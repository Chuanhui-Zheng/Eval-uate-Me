"""Tests for the support_reply example."""

from eval_uate_me import Case, TargetOutput
from support_reply.agent import SupportReplyTarget


def _case(category: str, urgency: str, subject: str = "Test", body: str = "Help.") -> Case:
    return Case(
        id=f"{category}-{urgency}",
        input={"subject": subject, "body": body, "category": category, "urgency": urgency},
        expected={"must_cover": [], "must_not": []},
    )


def test_oracle_returns_reply_for_all_urgencies():
    target = SupportReplyTarget()
    for category in ("account_access", "billing", "bug", "feature_request", "how_to"):
        for urgency in ("low", "medium", "high"):
            case = _case(category, urgency)
            out = target.run(case)
            assert out.error is None, f"{category}/{urgency}: error={out.error}"
            assert isinstance(out.output, dict), f"{category}/{urgency}: output not dict"
            reply = out.output.get("reply", "")
            assert len(reply) > 20, f"{category}/{urgency}: reply too short: {reply!r}"


def test_dismissive_flaw_produces_unhelpful_reply():
    target = SupportReplyTarget(flaw="dismissive")
    case = _case("bug", "high")
    out = target.run(case)
    assert out.error is None
    assert "FAQ" in out.output["reply"] or "cannot assist" in out.output["reply"]


def test_empty_flaw_produces_empty_reply():
    target = SupportReplyTarget(flaw="empty")
    case = _case("billing", "medium")
    out = target.run(case)
    assert out.output["reply"] == ""


def test_wrong_tone_flaw_produces_bad_reply():
    target = SupportReplyTarget(flaw="wrong_tone")
    case = _case("account_access", "high")
    out = target.run(case)
    assert "not our fault" in out.output["reply"]


def test_output_structure():
    target = SupportReplyTarget()
    case = _case("how_to", "low")
    out = target.run(case)
    assert isinstance(out.output, dict)
    assert "reply" in out.output
    assert isinstance(out.output["reply"], str)
