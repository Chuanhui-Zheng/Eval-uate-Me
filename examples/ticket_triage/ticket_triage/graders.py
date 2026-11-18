"""Graders for the ticket triage example."""

from __future__ import annotations
from eval_uate_me import Case, Score, TargetOutput, register_grader
from eval_uate_me.graders import Grader

VALID_CATEGORIES = {"account_access", "billing", "bug", "feature_request", "how_to"}
VALID_URGENCIES = {"low", "medium", "high"}


@register_grader("ticket_schema")
class Schema(Grader):
    """Verifies the output is a dict with the required category and urgency fields."""
    eval_uate_me_api = 1
    name = "ticket_schema"
    selftest = "guardrail"

    def grade(self, case: Case, out: TargetOutput) -> Score:
        output = out.output
        if not isinstance(output, dict):
            return Score(self.name, 0.0, False, f"output must be a dict, got {type(output).__name__}")
        missing = [k for k in ("category", "urgency") if k not in output]
        if missing:
            return Score(self.name, 0.0, False, f"missing required fields: {missing}")
        if output["category"] not in VALID_CATEGORIES:
            return Score(self.name, 0.0, False,
                         f"category {output['category']!r} not in {sorted(VALID_CATEGORIES)}")
        if output["urgency"] not in VALID_URGENCIES:
            return Score(self.name, 0.0, False,
                         f"urgency {output['urgency']!r} not in {sorted(VALID_URGENCIES)}")
        return Score(self.name, 1.0, True, "")


@register_grader("ticket_category")
class Category(Grader):
    eval_uate_me_api = 1
    name = "ticket_category"
    selftest = "guardrail"

    def grade(self, case: Case, out: TargetOutput) -> Score:
        output = out.output if isinstance(out.output, dict) else {}
        got = output.get("category", "")
        expected = (case.expected or {}).get("category", "")

        if got not in VALID_CATEGORIES:
            return Score(self.name, 0.0, False, f"invalid category {got!r}")
        ok = got == expected
        return Score(self.name, 1.0 if ok else 0.0, ok,
                     f"got {got!r}, expected {expected!r}" if not ok else "")


@register_grader("ticket_urgency")
class Urgency(Grader):
    eval_uate_me_api = 1
    name = "ticket_urgency"
    selftest = "guardrail"

    def grade(self, case: Case, out: TargetOutput) -> Score:
        output = out.output if isinstance(out.output, dict) else {}
        got = output.get("urgency", "")
        expected = (case.expected or {}).get("urgency", "")

        if got not in VALID_URGENCIES:
            return Score(self.name, 0.0, False, f"invalid urgency {got!r}")
        ok = got == expected
        return Score(self.name, 1.0 if ok else 0.0, ok,
                     f"got {got!r}, expected {expected!r}" if not ok else "")
