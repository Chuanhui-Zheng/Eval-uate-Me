"""Tests for the ticket_triage example."""

import pytest
from evalharness import Case, TargetOutput
from ticket_triage.agent import TicketTriageTarget
from ticket_triage.graders import Category, Schema, Urgency

GRADERS = [Schema(), Category(), Urgency()]

CASES = [
    {"id": "tt-001", "category": "account_access", "urgency": "high",
     "subject": "Cannot login to my account",
     "body": "Locked out, demo in 30 minutes."},
    {"id": "tt-003", "category": "feature_request", "urgency": "low",
     "subject": "Feature request: dark mode",
     "body": "Would love dark mode, not urgent."},
    {"id": "tt-004", "category": "bug", "urgency": "high",
     "subject": "App crashes when uploading files",
     "body": "Crashes on large PDFs. Need to submit by end of day today."},
]


def _make_case(c: dict) -> Case:
    return Case(
        id=c["id"],
        input={"subject": c["subject"], "body": c["body"]},
        expected={"category": c["category"], "urgency": c["urgency"]},
    )


def test_oracle_passes_all_graders():
    target = TicketTriageTarget()
    for c in CASES:
        case = _make_case(c)
        out = target.run(case)
        for grader in GRADERS:
            score = grader.grade(case, out)
            assert score.passed, f"{c['id']} {grader.name}: {score.reason}"


def test_category_grader_detects_wrong_category():
    target = TicketTriageTarget(flaw="wrong_category")
    case = _make_case(CASES[0])
    out = target.run(case)
    score = Category().grade(case, out)
    assert not score.passed


def test_urgency_grader_detects_always_low():
    target = TicketTriageTarget(flaw="always_low")
    high_urgency_case = _make_case(CASES[0])  # expected high
    out = target.run(high_urgency_case)
    score = Urgency().grade(high_urgency_case, out)
    assert not score.passed


def test_invalid_category_fails():
    case = _make_case(CASES[0])
    out = TargetOutput(output={"category": "unknown_cat", "urgency": "high"})
    score = Category().grade(case, out)
    assert not score.passed
    assert "invalid category" in score.reason


def test_invalid_urgency_fails():
    case = _make_case(CASES[0])
    out = TargetOutput(output={"category": "account_access", "urgency": "critical"})
    score = Urgency().grade(case, out)
    assert not score.passed
    assert "invalid urgency" in score.reason


def test_schema_grader_rejects_missing_fields():
    case = _make_case(CASES[0])
    out = TargetOutput(output={"category": "bug"})  # missing urgency
    score = Schema().grade(case, out)
    assert not score.passed
    assert "missing" in score.reason


def test_schema_grader_rejects_non_dict():
    case = _make_case(CASES[0])
    out = TargetOutput(output="account_access")
    score = Schema().grade(case, out)
    assert not score.passed


def test_schema_grader_accepts_valid_output():
    case = _make_case(CASES[0])
    out = TargetOutput(output={"category": "account_access", "urgency": "high"})
    score = Schema().grade(case, out)
    assert score.passed
