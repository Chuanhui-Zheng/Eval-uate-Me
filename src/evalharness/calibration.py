"""Check an automatic grader against human labels.

Labels come from `label import` (labels.jsonl; several reviewers allowed) or, for backward compatibility,
from `metadata.human_pass` in the dataset. With several reviewers the truth for a case is the majority;
ties are set aside as disputed. Labels whose output has since changed are stale and ignored.
`--grader overall` compares the final pass/fail verdict; any other name compares that one grader.

An LLM judge you have not calibrated is an unverified metric.
"""
from __future__ import annotations

import random
from itertools import combinations
from pathlib import Path
from typing import Any

from .config import ConfigError
from .labels import LABEL_FILE, load_labels, output_hash, read_rows
from .stats import cohen_kappa

MIN_LABELS = 30  # below this the estimates are too noisy to trust


def _grader_verdict(row: dict, grader: str) -> bool | None:
    if grader == "overall":
        return bool(row["passed"]) if row["result"].get("error") is None else None
    return next((s["passed"] for s in row["scores"] if s["grader"] == grader), None)


def _collect_labels(run_dir: Path, rows: list[dict]):
    """Return ({key: {labeler: bool}}, {key: {labeler: notes}}, stale_count, source).
    Stale = the output changed since it was labelled."""
    by_key = {(r["case"]["id"], r.get("attempt", 0)): r for r in rows}
    out: dict[tuple, dict[str, bool]] = {}
    notes: dict[tuple, dict[str, str]] = {}
    stale = 0
    if (Path(run_dir) / LABEL_FILE).exists():
        for key, per_labeler in load_labels(run_dir).items():
            row = by_key.get(key)
            for who, lab in per_labeler.items():
                if row is None or lab.get("output_sha256") != output_hash(row["result"].get("output")):
                    stale += 1
                    continue
                out.setdefault(key, {})[who] = bool(lab["human_pass"])
                notes.setdefault(key, {})[who] = lab.get("notes", "")
        return out, notes, stale, LABEL_FILE
    for key, row in by_key.items():
        human = row["case"].get("metadata", {}).get("human_pass")
        if human is not None:
            out[key] = {"metadata": bool(human)}
    return out, notes, 0, "metadata.human_pass"


def _ci(pairs: list[tuple[bool, bool]], iters: int = 2000, seed: int = 0) -> dict[str, list[float]]:
    rng = random.Random(seed)
    n = len(pairs)
    agr, kap = [], []
    for _ in range(iters):
        s = [pairs[rng.randrange(n)] for _ in range(n)]
        agr.append(sum(a == h for a, h in s) / n)
        kap.append(cohen_kappa([a for a, _ in s], [h for _, h in s]))
    agr.sort()
    kap.sort()
    lo, hi = int(0.025 * iters), int(0.975 * iters) - 1
    return {"agreement": [agr[lo], agr[hi]], "kappa": [kap[lo], kap[hi]]}


def _labeler_agreement(labels: dict[tuple, dict[str, bool]]) -> dict:
    by_who: dict[str, dict[tuple, bool]] = {}
    for key, per in labels.items():
        for who, v in per.items():
            by_who.setdefault(who, {})[key] = v
    pairs: list[dict[str, Any]] = []
    for a, b in combinations(sorted(by_who), 2):
        shared = sorted(set(by_who[a]) & set(by_who[b]))
        if len(shared) >= 2:
            xs, ys = [by_who[a][k] for k in shared], [by_who[b][k] for k in shared]
            pairs.append({"a": a, "b": b, "n": len(shared), "agreement": sum(x == y for x, y in zip(xs, ys)) / len(shared),
                          "kappa": cohen_kappa(xs, ys)})
    return {"pairs": pairs, "mean_kappa": sum(p["kappa"] for p in pairs) / len(pairs) if pairs else None}


def calibrate(run_dir: Path, grader: str) -> dict:
    rows = read_rows(run_dir)
    by_key = {(r["case"]["id"], r.get("attempt", 0)): r for r in rows}
    labels, _, stale, source = _collect_labels(run_dir, rows)

    pairs: list[tuple[bool, bool]] = []  # (grader verdict, human truth)
    disputed = 0
    for key, per in labels.items():
        yes = sum(per.values())
        if yes * 2 == len(per):  # tie between reviewers
            disputed += 1
            continue
        auto = _grader_verdict(by_key[key], grader)
        if auto is not None:
            pairs.append((auto, yes * 2 > len(per)))
    n = len(pairs)
    if n == 0:
        raise ConfigError(f"no labelled attempts with a '{grader}' verdict in {run_dir} "
                          f"(source: {source}); run `evalharness label export`/`import` first")

    tp = sum(a and h for a, h in pairs)
    fp = sum(a and not h for a, h in pairs)
    fn = sum((not a) and h for a, h in pairs)
    tn = sum((not a) and (not h) for a, h in pairs)
    ratio = lambda num, den: num / den if den else None  # noqa: E731
    warnings = []
    if n < MIN_LABELS:
        warnings.append(f"only {n} labelled attempts (< {MIN_LABELS}): estimates are noisy, see the confidence intervals")
    if stale:
        warnings.append(f"{stale} labels ignored because the output they judged has changed")
    if disputed:
        warnings.append(f"{disputed} attempts set aside because reviewers tied")
    return {
        "grader": grader, "source": source, "n": n, "skipped": len(rows) - n,
        "agreement": (tp + tn) / n, "kappa": cohen_kappa([a for a, _ in pairs], [h for _, h in pairs]),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn), "specificity": ratio(tn, tn + fp),
        "ci95": _ci(pairs), "stale": stale, "disputed": disputed,
        "labelers": sorted({w for per in labels.values() for w in per}),
        "labeler_agreement": _labeler_agreement(labels), "warnings": warnings,
    }


