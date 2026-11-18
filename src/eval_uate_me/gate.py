"""Baselines and the CI gate: block a change when quality drops, without being fooled by noise.

    eval_uate_me baseline promote RUN     # remember a good run (commit the file)
    eval_uate_me gate                     # compare the latest run with it; exit 1 on a regression

Rules live in the config:

    [gate]
    baseline = "eval.baseline.json"      # default: <config name>.baseline.json beside the config
    significant_only = true              # a max_drop breach fails only if the drop is statistically significant
    [gate.min]               pass_rate = 0.75              # floors (work without a baseline)
    [gate.max]               error_rate = 0.10             # ceilings
    [gate.max_drop]          pass_rate = 0.05              # allowed drop vs the baseline, in the metric's own units
    [gate.max_increase_pct]  cost_usd = 25                 # allowed rise vs the baseline, in percent
    [gate.warn_increase_pct] latency_p50_s = 50            # warn (never fail)

Metrics: pass_rate, error_rate, pass_rate_answered, latency_p50_s, cost_usd, pass_at_1, pass_all, `tag.<name>` (pass rate of a tag)
and `grader.<name>` (mean score). A metric a rule names but the run or baseline lacks FAILS the gate (a typo must not pass).
A fixed threshold on a small dataset is mostly noise, so with `significant_only` a breach of max_drop on a pass rate only fails
when a paired permutation test over the cases says the drop is real; otherwise it is reported as a warning.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config, ConfigError
from .formats import read_json
from .models import FORMAT_VERSION
from .report import _load
from .stats import paired_permutation_p


@dataclass
class GateOutcome:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def metrics_from_summary(summary: dict[str, Any]) -> dict[str, float]:
    m: dict[str, float] = {"pass_rate": summary["pass_rate"], "error_rate": summary.get("error_rate", 0.0),
                           "pass_rate_answered": summary.get("pass_rate_answered", summary["pass_rate"]),
                           "latency_p50_s": summary.get("latency_p50_s", 0.0), "cost_usd": summary.get("cost_usd_spent", 0.0)}
    for key in ("pass_at_1", "pass_all"):
        if key in summary:
            m[key] = summary[key]
    for tag, d in summary.get("by_tag", {}).items():
        m[f"tag.{tag}"] = d["pass_rate"]
    for g, v in summary.get("mean_score_by_grader", {}).items():
        m[f"grader.{g}"] = v
    return m


def latest_run(runs_dir: Path, name: str) -> Path:
    best = None
    for d in Path(runs_dir).glob("*"):
        sf, mf = d / "summary.json", d / "manifest.json"
        if d.is_dir() and sf.exists() and mf.exists() and read_json(sf).get("name") == name:
            started = read_json(mf).get("started_at", "")
            if best is None or (started, d.name) > best[0]:
                best = ((started, d.name), d)
    if best is None:
        raise ConfigError(f"no finished runs named '{name}' under {runs_dir}: run `eval_uate_me run` first (or pass --run)")
    return best[1]


def baseline_path(cfg: Config, config_file: Path, override: str | None = None) -> Path:
    if override:
        return Path(override)
    name = (cfg.gate or {}).get("baseline")
    return (config_file.parent / name) if name else config_file.with_suffix(".baseline.json")


def promote(run_dir: Path, out: Path) -> dict[str, Any]:
    summary, manifest = read_json(Path(run_dir) / "summary.json"), read_json(Path(run_dir) / "manifest.json")
    if manifest.get("status", "complete") != "complete" or summary.get("incomplete"):
        raise ConfigError(f"{run_dir.name} is {manifest.get('status', 'incomplete')}: only a complete run can be a baseline")
    rates, tags = _load(Path(run_dir))
    base = {"format_version": FORMAT_VERSION, "run_id": Path(run_dir).name, "name": summary["name"],
            "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "harness_version": __version__,
            "split": manifest.get("split", "all"), "dataset_sha256": manifest.get("dataset_sha256", ""),
            "metrics": metrics_from_summary(summary), "case_rates": rates, "case_tags": tags}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
    return base


def load_baseline(path: Path) -> dict[str, Any] | None:
    return read_json(path) if Path(path).is_file() else None


def _significance(metric: str, run_dir: Path, baseline: dict[str, Any], alpha: float) -> tuple[float, int] | None:
    """Paired permutation p-value for a pass-rate metric, or None when it is not a pass rate or there are no shared cases."""
    if metric != "pass_rate" and not metric.startswith("tag."):
        return None
    rates, tags = _load(run_dir)
    base_rates = baseline.get("case_rates", {})
    ids = [k for k in rates if k in base_rates]
    if metric.startswith("tag."):
        want = metric[4:]
        ids = [k for k in ids if want in tags.get(k, [])]
    if not ids:
        return None
    return paired_permutation_p([rates[k] - base_rates[k] for k in ids]), len(ids)


def evaluate_gate(run_dir: Path, baseline: dict[str, Any] | None, gate: dict[str, Any]) -> GateOutcome:
    out = GateOutcome()
    summary, manifest = read_json(Path(run_dir) / "summary.json"), read_json(Path(run_dir) / "manifest.json")
    metrics = metrics_from_summary(summary)
    if manifest.get("status", "complete") != "complete" or summary.get("incomplete"):
        out.failures.append(f"the run did not complete ({manifest.get('status', 'incomplete')}); its numbers are partial")
    alpha = float(gate.get("alpha", 0.05))
    significant_only = bool(gate.get("significant_only", False))

    for name, floor in gate.get("min", {}).items():
        v = metrics.get(name)
        if v is None:
            out.failures.append(f"metric '{name}' is missing from the run (min {floor})")
        elif v < floor:
            out.failures.append(f"{name} {v:.4f} is below the minimum {floor:.4f}")
    for name, ceiling in gate.get("max", {}).items():
        v = metrics.get(name)
        if v is None:
            out.failures.append(f"metric '{name}' is missing from the run (max {ceiling})")
        elif v > ceiling:
            out.failures.append(f"{name} {v:.4f} is above the maximum {ceiling:.4f}")

    needs_baseline = any(gate.get(k) for k in ("max_drop", "max_increase_pct", "warn_increase_pct")) or gate.get("fail_on_significant_drop")
    if not needs_baseline:
        return out
    if baseline is None:
        out.failures.append("no baseline: run `eval_uate_me baseline promote` on a good run and commit the file")
        return out
    if not gate.get("allow_dataset_change", False) and baseline.get("dataset_sha256") != manifest.get("dataset_sha256"):
        out.failures.append("the baseline was made on a different dataset version: re-promote a run on this dataset "
                            "(or set allow_dataset_change = true to compare anyway)")
    if baseline.get("split", "all") != manifest.get("split", "all"):  # never relaxed: dev vs held-out is not comparable
        out.failures.append(f"the baseline is for split '{baseline.get('split', 'all')}' but this run used "
                            f"'{manifest.get('split', 'all')}'")
    base_metrics = baseline.get("metrics", {})

    for name, allowed in gate.get("max_drop", {}).items():
        v, b = metrics.get(name), base_metrics.get(name)
        if v is None or b is None:
            out.failures.append(f"metric '{name}' is missing from the run or the baseline (max_drop {allowed})")
            continue
        drop = b - v
        if drop <= allowed:
            continue
        sig = _significance(name, Path(run_dir), baseline, alpha) if significant_only else None
        if significant_only and sig is not None and sig[0] >= alpha:
            out.warnings.append(f"{name} dropped {drop:.4f} (allowed {allowed:.4f}) but over {sig[1]} cases that is "
                                f"within noise (p = {sig[0]:.3f} >= {alpha}); not failing")
        else:
            out.failures.append(f"{name} dropped {drop:.4f} vs the baseline {b:.4f} (allowed {allowed:.4f})"
                                + (f", p = {sig[0]:.3f}" if sig else ""))
    if gate.get("fail_on_significant_drop"):
        sig = _significance("pass_rate", Path(run_dir), baseline, alpha)
        if sig and sig[0] < alpha and metrics["pass_rate"] < base_metrics.get("pass_rate", metrics["pass_rate"]):
            out.failures.append(f"pass_rate fell significantly vs the baseline (p = {sig[0]:.3f} over {sig[1]} cases)")

    for table, target in (("max_increase_pct", out.failures), ("warn_increase_pct", out.warnings)):
        for name, allowed_pct in gate.get(table, {}).items():
            v, b = metrics.get(name), base_metrics.get(name)
            if v is None or b is None:
                if table == "max_increase_pct":
                    out.failures.append(f"metric '{name}' is missing from the run or the baseline (max_increase_pct {allowed_pct})")
                continue
            if b == 0:
                if v > 0 and table == "max_increase_pct":
                    out.notes.append(f"{name} rose from 0 to {v:.4f}; a percentage is undefined, not failing")
                continue
            pct = (v - b) / b * 100
            if pct > allowed_pct:
                target.append(f"{name} rose {pct:.1f}% vs the baseline (allowed {allowed_pct:.1f}%)")
    return out


def format_for_ci(outcome: GateOutcome) -> list[str]:
    on_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    lines = [f"::error::eval_uate_me gate: {f}" if on_actions else f"FAIL {f}" for f in outcome.failures]
    lines += [f"::warning::eval_uate_me gate: {w}" if on_actions else f"WARN {w}" for w in outcome.warnings]
    lines += [f"note: {n}" for n in outcome.notes]
    return lines
