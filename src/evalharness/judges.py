"""Judge backends: anything that turns a prompt into text. Used by the llm_judge grader and by pairwise / judge-check.

Keeping the backend behind a tiny interface means graders never import a vendor SDK, and tests can run against a deterministic
mock. A backend implements `complete(prompt) -> str`; it may also override `complete_with_usage` to report tokens and cost, and
`cache_id` to say what makes its answers different (model, endpoint) so a cache never mixes them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .registry import register_judge


@dataclass
class JudgeReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0  # 0.0 also means "unknown": a backend only reports cost when it was given prices
    cached: bool = False


class Judge(ABC):
    network: bool | None = None  # see Target.network

    @abstractmethod
    def complete(self, prompt: str) -> str:
        ...

    def complete_with_usage(self, prompt: str) -> JudgeReply:
        return JudgeReply(self.complete(prompt))

    def cache_id(self) -> str:
        """What distinguishes this judge's answers from another's (used in cache keys)."""
        return type(self).__name__


class JudgeCache:
    """On-disk cache of judge replies, keyed by (judge identity, prompt version, full prompt). Re-scoring an unchanged
    (case, output, rubric) never calls the model again, and changing the model or the prompt version never reuses a reply."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, judge_id: str, version: str, prompt: str) -> Path:
        raw = json.dumps([judge_id, version, prompt], ensure_ascii=False)
        return self.dir / (hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".json")

    def get(self, judge_id: str, version: str, prompt: str) -> JudgeReply | None:
        p = self._path(judge_id, version, prompt)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return JudgeReply(text=d["text"], input_tokens=int(d.get("input_tokens", 0)), output_tokens=int(d.get("output_tokens", 0)),
                              cost_usd=0.0, cached=True)  # a hit costs nothing now, whatever the original call cost
        except (ValueError, KeyError, TypeError):
            return None  # a corrupt entry is a miss

    def put(self, judge_id: str, version: str, prompt: str, reply: JudgeReply) -> None:
        d = asdict(reply)
        d.pop("cached", None)
        self._path(judge_id, version, prompt).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


class CachingJudge(Judge):
    """Wraps a judge with a JudgeCache."""

    def __init__(self, inner: Judge, cache: JudgeCache, version: str):
        self.inner, self.cache, self.version = inner, cache, version
        self.network = inner.network

    def complete(self, prompt: str) -> str:
        return self.complete_with_usage(prompt).text

    def complete_with_usage(self, prompt: str) -> JudgeReply:
        hit = self.cache.get(self.inner.cache_id(), self.version, prompt)
        if hit is not None:
            return hit
        reply = self.inner.complete_with_usage(prompt)
        self.cache.put(self.inner.cache_id(), self.version, prompt, reply)
        return reply

    def cache_id(self) -> str:
        return self.inner.cache_id()