def format_calibration(r: dict) -> str:
    f = lambda x: "n/a" if x is None else f"{x:.2f}"  # noqa: E731
    lines = [f"n={r['n']} agreement={r['agreement']:.0%} kappa={r['kappa']:.2f} confusion={r['confusion']}",
             f"grader '{r['grader']}' vs human labels from {r['source']} ({', '.join(r['labelers'])})",
             f"  95% CI: agreement {r['ci95']['agreement'][0]:.0%}-{r['ci95']['agreement'][1]:.0%}, "
             f"kappa {r['ci95']['kappa'][0]:.2f} to {r['ci95']['kappa'][1]:.2f}",
             f"  when the grader says pass, humans agree {f(r['precision'])} of the time (precision); "
             f"it catches {f(r['recall'])} of the passes humans see (recall); "
             f"it correctly fails {f(r['specificity'])} of the fails (specificity)"]
    la = r["labeler_agreement"]
    for p in la["pairs"]:
        lines.append(f"  reviewers {p['a']} vs {p['b']}: agree {p['agreement']:.0%} on {p['n']} shared, kappa {p['kappa']:.2f}")
    lines += [f"  warning: {w}" for w in r["warnings"]]
    return "\n".join(lines)


def disagreements(run_dir: Path, grader: str = "overall") -> list[dict]:
    """Attempts where humans and the grader differ, most worrying first:
    false_pass (grader passed what humans failed), false_fail, then reviewers_disagree (tied humans).
    These are where to fix a rubric, a reference answer, or the grader itself."""
    rows = read_rows(run_dir)
    by_key = {(r["case"]["id"], r.get("attempt", 0)): r for r in rows}
    labels, notes, _, _ = _collect_labels(run_dir, rows)
    found = []
    for key, per in labels.items():
        row = by_key[key]
        auto = _grader_verdict(row, grader)
        if auto is None:
            continue
        yes = sum(per.values())
        if yes * 2 == len(per):
            kind = "reviewers_disagree"
        elif auto != (yes * 2 > len(per)):
            kind = "false_pass" if auto else "false_fail"
        else:
            continue
        if grader == "overall":
            why = "; ".join(f"{s['grader']}: {s['reason']}" for s in row["scores"] if not s["passed"] and s.get("role", "required") == "required")
        else:
            why = next((s["reason"] for s in row["scores"] if s["grader"] == grader), "")
        found.append({"case_id": key[0], "attempt": key[1], "kind": kind, "grader_passed": auto,
                      "human_votes": dict(per), "notes": {w: t for w, t in notes.get(key, {}).items() if t},
                      "grader_reason": why, "output": row["result"].get("output")})
    order = {"false_pass": 0, "false_fail": 1, "reviewers_disagree": 2}
    return sorted(found, key=lambda d: (order[d["kind"]], d["case_id"], d["attempt"]))


def format_disagreements(items: list[dict], total_labelled: int | None = None, limit: int = 20,
                         show_output: bool = False) -> str:
    if not items:
        return "no disagreements between the grader and the human labels"
    blurb = {"false_pass": "grader PASSED, humans said fail", "false_fail": "grader FAILED, humans said pass",
             "reviewers_disagree": "reviewers tied"}
    lines = [f"{len(items)} disagreement(s)" + (f" among {total_labelled} labelled attempts" if total_labelled else "")]
    for d in items[:limit]:
        votes = ", ".join(f"{w}={'yes' if v else 'no'}" for w, v in sorted(d["human_votes"].items()))
        lines.append(f"- {d['case_id']}#{d['attempt']}  [{blurb[d['kind']]}]  humans: {votes}")
        for w, t in sorted(d["notes"].items()):
            lines.append(f"    note ({w}): {t}")
        if d["grader_reason"]:
            lines.append(f"    grader: {d['grader_reason']}")
        if show_output and d["output"] is not None:
            text = d["output"] if isinstance(d["output"], str) else repr(d["output"])
            lines.append(f"    output: {text[:200]}{'...' if len(text) > 200 else ''}")
    if len(items) > limit:
        lines.append(f"... {len(items) - limit} more (raise --limit)")
    return "\n".join(lines)
