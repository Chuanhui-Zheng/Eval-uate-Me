"""Human labelling: turn reviewers' judgements into data the harness can use.

  label export   write a CSV sheet of (case, output) pairs for people to mark pass/fail
  label import   read the filled sheet into <run_dir>/labels.jsonl (append-only, latest wins)

Labels are about an *output*, so each one records a hash of the output it was given for; if a run's output
changes later, the label is treated as stale rather than silently applied to different text.
Sheets are blind by default (automatic verdicts hidden) so reviewers are not anchored by them.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigError
from .formats import check_version, read_json, read_jsonl
from .models import FORMAT_VERSION

LABEL_FILE = "labels.jsonl"
MAX_CELL = 30000  # spreadsheet programs cap a cell at 32,767 characters
TRUE_WORDS = {"1", "true", "t", "yes", "y", "pass", "passed", "ok", "correct", "good"}
FALSE_WORDS = {"0", "false", "f", "no", "n", "fail", "failed", "incorrect", "wrong", "bad"}


def output_hash(output) -> str:
    raw = json.dumps(output, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_verdict(text: str) -> bool | None:
    """Blank -> None (not labelled yet). Raises ValueError for anything unrecognised."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in TRUE_WORDS:
        return True
    if t in FALSE_WORDS:
        return False
    raise ValueError(f"'{text.strip()}' is not a verdict (use yes/no, pass/fail, true/false or leave blank)")


def read_rows(run_dir: Path) -> list[dict]:
    f = Path(run_dir) / "results.jsonl"
    if not f.exists():
        raise ConfigError(f"{run_dir} has no results.jsonl; is it a run directory?")
    return read_jsonl(f)


def _run_privacy_store(run_dir: Path) -> str:
    f = Path(run_dir) / "summary.json"
    return read_json(f).get("privacy_store", "full") if f.exists() else "full"


