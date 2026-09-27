"""Built-in targets for systems you already have: an HTTP endpoint, or a Python function.

    [target]                                  [target]
    type = "http"                             type = "python"
    url = "http://localhost:8000/answer"      callable = "my_app.agent:answer"     # module:function
    headers = {Authorization = "Bearer ${ENV:MY_TOKEN}"}   # ${ENV:NAME} is read from the environment, never stored

`http` POSTs {"id", "input", "metadata"} as JSON and reads {"output": ..., optional "trace", "tool_calls", "usage",
"cost_usd", "error"}. `python` calls function(input) (or function(case) with with_case = true); it may return the output
itself or a TargetOutput, and may be `async def` (then the harness keeps many calls in flight). Neither needs a plugin class.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .config import ConfigError
from .models import Case, TargetOutput
from .registry import register_target
from .targets import Target

_ENV = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(text: str, where: str) -> str:
    """Replace ${ENV:NAME} with the environment variable, failing clearly if it is not set."""
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in os.environ:
            raise ConfigError(f"{where}: environment variable {name} is not set")
        return os.environ[name]
    return _ENV.sub(sub, text)


def _dig(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            raise KeyError(path)
    return data


@register_target("http")
class HttpTarget(Target):
    """POST each case to a URL. Transport errors, non-2xx statuses and malformed bodies become error results for that case
    (the run continues; use run.retries to retry them)."""
    evalharness_api = 1
    network = True

    def __init__(self, url: str, headers: dict[str, str] | None = None, timeout_s: float = 30.0,
                 output_field: str = "output", send_metadata: bool = True):
        if urlparse(url).scheme not in ("http", "https"):
            raise ConfigError(f"[target] url must start with http:// or https://, got {url!r}")
        self.url, self.timeout_s, self.output_field, self.send_metadata = url, timeout_s, output_field, send_metadata
        self.headers = {"Content-Type": "application/json", "Accept": "application/json",
                        **{k: expand_env(str(v), f"[target] headers.{k}") for k, v in (headers or {}).items()}}

    def run(self, case: Case) -> TargetOutput:
        payload = {"id": case.id, "input": case.input, **({"metadata": case.metadata} if self.send_metadata else {})}
        req = urllib.request.Request(self.url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return TargetOutput(error=f"HTTP {e.code}: {e.read()[:200].decode('utf-8', errors='replace')}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return TargetOutput(error=f"http error: {getattr(e, 'reason', e)}")
        try:
            body = json.loads(raw)
        except ValueError as e:
            return TargetOutput(error=f"invalid JSON response: {e}")
        if not isinstance(body, dict):
            return TargetOutput(error="response JSON must be an object with an 'output' field")
        if body.get("error"):
            return TargetOutput(error=str(body["error"]))
        try:
            output = _dig(body, self.output_field)
        except KeyError:
            return TargetOutput(error=f"response JSON has no '{self.output_field}' field")
        trace = list(body.get("trace", [])) + [{"tool": str(t)} for t in body.get("tool_calls", [])]
        usage = {k: float(v) for k, v in (body.get("usage") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if isinstance(body.get("cost_usd"), (int, float)):
            usage["cost_usd"] = float(body["cost_usd"])
        return TargetOutput(output=output, trace=trace, usage=usage)


def _to_output(value: Any) -> TargetOutput:
    return value if isinstance(value, TargetOutput) else TargetOutput(output=value)


@register_target("python")
class PythonTarget(Target):
    """Call a Python function. `callable = "package.module:function"`; add `paths` for folders to import from."""
    evalharness_api = 1

    def __init__(self, callable: str, with_case: bool = False, paths: list[str] | None = None,
                 network: bool | None = None):
        mod, _, attr = callable.partition(":")
        if not mod or not attr:
            raise ConfigError(f"[target] callable must look like 'package.module:function', got {callable!r}")
        for p in paths or []:
            if p not in sys.path:
                sys.path.insert(0, p)
        try:
            obj: Any = importlib.import_module(mod)
            for part in attr.split("."):
                obj = getattr(obj, part)
        except (ImportError, AttributeError) as e:
            raise ConfigError(f"[target] cannot load '{callable}': {type(e).__name__}: {e}"
                              + ("" if paths else " (set `paths = [...]` if the module is not importable from here)")) from e
        if not callable_(obj):
            raise ConfigError(f"[target] '{callable}' is not callable")
        self.fn, self.with_case, self.network = obj, with_case, network
        if inspect.iscoroutinefunction(obj):
            self.arun = self._arun  # makes the harness use its async executor

    def _arg(self, case: Case) -> Any:
        return case if self.with_case else case.input

    def run(self, case: Case) -> TargetOutput:
        if inspect.iscoroutinefunction(self.fn):
            import asyncio
            return asyncio.run(self._arun(case))
        return _to_output(self.fn(self._arg(case)))

    async def _arun(self, case: Case) -> TargetOutput:
        return _to_output(await self.fn(self._arg(case)))


def callable_(obj: Any) -> bool:  # builtin name `callable` is shadowed by the option name above
    return hasattr(obj, "__call__")
