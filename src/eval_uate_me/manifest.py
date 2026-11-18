"""Run manifest: everything needed to know what produced a result and to reproduce it."""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .graders import JUDGE_PROMPT_VERSION
from .models import FORMAT_VERSION
from .pairwise import PAIR_PROMPT_VERSION
from .dataset_meta import resolve_meta

_SECRET_HINTS = ("key", "token", "secret", "password")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def redact(obj: Any) -> Any:
    """Mask values of option names that look like secrets (names ending in _env are env var *names*, kept)."""
    if isinstance(obj, dict):
        return {k: ("***" if any(h in k.lower() for h in _SECRET_HINTS) and not k.lower().endswith("_env")
                    and isinstance(v, str) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def git_info(cwd: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": bool(git("status", "--porcelain"))}


def build_manifest(cfg: Config, n_cases: int, started: datetime, finished: datetime | None,
                   status: str = "complete") -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "judge_prompt_versions": {"llm_judge": JUDGE_PROMPT_VERSION, "pairwise": PAIR_PROMPT_VERSION},
        "harness_version": __version__,
        "name": cfg.name,
        "started_at": started.astimezone(timezone.utc).isoformat(),
        "status": status,  # running | complete | interrupted
        "finished_at": finished.astimezone(timezone.utc).isoformat() if finished else None,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "config_sha256": cfg.config_sha256,
        "dataset_path": str(cfg.dataset),
        "dataset_sha256": sha256_file(cfg.dataset),
        "dataset_meta": (m.to_dict() if (m := resolve_meta(cfg.dataset, cfg.dataset_meta)) else None),
        "n_cases": n_cases,
        "repeats": cfg.repeats,
        "seed": cfg.seed,
        "target": redact(cfg.target_display or cfg.target),
        "graders": redact(cfg.graders_display or cfg.graders),
        "plugins": cfg.plugins,
        "git": git_info(cfg.dataset.parent),
    }
