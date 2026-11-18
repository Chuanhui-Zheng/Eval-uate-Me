"""LLM-based support reply target.

Sends the ticket to an LLM and asks it to draft a customer-facing reply.
The reply is open-ended text — it is graded by an LLM judge, not by exact match.

Usage::

    export OPENROUTER_API_KEY=sk-...
    eval_uate_me run eval.llm.toml
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

from eval_uate_me import Case, TargetOutput, register_target
from eval_uate_me.targets import Target

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM = """\
You are a customer support agent. Write a professional, empathetic, and helpful reply to the
incoming support ticket. Your reply should:
- Directly address the customer's problem
- Match the urgency of the situation
- Provide concrete next steps or a workaround where possible
- Be concise (2-4 short paragraphs at most)
- Never be dismissive, blame the customer, or make promises you cannot keep

Respond ONLY with the reply text — no subject line, no greeting formula like "Dear Customer",
just the body of the reply starting from the first sentence.
"""


def _openrouter_chat(
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    api_key: str,
) -> dict[str, Any]:
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        _OPENROUTER_URL,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


@register_target("support_reply_llm")
class LLMReplyTarget(Target):
    """Zero-shot LLM customer support reply writer via OpenRouter."""

    eval_uate_me_api = 1

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        max_tokens: int = 512,
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
        category = inp.get("category", "")
        urgency = inp.get("urgency", "")
        context = (case.metadata or {}).get("context", "")

        user_msg = f"Ticket subject: {subject}\n\nTicket body:\n{body}"
        if category or urgency:
            user_msg += f"\n\nClassification: category={category}, urgency={urgency}"
        if context:
            user_msg += f"\n\nBackground context (do not quote verbatim):\n{context}"

        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        t0 = time.monotonic()
        trace: list[dict[str, Any]] = []
        try:
            resp = _openrouter_chat(messages, self.model, self.max_tokens, api_key)
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
            reply = resp["choices"][0]["message"]["content"]
            return TargetOutput(output={"reply": reply}, trace=trace, latency_s=latency, usage=usage)

        except Exception as exc:  # noqa: BLE001
            return TargetOutput(error=str(exc), trace=trace, latency_s=time.monotonic() - t0)
