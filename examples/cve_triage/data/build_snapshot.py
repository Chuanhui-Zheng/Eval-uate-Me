"""Build the committed CVE snapshot from normalized NVD and CISA exports.

The input files are deliberately external: download the official NVD 2.0 yearly feeds and the
CISA KEV catalog, normalize the selected NVD records to JSON, then run this script.  The committed
snapshot is the reproducibility boundary used by the offline evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


TARGETS = {"2017": 11, "2018": 11, "2019": 11, "2020": 11, "2021": 12,
           "2022": 11, "2023": 11, "2024": 11, "2025": 11}
SELECTION_SALT = "cve-triage-v2:"


def _metric(cve: dict) -> dict:
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        values = cve.get("metrics", {}).get(key, [])
        primary = next((x for x in values if x.get("type") == "Primary"), values[0] if values else None)
        if primary and primary.get("cvssData", {}).get("baseScore") is not None:
            data = primary["cvssData"]
            severity = data.get("baseSeverity") or primary.get("baseSeverity")
            if severity:
                return {"severity": severity, "cvss_score": data["baseScore"], "vector": data.get("vectorString")}
    raise ValueError(f"NVD record {cve.get('id')} has no usable CVSS metric")


def _description(cve: dict) -> str:
    value = next((x["value"] for x in cve.get("descriptions", []) if x.get("lang") == "en"), "")
    if not value or value.startswith("Rejected reason:"):
        raise ValueError(f"NVD record {cve.get('id')} has no usable English description")
    return value


def _cwe(cve: dict) -> str:
    for weakness in cve.get("weaknesses", []):
        value = next((x["value"] for x in weakness.get("description", []) if x.get("lang") == "en"), "")
        if value:
            return value
    raise ValueError(f"NVD record {cve.get('id')} has no CWE")


def _references(cve: dict, kev: dict) -> list[str]:
    nvd_url = f"https://nvd.nist.gov/vuln/detail/{cve['id']}"
    refs = [nvd_url]
    candidates = []
    for ref in cve.get("references", []):
        url = ref.get("url", "")
        tags = set(ref.get("tags", []))
        if not url or url == nvd_url or "Broken Link" in tags:
            continue
        priority = 0 if tags & {"Vendor Advisory", "Patch", "Mitigation"} else 1
        candidates.append((priority, url))
    notes = str(kev.get("notes", ""))
    for item in notes.split(";"):
        url = item.strip()
        if url.startswith("http") and "nvd.nist.gov" not in url:
            candidates.append((2, url))
    for _, url in sorted(candidates):
        if url not in refs:
            refs.append(url)
        if len(refs) == 2:
            break
    return refs


def build(cisa_path: Path, nvd_path: Path) -> dict:
    kev_rows = json.loads(cisa_path.read_text(encoding="utf-8"))["vulnerabilities"]
    nvd_rows = json.loads(nvd_path.read_text(encoding="utf-8"))
    nvd = {row["id"]: row for row in nvd_rows}
    by_year: dict[str, list[dict]] = defaultdict(list)
    for kev in kev_rows:
        cve_id = kev["cveID"]
        year = cve_id.split("-")[1]
        cve = nvd.get(cve_id)
        if year not in TARGETS or cve is None:
            continue
        try:
            description = _description(cve)
            metric = _metric(cve)
            cwe = _cwe(cve)
        except ValueError:
            continue
        if not cve.get("references"):
            continue
        by_year[year].append({"kev": kev, "cve": cve, "description": description, "metric": metric, "cwe": cwe})

    records: list[dict] = []
    for year, target in TARGETS.items():
        candidates = sorted(by_year[year], key=lambda row: hashlib.sha256(
            (SELECTION_SALT + row["cve"]["id"]).encode("utf-8")).hexdigest())
        if len(candidates) < target:
            raise ValueError(f"only {len(candidates)} eligible CVEs for {year}; need {target}")
        for row in candidates[:target]:
            kev, cve = row["kev"], row["cve"]
            records.append({
                "cve_id": cve["id"],
                "description": row["description"],
                "severity": row["metric"]["severity"],
                "cvss_score": row["metric"]["cvss_score"],
                "cvss_vector": row["metric"]["vector"],
                "cwe": row["cwe"],
                "vendor": kev["vendorProject"],
                "product": kev["product"],
                "known_exploited": True,
                "references": _references(cve, kev),
                "published": cve.get("published"),
                "last_modified": cve.get("lastModified"),
                "cisa_date_added": kev.get("dateAdded"),
                "cisa_due_date": kev.get("dueDate"),
                "cisa_ransomware_use": kev.get("knownRansomwareCampaignUse"),
                "cisa_required_action": kev.get("requiredAction"),
                "cisa_vulnerability_name": kev.get("vulnerabilityName"),
            })
    records.sort(key=lambda row: row["cve_id"])
    return {
        "dataset_version": "2.0",
        "selection": {"salt": SELECTION_SALT, "target_counts_by_year": TARGETS},
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cisa", type=Path, required=True)
    parser.add_argument("--nvd", type=Path, required=True, help="normalized JSON array of selected NVD CVE records")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("snapshot.json"))
    args = parser.parse_args()
    snapshot = build(args.cisa, args.nvd)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(snapshot['records'])} CVE records to {args.output}")


if __name__ == "__main__":
    main()
