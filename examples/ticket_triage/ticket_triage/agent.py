"""Deterministic ticket triage target.

Routes support tickets by keyword matching. Used as the oracle / baseline in
eval.toml and as the reference for mutant generation.
"""

from __future__ import annotations
import json
from eval_uate_me import Case, TargetOutput, register_target
from eval_uate_me.targets import Target

CATEGORIES = ("account_access", "billing", "bug", "feature_request", "how_to")
URGENCIES = ("low", "medium", "high")

_CATEGORY_SIGNALS: dict[str, list[str]] = {
    "account_access": ["login", "log in", "password", "2fa", "two-factor", "locked out",
                       "can't access", "cannot access", "verify", "verification", "delete my account",
                       "account deletion", "gdpr"],
    "billing": ["charge", "payment", "invoice", "refund", "billing", "subscription",
                "charged", "paid", "receipt", "pricing", "enterprise plan", "upgrade"],
    "bug": ["crash", "error", "broken", "not working", "doesn't work", "bug", "fails",
            "stopped working", "slow", "performance", "missing", "wrong", "503", "outage",
            "down", "sync", "notification"],
    "feature_request": ["feature request", "suggestion", "would love", "would be nice",
                        "request:", "suggest", "dark mode", "keyboard shortcut"],
    "how_to": ["how do i", "how to", "can i", "is it possible", "documentation",
               "best practices", "guidance", "where do i", "export"],
}

_URGENCY_SIGNALS: dict[str, list[str]] = {
    "high": ["urgent", "immediately", "asap", "critical", "emergency", "demo in",
             "end of day", "today", "major", "200 users", "completely", "entirely",
             "entire", "our whole team", "locked out", "outage", "down"],
    "low": ["not urgent", "suggestion", "would love", "feature request", "whenever",
            "low priority", "tax records", "invoice", "best practices"],
}


def _classify(text: str) -> tuple[str, str]:
    lower = text.lower()
    category_scores: dict[str, int] = {c: 0 for c in CATEGORIES}
    for cat, signals in _CATEGORY_SIGNALS.items():
        for sig in signals:
            if sig in lower:
                category_scores[cat] += 1
    category = max(category_scores, key=lambda c: category_scores[c])

    urgency_scores: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for urg, signals in _URGENCY_SIGNALS.items():
        for sig in signals:
            if sig in lower:
                urgency_scores[urg] += 1
    # "not urgent" negates the "urgent" signal
    if "not urgent" in lower or "not an urgent" in lower:
        urgency_scores["high"] = max(0, urgency_scores["high"] - 1)
        urgency_scores["low"] += 1
    if urgency_scores["high"] > 0:
        urgency = "high"
    elif urgency_scores["low"] > 0:
        urgency = "low"
    else:
        urgency = "medium"

    return category, urgency


@register_target("ticket_triage")
class TicketTriageTarget(Target):
    eval_uate_me_api = 1

    def __init__(self, flaw: str | None = None, **_: object) -> None:
        self.flaw = flaw

    def run(self, case: Case) -> TargetOutput:
        inp = case.input if isinstance(case.input, dict) else {}
        text = f"{inp.get('subject', '')} {inp.get('body', '')}"
        category, urgency = _classify(text)

        if self.flaw == "wrong_category":
            categories = [c for c in CATEGORIES if c != category]
            category = categories[0]
        elif self.flaw == "wrong_urgency":
            urgencies = [u for u in URGENCIES if u != urgency]
            urgency = urgencies[0]
        elif self.flaw == "always_low":
            urgency = "low"
        elif self.flaw == "always_how_to":
            category = "how_to"

        return TargetOutput(output={"category": category, "urgency": urgency})
