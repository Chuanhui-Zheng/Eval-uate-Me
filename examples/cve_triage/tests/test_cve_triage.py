from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalharness import Case
from cve_triage.agent import CveTriageTarget
from cve_triage.graders import Cwe, Identity, InjectionResistance, KnownExploited, NoFabrication, Product, References, Safety, Schema, Severity, ToolCall, _product_match
from cve_triage.llm_agent import CveTriageLlmTarget, _evidence_packet, _lookup_result
from cve_triage.schema import validate_report


HERE = Path(__file__).parents[1]
SNAPSHOT = str(HERE / "data" / "snapshot.json")
CASES = [Case(**json.loads(line)) for line in (HERE / "data" / "cases.jsonl").read_text().splitlines()]
GRADERS = [Schema(), Identity(), Severity(), Cwe(), KnownExploited(), Product(), References(), NoFabrication(), ToolCall(), InjectionResistance(), Safety()]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reference_agent_passes_every_grader(case):
    out = CveTriageTarget(SNAPSHOT).run(case)
    assert validate_report(out.output) == []
    assert all(g.grade(case, out).passed for g in GRADERS)


@pytest.mark.parametrize("flaw, expected_failed", [
    ("omit", {"cve_cwe"}),
    ("misclassify", {"cve_severity"}),
    ("fabricate", {"cve_product", "cve_references", "cve_no_fabrication"}),
    ("no_references", {"cve_references"}),
    ("overclaim", {"cve_safety"}),
    ("inject", {"cve_injection"}),
])
def test_each_deliberate_flaw_is_caught(flaw, expected_failed):
    case = next(c for c in CASES if "injection" in c.metadata.get("tags", []) or c.id == "CVE-2021-44228".lower())
    if flaw == "overclaim":
        case = next(c for c in CASES if "kev" in c.metadata.get("tags", []) and "injection" not in c.metadata.get("tags", []))
    if flaw == "inject":
        case = next(c for c in CASES if "injection" in c.metadata.get("tags", []))
    out = CveTriageTarget(SNAPSHOT, flaw).run(case)
    failed = {g.name for g in GRADERS if not g.grade(case, out).passed}
    assert expected_failed <= failed


def test_unknown_identifier_is_explicitly_not_known():
    case = next(c for c in CASES if c.id == "cve-2099-0001")
    out = CveTriageTarget(SNAPSHOT).run(case)
    assert out.output["status"] == "unknown"
    assert out.output["severity"] is None
    assert out.output["references"] == []


def test_expanded_dataset_has_grouped_splits():
    groups: dict[str, set[str]] = {}
    for case in CASES:
        group_id = case.metadata["group_id"]
        groups.setdefault(group_id, set()).add(case.metadata["split"])

    assert len(CASES) == 420
    assert len(groups) == 120
    assert sum("injection" in case.metadata.get("tags", []) for case in CASES) == 300
    assert sum("unknown" in case.metadata.get("tags", []) for case in CASES) == 20
    assert all(len(splits) == 1 for splits in groups.values())


def test_retrieval_tool_returns_full_record_and_explicit_miss():
    snapshot = {"CVE-2099-9999": {"cve_id": "CVE-2099-9999", "description": "test", "vendor": "Acme",
                                   "product": "Widget", "known_exploited": False}}
    found = _lookup_result(snapshot, "cve-2099-9999")
    missing = _lookup_result(snapshot, "CVE-2099-0001")

    assert found["found"] is True
    assert found["canonical_affected_product"] == "Acme Widget"
    assert missing["found"] is False
    assert _evidence_packet(snapshot["CVE-2099-9999"], "summary")["cve_id"] == "CVE-2099-9999"


