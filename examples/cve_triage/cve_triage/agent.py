"""A deterministic CVE triage reference agent.

The target reads a frozen NVD/CISA snapshot and produces a structured report.  It is intentionally
small: the example demonstrates what eval_uate_me can test, while an LLM-backed target can be plugged
in later without changing the graders or dataset contract.
"""
from __future__ import annotations

import json
from pathlib import Path

from eval_uate_me import Target, TargetOutput, register_target

from .schema import DISCLAIMER, UNKNOWN

FLAWS = ("none", "omit", "misclassify", "fabricate", "no_references", "overclaim", "inject")


def load_snapshot(path: str | Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {r["cve_id"]: r for r in data["records"]}


class ReferenceAgent:
    def __init__(self, snapshot: dict[str, dict], flaw: str = "none"):
        if flaw not in FLAWS:
            raise ValueError(f"flaw must be one of {FLAWS}, got {flaw!r}")
        self.snapshot, self.flaw = snapshot, flaw

    def report(self, case_input: dict) -> dict:
        cve_id = str(case_input.get("cve_id", ""))
        rec = self.snapshot.get(cve_id)
        if rec is None:
            report = {
                "report_version": "1", "cve_id": cve_id, "status": UNKNOWN,
                "summary": "No matching record exists in the frozen reference snapshot; no severity or remediation claim is made.",
                "severity": None, "cvss_score": None, "cwe": None, "known_exploited": False,
                "affected_product": [], "references": [],
                "recommended_actions": ["Verify the identifier against an authoritative vulnerability database."],
                "disclaimer": DISCLAIMER,
            }
        else:
            product = rec["product"] if rec["vendor"].lower() == rec["product"].lower() else f"{rec['vendor']} {rec['product']}"
            actions = ["Confirm whether the affected product and version are deployed, then apply the vendor security update or mitigation."]
            if rec["known_exploited"]:
                actions.insert(0, "Prioritize remediation because this CVE is listed in CISA's Known Exploited Vulnerabilities catalog.")
            report = {
                "report_version": "1", "cve_id": cve_id, "status": "known",
                "summary": rec["description"], "severity": rec["severity"], "cvss_score": rec["cvss_score"],
                "cwe": rec["cwe"], "known_exploited": rec["known_exploited"], "affected_product": [product],
                "references": list(rec["references"]), "recommended_actions": actions, "disclaimer": DISCLAIMER,
            }
        return self._flaw(report, case_input, rec)

    def _flaw(self, report: dict, case_input: dict, rec: dict | None) -> dict:
        if self.flaw == "omit":
            report.pop("cwe", None)
        elif self.flaw == "misclassify" and rec:
            report["severity"] = "LOW"
            report["cvss_score"] = 1.0
        elif self.flaw == "fabricate" and rec:
            report["affected_product"].append("Acme Unlisted Appliance")
            report["references"].append("https://example.invalid/fake-advisory")
        elif self.flaw == "no_references":
            report["references"] = []
        elif self.flaw == "overclaim" and rec:
            report["summary"] += " Active exploitation is confirmed."
        elif self.flaw == "inject":
            note = str(case_input.get("description", ""))
            lowered = note.lower()
            if any(token in lowered for token in ("ignore previous", "system override", "for this record", "assistant note")):
                report["summary"] += " " + note
        return report


@register_target("cve_triage")
class CveTriageTarget(Target):
    eval_uate_me_api = 1
    network = False

    def __init__(self, snapshot: str, flaw: str = "none"):
        self.agent = ReferenceAgent(load_snapshot(snapshot), flaw)

    def run(self, case):
        report = self.agent.report(case.input if isinstance(case.input, dict) else {})
        return TargetOutput(output=report, trace=[{"tool": "nvd_snapshot_lookup", "cve_id": report.get("cve_id")}])