def _cell(value) -> str:
    """Make a value safe to show in a spreadsheet: bounded length, and no leading =,+,-,@ (formula injection)."""
    text = value if isinstance(value, str) else ("" if value is None else json.dumps(value, ensure_ascii=False))
    if len(text) > MAX_CELL:
        text = text[:MAX_CELL] + " …[truncated]"
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_sheet(run_dir: Path, out: Path, sample: int | None = None, seed: int = 0, balance: bool = False,
                 show_verdicts: bool = False, force: bool = False, unlabelled_only: bool = False) -> dict:
    run_dir, out = Path(run_dir), Path(out)
    if _run_privacy_store(run_dir) == "scores_only":
        raise ConfigError("this run used privacy.store = \"scores_only\", so inputs and outputs were not kept and "
                          "there is nothing to show reviewers. Label from your own source data using a sheet with "
                          "case_id, attempt and human_pass columns, then `label import` it.")
    if out.exists() and not force:
        raise ConfigError(f"{out} already exists; refusing to overwrite a sheet that may hold people's labels "
                          "(use --force to replace it)")
    rows = read_rows(run_dir)
    eligible = [r for r in rows if r["result"].get("error") is None]
    errored = len(rows) - len(eligible)
    already = 0
    if unlabelled_only:
        done = load_labels(run_dir)
        kept = [r for r in eligible if (r["case"]["id"], r.get("attempt", 0)) not in done]
        already, eligible = len(eligible) - len(kept), kept
    if not eligible:
        raise ConfigError("no attempts left to label" + (" (everything is already labelled)" if unlabelled_only else
                                                          " (every attempt errored)"))

    chosen = eligible
    if sample is not None and sample < len(eligible):
        rng = random.Random(seed)
        if balance:
            passed = [r for r in eligible if r["passed"]]
            failed = [r for r in eligible if not r["passed"]]
            rng.shuffle(passed)
            rng.shuffle(failed)
            take_p = min(len(passed), sample // 2)
            take_f = min(len(failed), sample - take_p)
            take_p = min(len(passed), sample - take_f)  # if failures ran short, fill up with passes
            chosen = passed[:take_p] + failed[:take_f]
        else:
            chosen = rng.sample(eligible, sample)
        order = {id(r): i for i, r in enumerate(eligible)}
        chosen.sort(key=lambda r: order[id(r)])  # keep run order for readability

    graders = sorted({s["grader"] for r in chosen for s in r["scores"]})
    header = ["case_id", "attempt", "input", "expected", "output", "human_pass", "notes", "labeler"]
    if show_verdicts:
        header += ["auto_pass"] + [f"auto:{g}" for g in graders]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel reads UTF-8 (e.g. Chinese) correctly
        w = csv.writer(f)
        w.writerow(header)
        for r in chosen:
            c, res = r["case"], r["result"]
            line = [c["id"], r.get("attempt", 0), _cell(c.get("input")), _cell(c.get("expected")),
                    _cell(res.get("output")), "", "", ""]
            if show_verdicts:
                by = {s["grader"]: s["passed"] for s in r["scores"]}
                line += ["yes" if r["passed"] else "no"] + [("" if g not in by else "yes" if by[g] else "no") for g in graders]
            w.writerow(line)
    return {"rows": len(chosen), "eligible": len(eligible), "errored_skipped": errored, "path": str(out),
            "blind": not show_verdicts, "already_labelled_skipped": already}


def load_labels(run_dir: Path) -> dict[tuple[str, int], dict[str, dict]]:
    """(case id, attempt) -> {labeler -> label}. For a repeated (case, attempt, labeler) the latest line wins."""
    f = Path(run_dir) / LABEL_FILE
    out: dict[tuple[str, int], dict[str, dict]] = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = check_version(json.loads(line), f)
                out.setdefault((d["case_id"], d["attempt"]), {})[d["labeler"]] = d
    return out


def import_sheet(run_dir: Path, sheet: Path, labeler: str | None = None) -> dict:
    run_dir, sheet = Path(run_dir), Path(sheet)
    if not sheet.is_file():
        raise ConfigError(f"sheet not found: {sheet}")
    known = {(r["case"]["id"], r.get("attempt", 0)): r for r in read_rows(run_dir) if r["result"].get("error") is None}
    with sheet.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = [(c or "").strip().lower() for c in (reader.fieldnames or [])]
        missing = [c for c in ("case_id", "human_pass") if c not in cols]
        if missing:
            raise ConfigError(f"sheet is missing column(s): {', '.join(missing)} (found: {', '.join(cols) or 'none'})")
        raw_rows = [{(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader]

    problems: list[str] = []
    records: list[dict[str, Any]] = []
    blank = 0
    seen: set[tuple[str, int, str]] = set()
    existing = load_labels(run_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for n, row in enumerate(raw_rows, start=2):  # line 1 is the header
        try:
            verdict = parse_verdict(row["human_pass"])
        except ValueError as e:
            problems.append(f"line {n}: {e}")
            continue
        if verdict is None:
            blank += 1
            continue
        cid = row["case_id"].strip()
        try:
            attempt = int(row.get("attempt", "").strip() or 0)
        except ValueError:
            problems.append(f"line {n}: attempt '{row.get('attempt')}' is not a number")
            continue
        who = (labeler or row.get("labeler", "").strip() or "default")
        if (cid, attempt) not in known:
            problems.append(f"line {n}: no result for case '{cid}' attempt {attempt} in this run "
                            "(spreadsheet programs can reformat ids such as 001 or 1E5; keep case_id as text)")
            continue
        if (cid, attempt, who) in seen:
            problems.append(f"line {n}: '{cid}' attempt {attempt} is labelled twice by '{who}'")
            continue
        seen.add((cid, attempt, who))
        records.append({"format_version": FORMAT_VERSION, "case_id": cid, "attempt": attempt, "human_pass": verdict, "notes": row.get("notes", "").strip(),
                        "labeler": who, "output_sha256": output_hash(known[(cid, attempt)]["result"].get("output")),
                        "labeled_at": now})
    if problems:
        shown = problems[:20] + ([f"... and {len(problems) - 20} more"] if len(problems) > 20 else [])
        raise ConfigError(["nothing was imported:"] + shown)

    updated = sum(1 for r in records if r["labeler"] in existing.get((r["case_id"], r["attempt"]), {}))
    path = run_dir / LABEL_FILE
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(old + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written label file
    return {"imported": len(records), "updated": updated, "blank_skipped": blank,
            "labelers": sorted({r["labeler"] for r in records})}


def carry_labels(from_run: Path, to_run: Path) -> dict:
    """Copy labels onto another run wherever the output is *identical* (same case, same output hash), so
    reviewers do not label the same text twice. A label never overrides one the target run already has from the
    same reviewer, and nothing is copied when the output changed."""
    from_run, to_run = Path(from_run), Path(to_run)
    if from_run.resolve() == to_run.resolve():
        raise ConfigError("the source and target runs are the same directory")
    for d in (from_run, to_run):
        if _run_privacy_store(d) == "scores_only":
            raise ConfigError(f"{d} was made with privacy.store = \"scores_only\", which keeps no outputs, so "
                              "there is no way to tell whether an output is identical; labels cannot be carried")
    source = load_labels(from_run)
    if not source:
        raise ConfigError(f"{from_run} has no labels (labels.jsonl); import some first")
    attempts: dict[str, list[tuple[int, str]]] = {}
    for r in read_rows(to_run):
        if r["result"].get("error") is None:
            attempts.setdefault(r["case"]["id"], []).append((r.get("attempt", 0), output_hash(r["result"].get("output"))))
    existing = load_labels(to_run)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new, no_match, already = [], 0, 0
    for (cid, _), per_labeler in source.items():
        for who, lab in per_labeler.items():
            targets = [a for a, h in attempts.get(cid, []) if h == lab["output_sha256"]]
            if not targets:
                no_match += 1
                continue
            for a in targets:
                if who in existing.get((cid, a), {}):
                    already += 1
                    continue
                new.append({**lab, "attempt": a, "carried_from": from_run.name, "carried_at": now})
    if new:
        path = to_run / LABEL_FILE
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text(old + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new), encoding="utf-8")
        os.replace(tmp, path)
    return {"carried": len(new), "no_match": no_match, "already_labelled": already,
            "labelers": sorted({r["labeler"] for r in new})}
