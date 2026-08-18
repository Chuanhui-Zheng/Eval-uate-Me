"""Console reporting and run-to-run comparison."""
from __future__ import annotations

import json
from pathlib import Path

from .formats import check_version, read_json
from .models import CaseResult
from .stats import holm_adjust, paired_delta_ci, paired_permutation_p


def print_report(results: list[CaseResult], summary: dict, out_dir: Path) -> None:
    repeated = summary.get("repeats", 1) > 1
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        label = f"{r.case.id}#{r.attempt}" if repeated else r.case.id
        print(f"[{mark}] {label}  ({r.result.latency_s:.2f}s)")
        if r.result.error:
            print(f"        error: {r.result.error}")
        for s in r.scores:
            if not s.passed:
                print(f"        {s.grader}{' (advisory)' if s.role == 'advisory' else ''}: {s.reason}")
    print()
    lo, hi = summary["pass_rate_ci95"]
    print(f"{summary['passed']}/{summary['total']} passed, pass rate {summary['pass_rate']:.0%} "
          f"(95% CI {lo:.0%}-{hi:.0%} over {summary['cases']} cases), "
          f"{summary['errors']} errors, p50 {summary['latency_p50_s']:.2f}s")
    if summary.get("split", "all") != "all":
        print(f"  split: {summary['split']} ({summary['cases']} cases)")
    if summary.get("heldout_looks"):
        n = summary["heldout_looks"]
        print(f"  held-out look #{n} on this dataset version" + ("" if n == 1 else
              ": repeated looks make this score less independent of your tuning"))
    if summary.get("privacy_store") == "scores_only":
        print("  privacy mode: content is not stored; reasons and errors are shown as [redacted]")
    if summary["errors"]:
        lo2, hi2 = summary["pass_rate_answered_ci95"]
        print(f"  {summary['errors']} attempts errored ({summary['error_rate']:.0%}) and count as failures above; "
              f"pass rate on answered cases only: {summary['pass_rate_answered']:.0%} "
              f"(95% CI {lo2:.0%}-{hi2:.0%}, {summary['cases_answered']} cases)")
    if summary.get("incomplete"):
        print(f"  INCOMPLETE: {summary['incomplete']} of {summary['planned']} jobs not run "
              f"(budget ${summary.get('max_cost_usd')} reached, ${summary.get('cost_usd_spent', 0):.4f} spent); "
              "the pass rate covers completed jobs only")
    if summary.get("budget_warning"):
        print(f"  warning: {summary['budget_warning']}")
    if summary.get("usage_total"):
        print("  usage: " + ", ".join(f"{k}={v:g}" for k, v in sorted(summary["usage_total"].items())))
    if summary.get("retried"):
        print(f"  {summary['retried']} attempts needed retries")
    if repeated:
        k = summary["repeats"]
        print(f"  repeats={k}  pass@1={summary['pass_at_1']:.2f}  pass@{k}={summary[f'pass_at_{k}']:.2f}  "
              f"pass^{k}={summary['pass_all']:.2f}")
        if summary["flaky"]:
            print(f"  flaky cases: {summary['flaky']}")
    for g, v in summary["mean_score_by_grader"].items():
        print(f"  {g}: mean {v:.2f}")
    if summary.get("advisory_failures"):
        print("  advisory checks failed (not counted): "
              + ", ".join(f"{k}={v}" for k, v in sorted(summary["advisory_failures"].items())))
    for g, per in summary.get("dimension_means", {}).items():
        print(f"  {g} dimensions: " + ", ".join(f"{d} {v:.2f}" for d, v in per.items()))
    if summary.get("judge_cost_usd"):
        print(f"  judge cost: ${summary['judge_cost_usd']:.4f}")
    for t, d in summary.get("by_tag", {}).items():
        print(f"  tag {t}: {d['pass_rate']:.0%} of {d['cases']} cases")
    if summary.get("failure_reasons"):
        print("  failure reasons: " + ", ".join(f"{k}={v}" for k, v in sorted(summary["failure_reasons"].items())))
    print(f"results: {out_dir}")