@pytest.mark.parametrize("want,got,expected", [
    # exact match
    ("Drupal Drupal Core", "Drupal Drupal Core", True),
    # vendor prefix dropped (most common LLM pattern)
    ("Drupal Drupal Core", "Drupal Core", True),
    ("Microsoft Win32k", "Win32k", True),
    ("Android Android Kernel", "Android Kernel", True),
    ("Google Chromium V8", "Chromium V8", True),
    ("OSGeo GeoServer", "GeoServer", True),
    ("VMware Workspace ONE Access and Identity Manager", "Workspace ONE Access and Identity Manager", True),
    # got is word-aligned substring of want (NVD joined multiple, LLM split)
    ("Apple iOS, iPadOS, and watchOS", "iOS", True),
    ("Apple iOS, iPadOS, and watchOS", "iPadOS", True),
    ("Apple iOS, iPadOS, and watchOS", "watchOS", True),
    ("Trend Micro Apex One and OfficeScan", "Trend Micro Apex One", True),
    # got includes vendor that want omits
    ("Win32k", "Microsoft Win32k", True),
    # unrelated products must NOT match
    ("Microsoft Win32k", "Acme Unlisted Appliance", False),
    ("Drupal Drupal Core", "WordPress Core", False),
    ("Apache Log4j", "Apache Struts", False),
])
def test_product_match(want, got, expected):
    assert _product_match(want, got) == expected


def test_retrieval_target_executes_tool_then_report(monkeypatch):
    case = next(c for c in CASES if "injection" not in c.metadata.get("tags", []))
    target = CveTriageLlmTarget(SNAPSHOT, evidence_mode="retrieval")
    expected = CveTriageTarget(SNAPSHOT).run(case).output
    calls = []

    def fake_request(key, messages, *, tools=None, response_format=None):
        calls.append({"messages": messages, "tools": tools, "response_format": response_format})
        # Round 0 (tools, no prior tool msgs): model calls lookup_cve
        if tools and not any(m.get("role") == "tool" for m in messages):
            return ({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function", "function": {
                    "name": "lookup_cve", "arguments": json.dumps({"cve_id": case.input["cve_id"]})}}]}}]},
                    {"input_tokens": 3, "output_tokens": 2})
        # Round 1 (tools, tool msg present): model is done, no more tool calls
        if tools:
            return ({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": []}}]},
                    {"input_tokens": 2, "output_tokens": 1})
        # Final constrained call (response_format): return structured output
        return ({"choices": [{"message": {"content": json.dumps(expected)}}]},
                {"input_tokens": 5, "output_tokens": 7})

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(target, "_request", fake_request)
    result = target.run(case)

    assert result.output == expected
    assert result.usage == {"input_tokens": 10, "output_tokens": 10}
    # call 0: loop round 0 with tools, call 1: loop round 1 with tools (no tool_calls → break), call 2: final with schema
    assert calls[0]["tools"] is not None
    assert calls[1]["tools"] is not None
    assert calls[2]["response_format"] is not None
    assert calls[2]["messages"][-1]["role"] == "tool"


def test_retrieval_session_mode_accumulates_history(monkeypatch):
    cases = [c for c in CASES if "injection" not in c.metadata.get("tags", [])][:2]
    target = CveTriageLlmTarget(SNAPSHOT, evidence_mode="retrieval", session_mode=True)
    call_counts = []

    def fake_request(key, messages, *, tools=None, response_format=None):
        call_counts.append(len(messages))
        if tools and not any(m.get("role") == "tool" for m in messages
                             if m not in target._session_messages):
            cve_id = cases[len([c for c in call_counts if c == call_counts[-1]]) - 1].input["cve_id"] \
                if len(call_counts) <= 2 else cases[0].input["cve_id"]
            # simplified: just break immediately (no tool calls)
            return ({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": []}}]},
                    {"input_tokens": 1, "output_tokens": 1})
        return ({"choices": [{"message": {"content": json.dumps({"status": "known", "cve_id": "X",
            "report_version": "1", "summary": "s", "severity": None, "cvss_score": None,
            "cwe": None, "known_exploited": False, "affected_product": [], "references": [],
            "recommended_actions": [], "disclaimer": "d"})}}]},
                {"input_tokens": 2, "output_tokens": 2})

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(target, "_request", fake_request)

    target.run(cases[0])
    history_after_first = len(target._session_messages)
    target.run(cases[1])
    history_after_second = len(target._session_messages)

    assert history_after_second > history_after_first  # session memory grew
    target.reset_session()
    assert target._session_messages == []
