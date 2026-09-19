"""Run history: how a system's scores move across runs, and whether the latest run is a real regression.

Reads every run directory under a runs folder (summary.json + manifest.json + results.jsonl). Runs are only compared
within a *series*: the same name, split and dataset version, because a score on a different dataset or split is not a
point on the same line.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

from .config import ConfigError
from .formats import read_json
from .report import _load
from .stats import paired_delta_ci, paired_permutation_p

SPARK = "▁▂▃▄▅▆▇█"


@dataclass
class RunRecord:
    dir: Path
    name: str
    started: datetime
    status: str
    split: str
    dataset_sha: str
    dataset_label: str
    cases: int
    pass_rate: float
    ci: tuple[float, float]
    error_rate: float
    cost: float
    p50: float
    git: str
    config_sha: str
    target: dict = field(default_factory=dict)
    incomplete: int = 0


def scan(runs_dir: Path, name: str | None = None, split: str | None = None) -> list[RunRecord]:
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        raise ConfigError(f"runs folder not found: {runs_dir}")
    out = []
    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        sf, mf = d / "summary.json", d / "manifest.json"
        if not (sf.exists() and mf.exists()):
            continue  # a run that never finished writing, or not a run directory
        s, m = read_json(sf), read_json(mf)
        if (name and s["name"] != name) or (split and m.get("split", "all") != split):
            continue
        dm = m.get("dataset_meta") or {}
        started = datetime.fromisoformat(m["started_at"]) if m.get("started_at") else datetime.fromtimestamp(d.stat().st_mtime)
        out.append(RunRecord(
            dir=d, name=s["name"], started=started, status=m.get("status", "complete"), split=m.get("split", "all"),
            dataset_sha=m.get("dataset_sha256", ""), dataset_label=(f"{dm['name']} v{dm.get('version', '?')}" if dm.get("name") else (m.get("dataset_sha256") or "")[:8]),
            cases=s["cases"], pass_rate=s["pass_rate"], ci=tuple(s["pass_rate_ci95"]), error_rate=s.get("error_rate", 0.0),
            cost=s.get("cost_usd_spent", 0.0), p50=s.get("latency_p50_s", 0.0), git=((m.get("git") or {}).get("commit") or "")[:7],
            config_sha=m.get("config_sha256", ""), target=m.get("target") or {}, incomplete=s.get("incomplete", 0)))
    if not out:
        raise ConfigError(f"no finished runs found under {runs_dir}" + (f" for name={name!r}" if name else ""))
    return sorted(out, key=lambda r: (r.started, r.dir.name))


def group_series(records: list[RunRecord]) -> dict[tuple, list[RunRecord]]:
    series: dict[tuple, list[RunRecord]] = {}
    for r in records:
        series.setdefault((r.name, r.split, r.dataset_sha), []).append(r)
    return series


def sparkline(values: list[float]) -> str:
    return "".join(SPARK[min(len(SPARK) - 1, max(0, int(v * (len(SPARK) - 1) + 0.5)))] for v in values)


def what_changed(a: RunRecord, b: RunRecord) -> list[str]:
    out = []
    if a.git != b.git:
        out.append(f"code {a.git or '?'} -> {b.git or '?'}")
    if a.target != b.target:
        keys = sorted(k for k in set(a.target) | set(b.target) if a.target.get(k) != b.target.get(k))
        out.append("target options: " + ", ".join(keys))
    elif a.config_sha != b.config_sha:
        out.append("config edited")
    return out


def regression(prev: RunRecord, last: RunRecord, alpha: float = 0.05) -> dict:
    ra, _ = _load(prev.dir)
    rb, _ = _load(last.dir)
    shared = sorted(ra.keys() & rb.keys())
    if not shared:
        return {"delta": 0.0, "p": 1.0, "regressed": False, "n": 0}
    delta, lo, hi = paired_delta_ci([ra[k] for k in shared], [rb[k] for k in shared])
    p = paired_permutation_p([rb[k] - ra[k] for k in shared])
    return {"delta": delta, "ci": (lo, hi), "p": p, "n": len(shared), "regressed": delta < 0 and p < alpha}


def analyse(records: list[RunRecord]) -> list[dict]:
    out = []
    for (name, split, _), runs in group_series(records).items():
        item = {"name": name, "split": split, "runs": runs, "dataset": runs[0].dataset_label, "regression": None, "changes": []}
        if len(runs) >= 2:
            item["regression"] = regression(runs[-2], runs[-1])
            item["changes"] = what_changed(runs[-2], runs[-1])
        out.append(item)
    return sorted(out, key=lambda s: s["runs"][-1].started, reverse=True)


def format_history(series: list[dict]) -> str:
    lines = []
    for s in series:
        runs = s["runs"]
        lines.append(f"{s['name']}  split={s['split']}  dataset={s['dataset']}  ({len(runs)} run{'s' if len(runs) != 1 else ''})")
        lines.append(f"  trend  {sparkline([r.pass_rate for r in runs])}  {runs[0].pass_rate:.0%} -> {runs[-1].pass_rate:.0%}")
        lines.append(f"  {'started':<17}{'pass rate (95% CI)':<24}{'errors':>7}{'cost':>9}{'p50':>7}  {'git':<8}status")
        for r in runs:
            lines.append(f"  {r.started.astimezone().strftime('%Y-%m-%d %H:%M'):<17}"
                         f"{r.pass_rate:>5.0%} ({r.ci[0]:.0%}-{r.ci[1]:.0%})".ljust(41)
                         + f"{r.error_rate:>7.0%}{('$%.2f' % r.cost):>9}{r.p50:>6.2f}s  {r.git:<8}{r.status}"
                         + (f" ({r.incomplete} not run)" if r.incomplete else ""))
        g = s["regression"]
        if g is not None and g["n"]:
            verdict = "REGRESSION" if g["regressed"] else ("improved" if g["delta"] > 0 and g["p"] < 0.05 else "no significant change")
            lines.append(f"  latest vs previous: {g['delta']:+.1%} (95% CI {g['ci'][0]:+.1%} to {g['ci'][1]:+.1%}, p = {g['p']:.3f}) -> {verdict}"
                         + (f"; changed: {'; '.join(s['changes'])}" if s["changes"] else "; nothing recorded as changed"))
        lines.append("")
    return "\n".join(lines).rstrip()


def _svg(runs: list[RunRecord], w: int = 640, h: int = 170) -> str:
    pad_l, pad_r, pad_t, pad_b = 40, 12, 12, 24
    n = len(runs)
    x = lambda i: pad_l + (w - pad_l - pad_r) * (i / max(1, n - 1) if n > 1 else 0.5)  # noqa: E731
    y = lambda v: pad_t + (h - pad_t - pad_b) * (1 - v)  # noqa: E731
    band = " ".join(f"{x(i):.1f},{y(r.ci[1]):.1f}" for i, r in enumerate(runs)) + " " + \
        " ".join(f"{x(i):.1f},{y(r.ci[0]):.1f}" for i, r in reversed(list(enumerate(runs))))
    line = " ".join(f"{x(i):.1f},{y(r.pass_rate):.1f}" for i, r in enumerate(runs))
    grid = "".join(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e6e6e6"/>'
                   f'<text x="4" y="{y(v) + 4:.1f}" font-size="10" fill="#666">{v:.0%}</text>' for v in (0, 0.5, 1))
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(r.pass_rate):.1f}" r="3.5" fill="#1f6feb"><title>'
                   f'{escape(r.started.strftime("%Y-%m-%d %H:%M"))}: {r.pass_rate:.0%} (CI {r.ci[0]:.0%}-{r.ci[1]:.0%}), git {escape(r.git)}'
                   f'</title></circle>' for i, r in enumerate(runs))
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="pass rate over runs">{grid}'
            f'<polygon points="{band}" fill="#1f6feb" opacity="0.12"/><polyline points="{line}" fill="none" stroke="#1f6feb" stroke-width="2"/>{dots}</svg>')


def render_html(series: list[dict]) -> str:
    css = ("body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:2rem auto;max-width:900px;padding:0 1rem}"
           "table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #eee;text-align:left;padding:.3rem .5rem}"
           ".bad{color:#b3261e;font-weight:600}.ok{color:#0a7d33}.meta{color:#666;font-size:.85rem}")
    out = [f"<!doctype html><html lang=en><meta charset=utf-8><title>Run history</title><style>{css}</style><h1>Run history</h1>"]
    for s in series:
        runs, g = s["runs"], s["regression"]
        out.append(f"<h2>{escape(s['name'])} <span class=meta>split {escape(s['split'])} · dataset {escape(s['dataset'])}</span></h2>")
        out.append(_svg(runs))
        if g is not None and g["n"]:
            cls, word = ("bad", "REGRESSION") if g["regressed"] else ("ok", "no significant regression")
            out.append(f"<p>Latest vs previous: {g['delta']:+.1%} (p = {g['p']:.3f}) <span class={cls}>{word}</span>"
                       + (f" · changed: {escape('; '.join(s['changes']))}" if s["changes"] else "") + "</p>")
        out.append("<table><tr><th>started</th><th>pass rate</th><th>errors</th><th>cost</th><th>git</th><th>status</th></tr>")
        for r in runs:
            out.append(f"<tr><td>{escape(r.started.astimezone().strftime('%Y-%m-%d %H:%M'))}</td><td>{r.pass_rate:.0%} "
                       f"({r.ci[0]:.0%}-{r.ci[1]:.0%})</td><td>{r.error_rate:.0%}</td><td>${r.cost:.2f}</td>"
                       f"<td>{escape(r.git)}</td><td>{escape(r.status)}</td></tr>")
        out.append("</table>")
    return "".join(out)
