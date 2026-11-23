"""Deterministic checks for the support agent's explicit output contract."""
from eval_uate_me import Grader, Score, register_grader


@register_grader("support_contract")
class SupportContract(Grader):
    eval_uate_me_api = 1
    name = "support_contract"
    semantic = False
    selftest = "guardrail"

    def grade(self, case, out):
        expected = case.expected or {}
        actual = out.output if isinstance(out.output, dict) else {}
        checks = {
            "category": actual.get("category") == expected.get("category"),
            "non_empty_reply": bool(str(actual.get("reply", "")).strip()),
            "confidence_range": isinstance(actual.get("confidence"), (int, float))
                and 0.0 <= actual["confidence"] <= 1.0,
        }
        confidence = actual.get("confidence")
        expected_decision = ("done" if isinstance(confidence, (int, float)) and confidence >= 0.7 and actual.get("reply")
                             else "human_review")
        checks["confidence_route"] = actual.get("decision") == expected_decision
        ok = all(checks.values())
        failed = [name for name, passed in checks.items() if not passed]
        return Score(self.name, sum(checks.values()) / len(checks), ok,
                     "contract failed: " + ", ".join(failed) if failed else "all contract checks passed")
