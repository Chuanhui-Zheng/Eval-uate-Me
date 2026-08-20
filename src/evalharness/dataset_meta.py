"""Dataset provenance: a small file saying where a dataset came from and what it may be used for.

Lives next to the dataset as `<name>.meta.toml` (or set `dataset_meta = "..."` in the config):

    name = "variant-triage"
    version = "1.0"                 # in quotes
    source = "NVD, CISA KEV"
    url = "https://nvd.nist.gov/"
    retrieved = 2026-09-15          # when the snapshot was taken
    license = "public domain (NCBI)"
    contains_personal_data = false
    redistributable = true          # may the file be committed to a public repository?

Without it, months later nobody can say whether a dataset may be shared or how stale it is.
"""
from __future__ import annotations

import hashlib
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .config import ConfigError, suggest

FIELDS: dict[str, type] = {
    "name": str, "version": str, "description": str, "source": str, "url": str, "retrieved": str,
    "license": str, "citation": str, "notes": str, "contains_personal_data": bool, "redistributable": bool,
}


@dataclass
class DatasetMeta:
    name: str | None = None
    version: str | None = None
    description: str | None = None
    source: str | None = None
    url: str | None = None
    retrieved: str | None = None
    license: str | None = None
    citation: str | None = None
    notes: str | None = None
    contains_personal_data: bool | None = None
    redistributable: bool | None = None
    sha256: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != ""}


def find_meta_path(dataset: Path, override: Path | None = None) -> Path | None:
    if override is not None:
        return override
    p = Path(dataset).with_suffix("").with_name(Path(dataset).stem + ".meta.toml")
    return p if p.is_file() else None


def load_meta(path: Path) -> DatasetMeta:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"dataset metadata file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} is not valid TOML: {e}") from e
    problems: list[str] = []
    values: dict = {}
    for k, v in raw.items():
        if k not in FIELDS:
            problems.append(f"unknown key '{k}'.{suggest(k, FIELDS)} Allowed: {', '.join(sorted(FIELDS))}")
            continue
        if k == "retrieved" and isinstance(v, date):  # TOML reads an unquoted 2026-09-15 as a date
            v = v.isoformat()
        want = FIELDS[k]
        if not isinstance(v, want):
            hint = " (put it in quotes)" if want is str and isinstance(v, (int, float)) else ""
            problems.append(f"'{k}' must be {'true or false' if want is bool else 'text'}, got {v!r}{hint}")
            continue
        if k == "retrieved":
            try:
                date.fromisoformat(str(v))
            except ValueError:
                problems.append(f"'retrieved' must be a date like 2026-09-15, got {v!r}")
                continue
        values[k] = v
    if problems:
        raise ConfigError([f"{path.name}: {p}" for p in problems])
    return DatasetMeta(**values, sha256=hashlib.sha256(text.encode()).hexdigest())


def resolve_meta(dataset: Path, override: Path | None = None) -> DatasetMeta | None:
    p = find_meta_path(dataset, override)
    return load_meta(p) if p else None