def _between(tag: str, text: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", text, re.S)
    return m.group(1) if m else ""


@register_judge("mock")
class MockJudge(Judge):
    """Deterministic judge for tests/offline runs. With `reply`, always returns it; otherwise scores 5 if the reference text
    appears in the output, else 1 (for every named dimension, if the prompt asks for dimensions)."""
    network = False

    def __init__(self, reply: str | None = None):
        self.reply = reply

    def cache_id(self) -> str:
        return "mock:" + hashlib.sha256((self.reply or "").encode("utf-8")).hexdigest()[:12]

    def complete(self, prompt: str) -> str:
        if self.reply is not None:
            return self.reply
        if "<response_a>" in prompt:  # pairwise: prefer the response containing the reference, else tie
            ref = _between("reference", prompt).strip()
            a_has, b_has = bool(ref) and ref in _between("response_a", prompt), bool(ref) and ref in _between("response_b", prompt)
            winner = "A" if a_has and not b_has else "B" if b_has and not a_has else "tie"
            return json.dumps({"winner": winner, "reason": "reference found in " + winner})
        ref, out = _between("reference", prompt).strip(), _between("output", prompt)
        ok = bool(ref) and ref in out
        dims = re.findall(r'<dimension name="([^"]+)">', prompt)
        if dims:
            return json.dumps({d: {"score": 5 if ok else 1, "reason": "reference found" if ok else "reference missing"} for d in dims})
        return json.dumps({"score": 5 if ok else 1, "reason": "reference found" if ok else "reference missing"})


def post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float, retries: int, what: str) -> dict[str, Any]:
    """POST JSON, retrying transient failures (429, 5xx, network) with backoff. Raises RuntimeError with the cause."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json", **headers})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.load(resp)
            if not isinstance(data, dict):
                raise RuntimeError(f"{what}: the reply is not a JSON object")
            return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 529) or attempt == retries - 1:
                raise RuntimeError(f"{what} HTTP {e.code}: {e.read()[:200]!r}") from e
        except urllib.error.URLError as e:
            if attempt == retries - 1:
                raise RuntimeError(f"{what} network error: {e.reason}") from e
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _cost(in_tokens: int, out_tokens: int, price_in: float | None, price_out: float | None) -> float:
    if price_in is None and price_out is None:
        return 0.0
    return (in_tokens * (price_in or 0.0) + out_tokens * (price_out or 0.0)) / 1_000_000


@register_judge("anthropic")
class AnthropicJudge(Judge):
    """Calls the Anthropic Messages API over plain HTTPS (no SDK). Key from ANTHROPIC_API_KEY. Pass price_in_per_mtok and
    price_out_per_mtok (USD per million tokens) to get cost accounting; without them cost is reported as 0 (unknown)."""
    network = True  # case input, reference and output are sent to the API

    def __init__(self, model: str = "claude-sonnet-5-5", max_tokens: int = 512, timeout_s: float = 60,
                 api_key_env: str = "ANTHROPIC_API_KEY", retries: int = 3, base_url: str = "https://api.anthropic.com",
                 price_in_per_mtok: float | None = None, price_out_per_mtok: float | None = None):
        self.model, self.max_tokens, self.timeout_s = model, max_tokens, timeout_s
        self.api_key_env, self.retries, self.base_url = api_key_env, retries, base_url.rstrip("/")
        self.price_in, self.price_out = price_in_per_mtok, price_out_per_mtok

    def cache_id(self) -> str:
        return f"anthropic:{self.base_url}:{self.model}:{self.max_tokens}"

    def complete(self, prompt: str) -> str:
        return self.complete_with_usage(prompt).text

    def complete_with_usage(self, prompt: str) -> JudgeReply:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"environment variable {self.api_key_env} is not set")
        data = post_json(f"{self.base_url}/v1/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"},
                         {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0,
                          "messages": [{"role": "user", "content": prompt}]}, self.timeout_s, self.retries, "judge")
        usage = data.get("usage") or {}
        tin, tout = int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
        return JudgeReply("".join(b.get("text", "") for b in data.get("content", [])), tin, tout,
                          _cost(tin, tout, self.price_in, self.price_out))


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


@register_judge("openai_compat")
class OpenAICompatJudge(Judge):
    """Any server that speaks the OpenAI chat-completions API: OpenAI, Groq, Gemini's OpenAI-compatible endpoint, Ollama, vLLM,
    LM Studio and others. Set `base_url` (default OpenAI's) and `model`; the key comes from the environment variable named by
    `api_key_env` (empty string = send no Authorization header, for local servers). `headers` values may use ${ENV:NAME}.
    A base_url on localhost is treated as staying on this machine (privacy.local_only allows it); anything else sends case
    content to that server. Give price_in_per_mtok / price_out_per_mtok for cost accounting (otherwise cost is 0 = unknown)."""

    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1", api_key_env: str = "OPENAI_API_KEY",
                 max_tokens: int = 512, timeout_s: float = 60, retries: int = 3, temperature: float = 0.0,
                 headers: dict[str, str] | None = None, json_mode: bool = False,
                 price_in_per_mtok: float | None = None, price_out_per_mtok: float | None = None):
        from urllib.parse import urlparse
        from .adapters import expand_env
        from .config import ConfigError
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ConfigError(f"openai_compat base_url must start with http:// or https://, got {base_url!r}")
        self.model, self.base_url, self.api_key_env = model, base_url.rstrip("/"), api_key_env
        self.max_tokens, self.timeout_s, self.retries, self.temperature, self.json_mode = max_tokens, timeout_s, retries, temperature, json_mode
        self.headers = {k: expand_env(str(v), f"openai_compat headers.{k}") for k, v in (headers or {}).items()}
        self.price_in, self.price_out = price_in_per_mtok, price_out_per_mtok
        self.network = (parsed.hostname or "") not in _LOCAL_HOSTS

    def cache_id(self) -> str:
        return f"openai_compat:{self.base_url}:{self.model}:{self.temperature}:{self.max_tokens}:{self.json_mode}"

    def complete(self, prompt: str) -> str:
        return self.complete_with_usage(prompt).text

    def complete_with_usage(self, prompt: str) -> JudgeReply:
        headers = dict(self.headers)
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise RuntimeError(f"environment variable {self.api_key_env} is not set")
            headers["authorization"] = f"Bearer {key}"
        body: dict[str, Any] = {"model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens,
                                "messages": [{"role": "user", "content": prompt}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        data = post_json(f"{self.base_url}/chat/completions", headers, body, self.timeout_s, self.retries, "judge")
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"judge reply has no choices[0].message.content: {str(data)[:200]}") from e
        if not isinstance(text, str):
            raise RuntimeError(f"judge reply content is not text: {type(text).__name__}")
        usage = data.get("usage") or {}
        tin, tout = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
        return JudgeReply(text, tin, tout, _cost(tin, tout, self.price_in, self.price_out))
