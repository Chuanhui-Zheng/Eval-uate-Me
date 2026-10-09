# CVE triage data sources

This example uses a frozen snapshot of public records retrieved on 2026-11-17:

- NIST National Vulnerability Database (NVD) 2.0 API: https://nvd.nist.gov/developers/vulnerabilities
- CISA Known Exploited Vulnerabilities catalog: https://www.cisa.gov/known-exploited-vulnerabilities-catalog

The snapshot contains 100 CVEs present in CISA's Known Exploited Vulnerabilities catalog, with descriptions, CVSS, CWE,
product, and references taken from the corresponding NVD 2.0 records. It is committed so tests are deterministic and do not
require network access. The generated `cases.jsonl` expands these records into 100 factual cases, 300 prompt-injection cases,
and 20 unknown identifiers. All variants of a CVE share one group split.

The selection is deterministic: 11 records from each year 2017–2020 and 2022–2025, 12 from 2021, ranked by
`sha256("cve-triage-v2:" + cve_id)`. The build inputs are not fetched during normal tests; `build_snapshot.py` can rebuild the
committed snapshot from normalized NVD JSON and the CISA KEV export. NVD and CISA records can change, so refresh the snapshot
deliberately, review the diff, and bump the dataset version before using it as a new benchmark. This is a security research
example, not a substitute for vendor advisories or a penetration test.
