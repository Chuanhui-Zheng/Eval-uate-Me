"""LLM-based ticket triage target.

Sends the ticket subject and body to an LLM via the OpenRouter API and asks it
to classify the ticket into a category and urgency level.  The model must return
valid JSON — the prompt requests a ``response_format`` JSON schema.

Usage::

    export OPENROUTER_API_KEY=sk-...
    evalharness run eval.llm.toml

Config keys (all optional):
    model       OpenRouter model ID  (default: openai/gpt-4o-mini)
    max_tokens  Maximum tokens to generate  (default: 256)
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

from evalharness import Case, TargetOutput, register_target
from evalharness.targets import Target

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM = """\
You are a customer-support ticket routing agent.
Classify the incoming ticket into exactly ONE category and ONE urgency level.

Categories:
- account_access: login issues, password resets, 2FA problems, account deletion, locked accounts
- billing: charges, invoices, refunds, subscription changes, pricing questions
- bug: software errors, crashes, features not working, performance regressions
- feature_request: requests for new features or improvements
- how_to: usage questions, documentation requests, integration guidance

Urgency:
- high: immediate business impact, users completely blocked, data loss risk, SLA breach imminent
- medium: degraded experience, workaround exists, affects some users
- low: informational, improvement request, non-critical question

Respond ONLY with a JSON object:
{"category": "<category>", "urgency": "<urgency>"}
"""

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "ticket_classification",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["account_access", "billing", "bug", "feature_request", "how_to"],
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
            },
            "required": ["category", "urgency"],
            "additionalProperties": False,
        },
    },
}


def _openrouter_chat(
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": _RESPONSE_FORMAT,
    }).encode()
    req = urllib.request.Request(
        _OPENROUTER_URL,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()), {}


@register_target("ticket_triage_llm")
class LLMTriageTarget(Target):
    """Zero-shot LLM ticket classifier via OpenRouter."""

    evalharness_api = 1

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        max_tokens: int = 256,
        **_: object,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def run(self, case: Case) -> TargetOutput:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return TargetOutput(error="OPENROUTER_API_KEY not set")

        inp = case.input if isinstance(case.input, dict) else {}
        subject = inp.get("subject", "")
        body = inp.get("body", "")
        user_msg = f"Subject: {subject}\n\n{body}"

        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        t0 = time.monotonic()
        trace: list[dict[str, Any]] = []
        try:
            resp, _ = _openrouter_chat(messages, self.model, self.max_tokens, api_key)
            latency = time.monotonic() - t0

            usage_raw = resp.get("usage") or {}
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
            }
            trace.append({
                "tool": "openrouter_chat_completion",
                "model": self.model,
                "round": "final",
            })

            content = resp["choices"][0]["message"]["content"]
            output = json.loads(content)
            return TargetOutput(output=output, trace=trace, latency_s=latency, usage=usage)

        except Exception as exc:  # noqa: BLE001
            return TargetOutput(error=str(exc), trace=trace, latency_s=time.monotonic() - t0)
