"""Config loading (TOML) and dataset loading (JSONL)."""
from __future__ import annotations

import difflib
import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Case


@dataclass
class Config:
    name: str
    dataset: Path
    target: dict[str, Any]
    graders: list[dict[str, Any]]
    plugins: list[str] = field(default_factory=list)
    concurrency: int = 4
    repeats: int = 1
    seed: int | None = None
    retries: int = 0
    retry_delay_s: float = 1.0
    max_per_second: float | None = None
    cache: bool = False
    judge_cache: bool = False
    isolation: str = "none"
    timeout_s: float | None = None
    cpu_limit_s: float | None = None
    memory_limit_mb: int | None = None
    env_passthrough: list[str] = field(default_factory=list)
    docker_image: str = "evalharness:latest"
    docker_mounts: list[str] = field(default_factory=list)
    docker_network: str = "none"
    max_cost_usd: float | None = None
    dataset_meta: Path | None = None
    mutants: list[dict[str, Any]] = field(default_factory=list)
    selftest_oracle: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    target_display: dict[str, Any] | None = None   # as written (with ${CONFIG_DIR}); what manifests record
    graders_display: list[dict[str, Any]] | None = None
    split_dev_fraction: float | None = None
    split_salt: str = ""
    privacy_store: str = "full"
    local_only: bool = False
    config_sha256: str = ""
    output_dir: Path = Path("runs")


MUTATION_OPERATORS = (  # output-level mutation operators (see mutation.py)
    "drop_key", "null_value", "empty_value", "truncate_text", "replace_text", "swap_value", "perturb_number", "flip_bool",
    "drop_item", "duplicate_item", "reverse_list", "empty_output")
MUTANT_KEYS = ("name", "target", "operator", "path", "rate", "rates", "seed", "pattern", "replacement", "delta", "factor", "which")
CASE_SCHEMA_VERSION = 1  # of cases.jsonl rows (optional "schema_version"); see formats.py


