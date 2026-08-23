"""Dataset lint: cheap checks for problems that make an eval's score meaningless.

Each finding is a `warn` (likely to distort results) or `info` (worth knowing)."""
from __future__ import annotations

import json
import math
import subprocess
from datetime import date
from pathlib import Path
from collections import Counter
from dataclasses import asdict, dataclass, field

from .dataset_meta import DatasetMeta
from .models import Case
from .splits import SPLITS, case_split


@dataclass
class Finding:
    level: str  # warn | info
    code: str
    message: str
    case_ids: list[str] = field(default_factory=list)


def _key(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def _answer_strings(expected) -> list[str]:
    items = expected if isinstance(expected, list) else [expected]
    return [x for x in items if isinstance(x, str) and len(x.strip()) >= 3]


RESTRICTIVE_LICENSE_WORDS = ("unknown", "proprietary", "all rights reserved", "restricted", "controlled", "dbgap")


def _git(args: list[str], cwd: Path) -> int | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=10).returncode
    except (OSError, subprocess.TimeoutExpired):
        return None


def meta_findings(meta: DatasetMeta | None, dataset_path: Path | None = None, privacy_store: str | None = None,
                  today: date | None = None) -> list[Finding]:
    out: list[Finding] = []
    if meta is None:
        return [Finding("warn", "no_metadata", "no dataset metadata file (<name>.meta.toml): source, version, "
                        "retrieval date and licence are unrecorded")]
    missing = [f for f in ("name", "version", "source", "retrieved", "license") if not getattr(meta, f)]
    if missing:
        out.append(Finding("warn", "incomplete_metadata", f"dataset metadata is missing: {', '.join(missing)}"))
    if meta.contains_personal_data is None:
        out.append(Finding("warn", "personal_data_undeclared",
                           "contains_personal_data is not set: say explicitly whether the cases include personal data"))
    elif meta.contains_personal_data and privacy_store == "full":
        out.append(Finding("warn", "personal_data_without_privacy_mode",
                           "the dataset contains personal data but privacy.store is 'full', so results and reports "
                           "will store it; use store = 'scores_only'"))
    lic = (meta.license or "").lower()
    if lic and any(w in lic for w in RESTRICTIVE_LICENSE_WORDS):
        out.append(Finding("warn", "restrictive_license", f"licence '{meta.license}' suggests limits on sharing: "
                           "do not publish or redistribute this file"))
    if meta.redistributable is False and dataset_path is not None:
        cwd = Path(dataset_path).resolve().parent
        if _git(["ls-files", "--error-unmatch", Path(dataset_path).name], cwd) == 0:
            out.append(Finding("warn", "restricted_data_tracked",
                               "marked redistributable = false but this file is tracked by git: remove it from the "
                               "repository (and its history) before publishing"))
        elif _git(["check-ignore", "-q", Path(dataset_path).name], cwd) == 1:
            out.append(Finding("warn", "restricted_data_not_ignored",
                               "marked redistributable = false but not git-ignored: `git add .` would include it; "
                               "add it to .gitignore"))
    if meta.retrieved:
        age = ((today or date.today()) - date.fromisoformat(meta.retrieved)).days
        if age > 365:
            out.append(Finding("info", "old_snapshot", f"snapshot is {age // 30} months old; check whether the source "
                               "has been updated (public vulnerability databases change records over time)"))
    return out


