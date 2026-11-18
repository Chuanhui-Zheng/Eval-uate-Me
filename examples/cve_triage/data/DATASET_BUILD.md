# Dataset build record

The committed snapshot is a reproducible, offline benchmark artifact. Normal evaluation reads only `snapshot.json` and
`cases.jsonl`; it does not need network access or an API key.

## Selection

- Source records: CISA Known Exploited Vulnerabilities catalog, joined to NVD 2.0 yearly JSON feeds.
- Years: 2017–2025.
- Per-year targets: 11 records for 2017–2020 and 2022–2025, 12 records for 2021.
- Selection ranking: ascending `sha256("cve-triage-v2:" + cve_id)` among eligible CISA records with an NVD match.
- Result: 100 distinct CVEs, all marked `known_exploited = true`.

## Case expansion

`build_dataset.py` derives 420 cases from the snapshot:

- 100 factual cases, one per CVE;
- 300 adversarial cases, three untrusted-description prompt-injection variants per CVE;
- 20 unknown identifiers (`CVE-2099-0001` through `CVE-2099-0020`).

The split is assigned at the CVE group level using `sha256("cve-triage-group-v2:" + group_id)`, so a base case and all
variants of the same CVE remain together. The current generated counts are 214 dev and 206 held-out cases with no group
appearing in both splits.

## Rebuilding from source exports

`build_snapshot.py` accepts the CISA KEV JSON export and a normalized JSON array of selected NVD records. The NVD feeds are
large, so extraction is intentionally kept outside the normal test path. After rebuilding the snapshot, run:

```bash
.venv/bin/python examples/cve_triage/data/build_dataset.py
.venv/bin/python -m eval_uate_me check examples/cve_triage/eval.toml
```

Review all changes to the committed snapshot and bump `cases.meta.toml` before treating a refreshed source export as a new
benchmark version.