class ConfigError(ValueError):
    """A problem with the user's config or dataset, worded so a non-programmer can fix it."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


class PluginError(ConfigError):
    """A plugin cannot be used: incompatible API version, import failure, broken entry point."""


TOP_KEYS = {"name": str, "dataset": str, "plugins": list, "target": dict, "graders": list, "run": dict, "privacy": dict, "dataset_meta": str, "split": dict, "mutants": list, "selftest": dict, "gate": dict}
# key -> (accepted types, check, requirement text)
RUN_KEYS: dict[str, tuple[tuple[type, ...], Any, str]] = {
    "concurrency": ((int,), lambda v: v >= 1, "an integer >= 1"),
    "repeats": ((int,), lambda v: v >= 1, "an integer >= 1"),
    "seed": ((int,), lambda v: True, "an integer"),
    "retries": ((int,), lambda v: v >= 0, "an integer >= 0"),
    "retry_delay_s": ((int, float), lambda v: v >= 0, "a number >= 0"),
    "max_per_second": ((int, float), lambda v: v > 0, "a number > 0"),
    "cache": ((bool,), lambda v: True, "true or false"),
    "judge_cache": ((bool,), lambda v: True, "true or false"),
    "max_cost_usd": ((int, float), lambda v: v > 0, "a number > 0"),
    "output_dir": ((str,), lambda v: True, "a folder path (text)"),
    "isolation": ((str,), lambda v: v in ("none", "process", "docker"), "\"none\", \"process\" or \"docker\""),
    "docker_image": ((str,), lambda v: bool(v), "a Docker image name"),
    "docker_mounts": ((list,), lambda v: all(isinstance(x, str) for x in v), "a list of folders to mount read-only"),
    "docker_network": ((str,), lambda v: v in ("none", "bridge"), "\"none\" (default) or \"bridge\""),
    "timeout_s": ((int, float), lambda v: v > 0, "a number of seconds > 0"),
    "cpu_limit_s": ((int, float), lambda v: v > 0, "a number of CPU seconds > 0"),
    "memory_limit_mb": ((int,), lambda v: v > 0, "an integer number of MB > 0"),
    "env_passthrough": ((list,), lambda v: all(isinstance(x, str) for x in v), "a list of environment variable names"),
}


def suggest(word: str, options) -> str:
    m = difflib.get_close_matches(str(word), [str(o) for o in options], n=1)
    return f" Did you mean '{m[0]}'?" if m else ""


def _check_keys(table: dict, allowed, where: str, problems: list[str]) -> None:
    for k in table:
        if k not in allowed:
            problems.append(f"unknown key '{k}' in {where}.{suggest(k, allowed)} Allowed: {', '.join(sorted(allowed))}")


def validate_raw(raw: dict, base: Path) -> list[str]:
    problems: list[str] = []
    _check_keys(raw, TOP_KEYS, "the top level", problems)
    for key in ("dataset", "target", "graders"):
        if key not in raw:
            problems.append(f"missing required key '{key}'")
    for k, t in TOP_KEYS.items():
        if k in raw and not isinstance(raw[k], t):
            want = {str: "text", list: "a list", dict: "a table"}[t]
            problems.append(f"'{k}' must be {want}, got {type(raw[k]).__name__}")
    if isinstance(raw.get("dataset"), str) and not (base / raw["dataset"]).is_file():
        problems.append(f"dataset file not found: {base / raw['dataset']}")
    if isinstance(raw.get("dataset_meta"), str) and not (base / raw["dataset_meta"]).is_file():
        problems.append(f"dataset_meta file not found: {base / raw['dataset_meta']}")
    if isinstance(raw.get("target"), dict) and not isinstance(raw["target"].get("type"), str):
        problems.append("[target] needs a 'type' (e.g. type = \"echo\")")
    if isinstance(raw.get("graders"), list):
        if not raw["graders"]:
            problems.append("'graders' is empty: add at least one [[graders]] table")
        for n, g in enumerate(raw["graders"], 1):
            if not isinstance(g, dict) or not isinstance(g.get("type"), str):
                problems.append(f"[[graders]] #{n} needs a 'type'")
    if isinstance(raw.get("plugins"), list) and not all(isinstance(x, str) for x in raw["plugins"]):
        problems.append("'plugins' must be a list of module names")
    run = raw.get("run")
    if isinstance(run, dict):
        _check_keys(run, RUN_KEYS, "[run]", problems)
        for k, v in run.items():
            if k in RUN_KEYS:
                types, ok, need = RUN_KEYS[k]
                if isinstance(v, bool) and bool not in types or not isinstance(v, types) or not ok(v):
                    problems.append(f"[run] {k} must be {need}, got {v!r}")
    if isinstance(run, dict) and run.get("isolation", "none") == "none" and (run.get("cpu_limit_s") or run.get("memory_limit_mb")):
        problems.append("[run] cpu_limit_s and memory_limit_mb need isolation = \"process\" or \"docker\" (a thread cannot be limited)")
    if isinstance(run, dict) and run.get("isolation") != "docker" and any(k in run for k in ("docker_image", "docker_mounts", "docker_network")):
        problems.append("[run] docker_image, docker_mounts and docker_network only apply with isolation = \"docker\"")
    sp = raw.get("split")
    if isinstance(sp, dict):
        _check_keys(sp, ("dev_fraction", "salt"), "[split]", problems)
        frac = sp.get("dev_fraction")
        if frac is not None and (isinstance(frac, bool) or not isinstance(frac, (int, float)) or not 0 < frac < 1):
            problems.append(f"[split] dev_fraction must be a number between 0 and 1 (exclusive), got {frac!r}")
        if not isinstance(sp.get("salt", ""), str):
            problems.append("[split] salt must be text")
    if isinstance(raw.get("mutants"), list):
        names = []
        for n, m in enumerate(raw["mutants"], 1):
            where = f"[[mutants]] #{n}"
            if not isinstance(m, dict) or not isinstance(m.get("name"), str):
                problems.append(f"{where} needs a 'name' and either a [mutants.target] table (a different target) or an "
                                "'operator' (damage the real target's output)")
                continue
            where = f"[[mutants]] '{m['name']}'"
            _check_keys(m, MUTANT_KEYS, where, problems)
            has_target, has_op = isinstance(m.get("target"), dict), "operator" in m
            if has_target == has_op:
                problems.append(f"{where} needs 'name' and exactly one of a [mutants.target] table (a different target) or an "
                                "'operator' (damage the real target's output)")
            if has_target and not isinstance(m["target"].get("type"), str):
                problems.append(f"{where}: [mutants.target] needs a 'type'")
            if has_op:
                if m["operator"] not in MUTATION_OPERATORS:
                    problems.append(f"{where}: unknown operator {m['operator']!r}.{suggest(m['operator'], MUTATION_OPERATORS)} "
                                    f"Operators: {', '.join(MUTATION_OPERATORS)}")
                if "path" in m and not isinstance(m["path"], str):
                    problems.append(f"{where}: path must be text, e.g. \"findings[*].classification\"")
                for key in ("rate", "rates"):
                    vals = m.get(key)
                    if vals is None:
                        continue
                    for v in (vals if isinstance(vals, list) else [vals]):
                        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
                            problems.append(f"{where}: {key} must be number(s) in (0, 1], got {v!r}")
            elif any(k in m for k in ("path", "rate", "rates", "pattern", "replacement", "delta", "factor", "which", "seed")):
                problems.append(f"{where}: path, rate and the other operator options only apply with 'operator'")
            if m["name"] in names:
                problems.append(f"[[mutants]] name '{m['name']}' is used twice")
            names.append(m["name"])
    gt = raw.get("gate")
    if isinstance(gt, dict):
        tables = ("min", "max", "max_drop", "max_increase_pct", "warn_increase_pct")
        flags = ("significant_only", "fail_on_significant_drop", "allow_dataset_change")
        _check_keys(gt, ("baseline", "alpha") + flags + tables, "[gate]", problems)
        if "baseline" in gt and not isinstance(gt["baseline"], str):
            problems.append("[gate] baseline must be a file path (text)")
        a = gt.get("alpha", 0.05)
        if isinstance(a, bool) or not isinstance(a, (int, float)) or not 0 < a < 1:
            problems.append(f"[gate] alpha must be a number between 0 and 1, got {a!r}")
        for k in flags:
            if k in gt and not isinstance(gt[k], bool):
                problems.append(f"[gate] {k} must be true or false")
        for k in tables:
            if k in gt:
                t = gt[k]
                if not isinstance(t, dict) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in t.values()):
                    problems.append(f"[gate.{k}] must map metric names to numbers >= 0")
    st = raw.get("selftest")
    if isinstance(st, dict):
        _check_keys(st, ("oracle",), "[selftest]", problems)
        if "oracle" in st and not (isinstance(st["oracle"], dict) and isinstance(st["oracle"].get("type"), str)):
            problems.append("[selftest.oracle] needs a 'type': the target that produces a perfect answer")
    priv = raw.get("privacy")
    if isinstance(priv, dict):
        _check_keys(priv, ("store", "local_only"), "[privacy]", problems)
        if priv.get("store", "full") not in ("full", "scores_only"):
            problems.append(f"[privacy] store must be \"full\" or \"scores_only\", got {priv['store']!r}")
        if not isinstance(priv.get("local_only", False), bool):
            problems.append("[privacy] local_only must be true or false")
        if priv.get("store") == "scores_only" and isinstance(run, dict) and (run.get("cache") is True or run.get("judge_cache") is True):
            problems.append("run.cache and run.judge_cache store raw outputs or judge replies (which can quote them) on disk, so "
                            "they cannot be combined with privacy.store = \"scores_only\"")
    return problems


CONFIG_DIR_TOKEN = "${CONFIG_DIR}"


def expand_vars(obj: Any, base: Path) -> Any:
    """Replace ${CONFIG_DIR} with the config file's folder in every string, so plugin options such as a data file path
    work whatever directory the command is run from."""
    if isinstance(obj, str):
        return obj.replace(CONFIG_DIR_TOKEN, str(base))
    if isinstance(obj, dict):
        return {k: expand_vars(v, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_vars(v, base) for v in obj]
    return obj


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} is not valid TOML: {e}") from e
    base = path.parent
    problems = validate_raw(raw, base)
    if problems:
        raise ConfigError([f"{path.name}: {p}" for p in problems])
    run = raw.get("run", {})
    return Config(
        name=raw.get("name", path.stem),
        dataset=(base / raw["dataset"]),
        target=expand_vars(raw["target"], base),
        graders=expand_vars(raw["graders"], base),
        target_display=raw["target"],
        graders_display=raw["graders"],
        plugins=raw.get("plugins", []),
        concurrency=int(run.get("concurrency", 4)),
        repeats=int(run.get("repeats", 1)),
        seed=run.get("seed"),
        retries=int(run.get("retries", 0)),
        retry_delay_s=float(run.get("retry_delay_s", 1.0)),
        max_per_second=run.get("max_per_second"),
        cache=bool(run.get("cache", False)),
        judge_cache=bool(run.get("judge_cache", False)),
        isolation=run.get("isolation", "none"),
        timeout_s=run.get("timeout_s"),
        cpu_limit_s=run.get("cpu_limit_s"),
        memory_limit_mb=run.get("memory_limit_mb"),
        env_passthrough=list(run.get("env_passthrough", [])),
        docker_image=run.get("docker_image", "evalharness:latest"),
        docker_mounts=expand_vars(list(run.get("docker_mounts", [])), base),
        docker_network=run.get("docker_network", "none"),
        max_cost_usd=run.get("max_cost_usd"),
        dataset_meta=(base / raw["dataset_meta"]) if raw.get("dataset_meta") else None,
        mutants=expand_vars(raw.get("mutants", []), base),
        selftest_oracle=expand_vars(raw.get("selftest", {}).get("oracle"), base),
        gate=raw.get("gate"),
        split_dev_fraction=raw.get("split", {}).get("dev_fraction"),
        split_salt=raw.get("split", {}).get("salt", ""),
        privacy_store=raw.get("privacy", {}).get("store", "full"),
        local_only=bool(raw.get("privacy", {}).get("local_only", False)),
        config_sha256=hashlib.sha256(text.encode()).hexdigest(),
        output_dir=(base / run.get("output_dir", "runs")),
    )


def load_cases(path: Path) -> list[Case]:
    if not Path(path).is_file():
        raise ConfigError(f"dataset file not found: {path}")
    cases, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path}:{n}: invalid JSON: {e}") from e
        sv = d.get("schema_version", 1)
        if isinstance(sv, bool) or not isinstance(sv, int) or sv < 1:
            raise ConfigError(f"{path}:{n}: schema_version must be a positive integer, got {sv!r}")
        if sv > CASE_SCHEMA_VERSION:
            raise ConfigError(f"{path}:{n}: case schema_version {sv} is newer than this evalharness reads ({CASE_SCHEMA_VERSION}): "
                              "upgrade evalharness")
        cid = str(d.get("id", f"case-{n}"))
        if cid in seen:
            raise ConfigError(f"{path}:{n}: duplicate case id '{cid}'")
        seen.add(cid)
        cases.append(Case(id=cid, input=d.get("input"), expected=d.get("expected"), metadata=d.get("metadata", {})))
    if not cases:
        raise ConfigError(f"{path}: no cases found")
    return cases
