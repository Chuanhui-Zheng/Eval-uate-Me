"""Versioned on-disk formats.

Every file eval_uate_me writes for a run (results.jsonl rows, summary.json, manifest.json, labels.jsonl) carries
`"format_version": N`. Readers accept older files (no field counts as version 0) and refuse files written by a NEWER
format, with a message that says to upgrade, instead of misreading them. A change that adds keys keeps the number; a change
that removes, renames or re-types a key bumps it, and the release notes then say how to migrate.

Datasets (`cases.jsonl`) may carry an optional per-row `schema_version`, checked the same way.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import CASE_SCHEMA_VERSION, ConfigError  # noqa: F401  (re-exported)
from .models import FORMAT_VERSION

def check_version(data: dict[str, Any], where: Any, key: str = "format_version", supported: int = FORMAT_VERSION) -> dict[str, Any]:
    v = data.get(key, 0)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ConfigError(f"{where}: {key} must be a non-negative integer, got {v!r}")
    if v > supported:
        raise ConfigError(f"{where} was written by a newer eval_uate_me ({key} {v}; this version reads up to {supported}): "
                          "upgrade eval_uate_me to read it")
    return data


def read_json(path: Path) -> dict[str, Any]:
    return check_version(json.loads(Path(path).read_text(encoding="utf-8")), path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            rows.append(check_version(json.loads(line), f"{path} line {n}"))
    return rows