def lint(cases: list[Case], min_cases: int = 30, majority_warn: float = 0.8, *, check_meta: bool = False,
         meta: DatasetMeta | None = None, dataset_path: Path | None = None, privacy_store: str | None = None,
         today: date | None = None, split_dev_fraction: float | None = None,
         split_salt: str = "") -> list[Finding]:
    out: list[Finding] = []
    n = len(cases)

    by_input: dict[str, list[str]] = {}
    for c in cases:
        by_input.setdefault(_key(c.input), []).append(c.id)
    dups = sorted(i for ids in by_input.values() if len(ids) > 1 for i in ids)
    if dups:
        out.append(Finding("warn", "duplicate_input",
                           "cases with identical input are double-counted and can inflate or deflate the score", dups))

    missing = [c.id for c in cases if c.expected is None]
    if missing:
        out.append(Finding("warn", "missing_expected",
                           "no `expected` value: reference-based graders and baselines cannot use these cases", missing))
    empty = [c.id for c in cases if c.expected in ("", [], {})]
    if empty:
        out.append(Finding("warn", "empty_expected", "`expected` is empty, so almost any output matches it", empty))

    leaked = []
    for c in cases:
        text = c.input if isinstance(c.input, str) else _key(c.input)
        if any(a.lower() in text.lower() for a in _answer_strings(c.expected)):
            leaked.append(c.id)
    if leaked:
        out.append(Finding("warn", "answer_in_input",
                           "the reference answer appears verbatim in the input: an agent can pass by copying", leaked))

    labelled = [c for c in cases if c.expected is not None]
    if len(labelled) >= 5:
        top, count = Counter(_key(c.expected) for c in labelled).most_common(1)[0]
        if count / len(labelled) >= majority_warn:
            out.append(Finding("warn", "constant_answer",
                               f"{count / len(labelled):.0%} of references are identical ({top[:40]}): "
                               "a constant guess scores about that much"))

    if n < min_cases:
        half = 1.96 * math.sqrt(0.25 / n) if n else 1.0
        out.append(Finding("warn", "small_dataset",
                           f"{n} cases (< {min_cases}): a pass rate near 50% has a 95% CI of about ±{half:.0%}"))

    tagged = [c for c in cases if c.metadata.get("tags") or c.metadata.get("category")]
    if not tagged:
        out.append(Finding("info", "no_tags", "no tags/category: results cannot be broken down by slice"))
    elif len(tagged) < n:
        out.append(Finding("warn", "partially_tagged", "some cases have no tag, so slice breakdowns are incomplete",
                           [c.id for c in cases if c not in tagged]))
    out.extend(_split_findings(cases, split_dev_fraction, split_salt))
    if check_meta:
        out.extend(meta_findings(meta, dataset_path, privacy_store, today))
    return out


def _split_findings(cases: list[Case], dev_fraction: float | None, salt: str, min_split: int = 10) -> list[Finding]:
    """Only runs when splits are in use (a [split] config or any metadata.split)."""
    if dev_fraction is None and not any("split" in c.metadata for c in cases):
        return []
    assigned = {c.id: case_split(c, dev_fraction, salt) for c in cases}
    out: list[Finding] = []
    none = [i for i, s in assigned.items() if s is None]
    if none:
        out.append(Finding("warn", "split_unassigned", "some cases have no split (no [split] config and no "
                           "metadata.split): they are excluded from dev/heldout runs", none))
    for name in SPLITS:
        k = sum(1 for s in assigned.values() if s == name)
        if k < min_split:
            half = 1.96 * math.sqrt(0.25 / k) if k else 1.0
            out.append(Finding("warn", "split_too_small", f"the '{name}' split has {k} case(s) (< {min_split}): a pass "
                               f"rate near 50% there has a 95% CI of about ±{half:.0%}"))
    by_input: dict[str, set[str]] = {}
    for c in cases:
        split_of = assigned[c.id]
        if split_of:
            by_input.setdefault(_key(c.input), set()).add(split_of)
    leaked = [c.id for c in cases if assigned[c.id] and len(by_input[_key(c.input)]) > 1]
    if leaked:
        out.append(Finding("warn", "split_leakage", "the same input is in both dev and heldout: tuning on dev "
                           "leaks into the held-out score", leaked))
    return out


def format_findings(findings: list[Finding], n_cases: int) -> str:
    lines = [f"lint: {n_cases} cases, {sum(f.level == 'warn' for f in findings)} warnings, "
             f"{sum(f.level == 'info' for f in findings)} notes"]
    for f in findings:
        ids = f"  [{', '.join(f.case_ids[:8])}{' ...' if len(f.case_ids) > 8 else ''}]" if f.case_ids else ""
        lines.append(f"  {f.level.upper():<4} {f.code}: {f.message}{ids}")
    if not findings:
        lines.append("  no issues found")
    return "\n".join(lines)


def to_dicts(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]