def _load(run_dir: Path) -> tuple[dict[str, float], dict[str, list[str]]]:
    """(case id -> pass rate across attempts, case id -> tags)."""
    f = Path(run_dir) / "results.jsonl"
    acc: dict[str, list[bool]] = {}
    tags: dict[str, list[str]] = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = check_version(json.loads(line), f)
            acc.setdefault(d["case"]["id"], []).append(d["passed"])
            md = d["case"].get("metadata", {})
            tags[d["case"]["id"]] = [str(t) for t in md.get("tags", [])] + ([str(md["category"])] if md.get("category") else [])
    return {k: sum(v) / len(v) for k, v in acc.items()}, tags


def _manifest(run_dir: Path) -> dict:
    f = Path(run_dir) / "manifest.json"
    return read_json(f) if f.exists() else {}


def show(run_dir: Path) -> None:
    m, s = _manifest(run_dir), read_json(Path(run_dir) / "summary.json")
    for k in ("name", "status", "split", "heldout_looks", "resumes", "started_at", "harness_version", "python", "n_cases", "repeats", "seed",
              "dataset_sha256", "config_sha256"):
        print(f"{k}: {m.get(k)}")
    dm = m.get("dataset_meta")
    print("dataset: " + (f"{dm.get('name', '?')} v{dm.get('version', '?')} | source: {dm.get('source', '?')} | "
                         f"retrieved: {dm.get('retrieved', '?')} | licence: {dm.get('license', '?')}"
                         if dm else "no metadata file"))
    g = m.get("git", {})
    print(f"git: {g.get('commit')}{' (dirty)' if g.get('dirty') else ''}")
    print(f"target: {m.get('target')}")
    print(f"pass_rate: {s['pass_rate']:.1%}  cases: {s['cases']}  errors: {s['errors']}")


def _tag_rows(shared: list[str], ra: dict, rb: dict, tags: dict[str, list[str]]) -> list[dict]:
    """Per-tag deltas. Looking at many slices makes some look 'significant' by luck, so p-values are Holm-adjusted
    across all the tags compared; only the adjusted value should be read as evidence."""
    groups: dict[str, list[str]] = {}
    for k in shared:
        for t in tags.get(k, []):
            groups.setdefault(t, []).append(k)
    rows = []
    for t, ids in groups.items():
        delta, lo, hi = paired_delta_ci([ra[k] for k in ids], [rb[k] for k in ids])
        rows.append({"tag": t, "n": len(ids), "delta": delta, "lo": lo, "hi": hi,
                     "p": paired_permutation_p([rb[k] - ra[k] for k in ids])})
    adj = holm_adjust([r["p"] for r in rows])
    for r, a in zip(rows, adj):
        r["p_adj"] = a
    return sorted(rows, key=lambda r: r["p_adj"])


def compare_data(a: Path, b: Path) -> dict:
    """Everything `compare` knows, as data (so it can be printed as text or as Markdown)."""
    (ra, tags_a), (rb, _) = _load(a), _load(b)
    shared = sorted(ra.keys() & rb.keys())
    ma, mb = _manifest(a), _manifest(b)
    warnings = []
    if ma and mb and ma.get("split", "all") != mb.get("split", "all"):
        warnings.append(f"runs use different splits ({ma.get('split', 'all')} vs {mb.get('split', 'all')}); "
                        "only shared case ids are compared and the numbers are not like for like")
    if ma and mb and ma.get("dataset_sha256") != mb.get("dataset_sha256"):
        warnings.append("datasets differ between runs; only shared case ids are compared")
    d = {"a": a, "b": b, "warnings": warnings, "shared": len(shared),
         "regressions": [k for k in shared if rb[k] < ra[k]], "improved": [k for k in shared if rb[k] > ra[k]],
         "only": sorted(ra.keys() ^ rb.keys()), "stats": None, "tags": []}
    if shared:
        delta, lo, hi = paired_delta_ci([ra[k] for k in shared], [rb[k] for k in shared])
        d["stats"] = {"delta": delta, "lo": lo, "hi": hi, "p": paired_permutation_p([rb[k] - ra[k] for k in shared]),
                      "pass_a": sum(ra[k] for k in shared) / len(shared), "pass_b": sum(rb[k] for k in shared) / len(shared),
                      "significant": lo > 0 or hi < 0}
        d["tags"] = _tag_rows(shared, ra, rb, tags_a)
    return d


