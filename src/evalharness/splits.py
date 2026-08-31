"""Development / held-out splits.

Tune on `dev`; look at `heldout` rarely, ideally once, as the final number. If you keep adjusting prompts,
graders or references while watching the same cases, the score stops measuring anything but your tuning.

A case's split is, in order of precedence:
  1. `metadata.split` = "dev" | "heldout" in the dataset (an explicit decision), else
  2. a hash of its id (and `salt`): stable and reproducible, and adding cases never moves existing ones.
Configure the hash split with:

    [split]
    dev_fraction = 0.3        # the rest is held out
    salt = "v1"               # change it to draw a different split
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import ConfigError
from .models import Case

SPLITS = ("dev", "heldout")


def bucket(case_id: str, salt: str = "") -> float:
    """Deterministic position of a case in [0, 1)."""
    digest = hashlib.sha256(f"{salt}:{case_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def case_split(case: Case, dev_fraction: float | None, salt: str = "") -> str | None:
    explicit = case.metadata.get("split")
    if explicit is not None:
        if explicit not in SPLITS:
            raise ConfigError(f"case '{case.id}': metadata.split must be one of {SPLITS}, got {explicit!r}")
        return explicit
    if dev_fraction is None:
        return None
    return "dev" if bucket(case.id, salt) < dev_fraction else "heldout"


def split_cases(cases: list[Case], dev_fraction: float | None, salt: str = "") -> dict[str, list[Case]]:
    """Assign every case. Raises if some case has no split (no [split] config and no metadata.split)."""
    out: dict[str, list[Case]] = {s: [] for s in SPLITS}
    unassigned = []
    for c in cases:
        s = case_split(c, dev_fraction, salt)
        if s is None:
            unassigned.append(c)
        else:
            out[s].append(c)
    if unassigned:
        shown = ", ".join(c.id for c in unassigned[:5]) + (" ..." if len(unassigned) > 5 else "")
        raise ConfigError(f"{len(unassigned)} case(s) have no split ({shown}): add a [split] table with dev_fraction "
                          "to the config, or set metadata.split on every case")
    return out


def select(cases: list[Case], which: str, dev_fraction: float | None, salt: str = "") -> list[Case]:
    if which == "all":
        return cases
    chosen = split_cases(cases, dev_fraction, salt)[which]
    if not chosen:
        raise ConfigError(f"the '{which}' split has no cases (dev_fraction={dev_fraction}, {len(cases)} cases)")
    return chosen


def export(cases: list[Case], dev_fraction: float | None, salt: str, out_dir: Path, only: str | None = None,
           force: bool = False) -> dict[str, Path]:
    """Write dev.jsonl / heldout.jsonl so the dev set can be shared while the held-out set stays private."""
    parts = split_cases(cases, dev_fraction, salt)
    out_dir = Path(out_dir)
    targets = {s: out_dir / f"{s}.jsonl" for s in SPLITS if only in (None, s)}
    exists = [str(p) for p in targets.values() if p.exists()]
    if exists and not force:
        raise ConfigError([f"refusing to overwrite {p} (use --force)" for p in exists])
    out_dir.mkdir(parents=True, exist_ok=True)
    for s, path in targets.items():
        with path.open("w", encoding="utf-8") as f:
            for c in parts[s]:
                f.write(json.dumps({"id": c.id, "input": c.input, "expected": c.expected, "metadata": c.metadata},
                                   ensure_ascii=False) + "\n")
    return targets


def record_heldout_look(output_dir: Path, dataset: Path, config_sha256: str, split: str, run_name: str) -> int:
    """Log that held-out cases were evaluated and return which look this is for this dataset version.
    Prints a warning on repeats. An honesty aid, not enforcement: deleting the log or editing the dataset resets it."""
    import sys
    from datetime import datetime
    from .manifest import sha256_file

    log = Path(output_dir) / "heldout_log.jsonl"
    ds = sha256_file(dataset)
    previous = 0
    if log.exists():
        previous = sum(1 for l in log.read_text(encoding="utf-8").splitlines()
                       if l.strip() and json.loads(l).get("dataset_sha256") == ds)
    if previous:
        print(f"warning: the held-out split has already been evaluated {previous} time(s) on this dataset "
              "version; every extra look makes it less independent of your tuning", file=sys.stderr)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().astimezone().isoformat(timespec="seconds"), "dataset_sha256": ds,
                            "split": split, "run": run_name, "config_sha256": config_sha256}) + "\n")
    return previous + 1
