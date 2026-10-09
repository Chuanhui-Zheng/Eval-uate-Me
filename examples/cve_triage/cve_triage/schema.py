from __future__ import annotations

DISCLAIMER = "Research and triage summary only; verify with the vendor advisory and a qualified security professional."
UNKNOWN = "unknown"


def validate_report(report) -> list[str]:
    if not isinstance(report, dict):
        return ["report must be an object"]
    required = {
        "report_version", "cve_id", "status", "summary", "severity", "cvss_score", "cwe",
        "known_exploited", "affected_product", "references", "recommended_actions", "disclaimer",
    }
    problems = [f"missing {k}" for k in sorted(required - set(report))]
    if report.get("report_version") != "1":
        problems.append("report_version must be '1'")
    if not isinstance(report.get("cve_id"), str) or not report.get("cve_id"):
        problems.append("cve_id must be non-empty text")
    if report.get("status") not in ("known", UNKNOWN):
        problems.append("status must be known or unknown")
    if not isinstance(report.get("summary"), str) or not report.get("summary", "").strip():
        problems.append("summary must be non-empty text")
    if report.get("status") == "known":
        if report.get("severity") not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            problems.append("severity must be a CVSS severity")
        if not isinstance(report.get("cvss_score"), (int, float)):
            problems.append("cvss_score must be numeric")
        if not isinstance(report.get("cwe"), str) or not report.get("cwe"):
            problems.append("cwe must be non-empty text")
    if not isinstance(report.get("known_exploited"), bool):
        problems.append("known_exploited must be boolean")
    if not isinstance(report.get("affected_product"), list) or not all(isinstance(x, str) for x in report.get("affected_product", [])):
        problems.append("affected_product must be a list of strings")
    if not isinstance(report.get("references"), list) or not all(isinstance(x, str) for x in report.get("references", [])):
        problems.append("references must be a list of strings")
    if not isinstance(report.get("recommended_actions"), list) or not all(isinstance(x, str) for x in report.get("recommended_actions", [])):
        problems.append("recommended_actions must be a list of strings")
    if not isinstance(report.get("disclaimer"), str) or not report.get("disclaimer", "").strip():
        problems.append("disclaimer must be non-empty text")
    return problems