def compare(a: Path, b: Path) -> int:
    """Compare run A (baseline) to run B. Returns number of regressed cases."""
    d = compare_data(a, b)
    print(f"baseline: {a}\ncandidate: {b}")
    for w in d["warnings"]:
        print(f"WARNING: {w}")
    st = d["stats"]
    if st:
        verdict = "significant" if st["significant"] else "not significant (CI includes 0)"
        print(f"pass-rate delta: {st['delta']:+.1%} (95% CI {st['lo']:+.1%} to {st['hi']:+.1%}, p = {st['p']:.3f}) -> {verdict}")
        if d["tags"]:
            print(f"by tag ({len(d['tags'])} compared; p-values Holm-adjusted for looking at {len(d['tags'])} slices):")
            for r in d["tags"]:
                flag = "  <- significant after correction" if r["p_adj"] < 0.05 else ""
                print(f"  {r['tag']:<20} n={r['n']:<4} delta {r['delta']:+.1%} (95% CI {r['lo']:+.1%} to {r['hi']:+.1%})  "
                      f"p={r['p']:.3f}  adjusted p={r['p_adj']:.3f}{flag}")
    print(f"regressions ({len(d['regressions'])}): {d['regressions']}")
    print(f"improved ({len(d['improved'])}): {d['improved']}")
    if d["only"]:
        print(f"only in one run: {d['only']}")
    return len(d["regressions"])


def _md(text) -> str:
    """Escape text for a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def markdown_compare(a: Path, b: Path, title: str = "Eval comparison") -> tuple[str, int]:
    """A GitHub-flavoured Markdown summary suitable for a pull-request comment, and the number of regressed cases."""
    d = compare_data(a, b)
    st = d["stats"]
    lines = [f"### {_md(title)}", ""]
    for w in d["warnings"]:
        lines.append(f"> :warning: {_md(w)}")
    if d["warnings"]:
        lines.append("")
    if st:
        mark = ":red_circle: **regression**" if st["significant"] and st["delta"] < 0 else \
               ":green_circle: **improvement**" if st["significant"] else ":white_circle: no significant change"
        lines += ["| | baseline | candidate | change |", "|---|---|---|---|",
                  f"| pass rate ({d['shared']} cases) | {st['pass_a']:.1%} | {st['pass_b']:.1%} | {st['delta']:+.1%} "
                  f"(95% CI {st['lo']:+.1%} to {st['hi']:+.1%}, p = {st['p']:.3f}) |", "", mark, ""]
    if d["tags"]:
        lines += ["| tag | cases | change | adjusted p |", "|---|---|---|---|"]
        for r in d["tags"]:
            lines.append(f"| {_md(r['tag'])} | {r['n']} | {r['delta']:+.1%} | {r['p_adj']:.3f}"
                         + (" :red_circle:" if r["p_adj"] < 0.05 and r["delta"] < 0 else " :green_circle:" if r["p_adj"] < 0.05 else "") + " |")
        lines += ["", "<sub>p-values are Holm-adjusted across the tags compared; read the adjusted value.</sub>", ""]
    shown = d["regressions"][:15]
    lines.append(f"**Regressed cases ({len(d['regressions'])}):** " + (", ".join(f"`{_md(k)}`" for k in shown) or "none")
                 + (f" and {len(d['regressions']) - 15} more" if len(d["regressions"]) > 15 else ""))
    lines.append(f"**Improved cases ({len(d['improved'])}).**")
    if d["only"]:
        lines.append(f"{len(d['only'])} case(s) exist in only one run.")
    return "\n".join(lines) + "\n", len(d["regressions"])
