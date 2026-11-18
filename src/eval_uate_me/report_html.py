"""Self-contained HTML report (no external assets) built from a run directory."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .formats import read_json, read_jsonl

_MAX = 2000

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.6 -apple-system,system-ui,'Segoe UI',sans-serif;background:#f5f6fa;color:#1a1a2e;min-height:100vh}
.page{max-width:1080px;margin:0 auto;padding:2rem 1.5rem}
h1{font-size:1.5rem;font-weight:700;color:#1a1a2e;margin-bottom:.25rem}
h2{font-size:1rem;font-weight:600;color:#444;margin:2rem 0 .75rem;text-transform:uppercase;letter-spacing:.05em}
.meta{color:#888;font-size:.82rem;margin-bottom:1.5rem}

.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:.75rem;margin:1.25rem 0}
.card{background:#fff;border:1px solid #e8eaed;border-radius:12px;padding:.9rem 1.1rem;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.card-label{font-size:.75rem;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:.3rem}
.card-value{font-size:1.5rem;font-weight:700;color:#1a1a2e;line-height:1}
.card.good .card-value{color:#0a7d33}
.card.bad .card-value{color:#c0392b}
.card.neutral .card-value{color:#2563eb}

.dims{display:flex;flex-direction:column;gap:.5rem;margin:1rem 0 1.5rem}
.dim-row{display:flex;align-items:center;gap:.75rem}
.dim-label{width:140px;font-size:.82rem;color:#555;text-align:right;flex-shrink:0}
.dim-bar-wrap{flex:1;background:#eef0f4;border-radius:99px;height:10px;overflow:hidden}
.dim-bar{height:100%;border-radius:99px;background:linear-gradient(90deg,#2563eb,#7c3aed);transition:width .3s}
.dim-score{width:36px;font-size:.82rem;font-weight:600;color:#444;text-align:right}

.jump-links{display:flex;flex-wrap:wrap;gap:.35rem;margin:.5rem 0 1.5rem}
.jump-link{font-size:.78rem;padding:.2rem .6rem;border-radius:99px;background:#fef2f2;color:#c0392b;text-decoration:none;border:1px solid #fecaca}
.jump-link:hover{background:#fee2e2}

table{width:100%;border-collapse:collapse}
th{font-size:.78rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:#888;padding:.5rem .75rem;border-bottom:2px solid #eef0f4;text-align:left}
td{padding:.45rem .75rem;border-bottom:1px solid #f0f0f4;font-size:.85rem;vertical-align:top}
tr:last-child td{border-bottom:none}

.case-card{background:#fff;border:1px solid #e8eaed;border-radius:12px;margin-bottom:.6rem;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.case-header{display:flex;align-items:center;gap:.75rem;padding:.7rem 1rem;cursor:pointer;user-select:none}
.case-header:hover{background:#fafbfc}
.badge{font-size:.72rem;font-weight:700;padding:.2rem .55rem;border-radius:99px;letter-spacing:.03em}
.badge.pass{background:#dcfce7;color:#15803d}
.badge.fail{background:#fee2e2;color:#b91c1c}
.case-id{font-weight:600;font-size:.88rem;color:#1a1a2e}
.case-latency{margin-left:auto;font-size:.78rem;color:#aaa}
.case-body{padding:.75rem 1rem 1rem;border-top:1px solid #f0f0f4;display:none}
.case-card.open .case-body{display:block}
.case-card.open .case-header{background:#fafbfc}

.field-label{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:#888;margin:.75rem 0 .3rem}
.field-label:first-child{margin-top:0}
pre{background:#1e1e2e;color:#cdd6f4;padding:.85rem 1rem;border-radius:8px;overflow-x:auto;font-size:.8rem;line-height:1.5;white-space:pre-wrap;word-break:break-word}
pre .kw{color:#cba6f7}pre .str{color:#a6e3a1}pre .num{color:#fab387}pre .cmt{color:#6c7086;font-style:italic}

.score-row{display:flex;align-items:center;gap:.6rem;padding:.3rem 0}
.score-name{width:130px;font-size:.82rem;color:#555}
.score-mini-bar{flex:1;background:#eef0f4;border-radius:99px;height:7px;overflow:hidden}
.score-mini-fill{height:100%;border-radius:99px}
.score-mini-fill.pass{background:#22c55e}
.score-mini-fill.fail{background:#ef4444}
.score-val{width:32px;font-size:.78rem;font-weight:600;text-align:right}
.score-reason{font-size:.78rem;color:#888;margin-top:.15rem;padding-left:130px}
.error-box{background:#fff1f1;border:1px solid #fecaca;border-radius:8px;padding:.6rem .9rem;font-size:.82rem;color:#b91c1c;margin:.5rem 0}

.trace-wrap{margin-top:.75rem}
.trace-step-row{cursor:pointer}
.trace-step-row td:first-child{color:#2563eb;font-weight:600}
.trace-step-row:hover td{background:#fafbfc}
.trace-detail-row{display:none}
.trace-step-row.open+.trace-detail-row{display:table-row}
.trace-detail-row td{background:#f8f9fb;padding:.5rem 1rem}

.section-box{background:#fff;border:1px solid #e8eaed;border-radius:12px;overflow:hidden;margin-bottom:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.section-box table{margin:0}
"""

_JS = """
<script>
document.querySelectorAll('.case-header').forEach(function(h){
  h.addEventListener('click',function(){h.closest('.case-card').classList.toggle('open')});
});
document.addEventListener('click',function(e){
  var row=e.target.closest('.trace-step-row');
  if(row) row.classList.toggle('open');
});
</script>
"""


def _fmt(v) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2, default=str)
    if len(s) > _MAX:
        s = s[:_MAX] + f"\n… ({len(s) - _MAX} more characters)"
    return escape(s)


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _bar(score: float, cls: str = "") -> str:
    pct = int(score * 100)
    return (f'<div class="score-mini-bar"><div class="score-mini-fill {cls}" style="width:{pct}%"></div></div>'
            f'<div class="score-val">{score:.2f}</div>')


def render(run_dir: Path) -> str:
    run_dir = Path(run_dir)
    summary = read_json(run_dir / "summary.json")
    mf = run_dir / "manifest.json"
    manifest = read_json(mf) if mf.exists() else {}
    rows = read_jsonl(run_dir / "results.jsonl")

    name = summary["name"]
    lo, hi = summary["pass_rate_ci95"]
    pr = summary["pass_rate"]
    pr_cls = "good" if pr >= 0.8 else ("bad" if pr < 0.5 else "neutral")

    # ── header ──────────────────────────────────────────────────────────────
    out = [f'<!doctype html><html lang=en><meta charset=utf-8>',
           f'<meta name=viewport content="width=device-width,initial-scale=1">',
           f'<title>{escape(name)}</title>',
           f'<style>{_CSS}</style>',
           '<div class=page>',
           f'<h1>{escape(name)}</h1>',
           f'<p class=meta>{escape(str(manifest.get("started_at","")))}']

    split = summary.get("split", "all")
    if split != "all":
        out.append(f' · split: <b>{escape(split)}</b>')
    git = (manifest.get("git") or {}).get("commit")
    if git:
        out.append(f' · git {escape(str(git)[:10])}')
    out.append('</p>')

    # ── summary cards ────────────────────────────────────────────────────────
    cards = [
        ("Pass rate", _pct(pr), pr_cls),
        ("95 % CI", f"{_pct(lo)}–{_pct(hi)}", "neutral"),
        ("Cases", str(summary["cases"]), "neutral"),
        ("Errors", f"{summary['errors']}", "bad" if summary["errors"] else "good"),
        ("p50 latency", f"{summary['latency_p50_s']:.2f}s", "neutral"),
    ]
    if summary.get("repeats", 1) > 1:
        cards.append(("Repeats", str(summary["repeats"]), "neutral"))
    for k, v in sorted(summary.get("usage_total", {}).items()):
        cards.append((k, f"{v:g}", "neutral"))

    out.append('<div class=cards>')
    for label, val, cls in cards:
        out.append(f'<div class="card {cls}"><div class=card-label>{escape(label)}</div>'
                   f'<div class=card-value>{escape(val)}</div></div>')
    out.append('</div>')

    # ── dimension bars ───────────────────────────────────────────────────────
    dims = {k.replace("llm_judge dimensions: ", "").split()[0]: v
            for k, v in summary.items()
            if "dimensions" in str(k)}
    dim_data = summary.get("grader_dimensions", {})
    # fall back: parse from summary keys
    for k, v in summary.items():
        if isinstance(k, str) and k.startswith("llm_judge dimensions:"):
            pass
    # read from summary directly
    dim_data = {}
    for k, v in summary.items():
        if isinstance(k, str) and " dimensions: " in k:
            for part in str(v).split(", ") if isinstance(v, str) else []:
                nm, _, sc = part.partition(" ")
                try:
                    dim_data[nm] = float(sc)
                except ValueError:
                    pass
    # also check nested
    if not dim_data:
        for k, v in summary.items():
            if isinstance(k, str) and k.endswith("_dimensions") and isinstance(v, dict):
                dim_data.update(v)

    if dim_data:
        out.append('<h2>Dimension scores</h2><div class=dims>')
        for nm, sc in sorted(dim_data.items(), key=lambda x: -x[1]):
            pct = int(float(sc) * 100)
            out.append(f'<div class=dim-row>'
                       f'<div class=dim-label>{escape(nm)}</div>'
                       f'<div class=dim-bar-wrap><div class=dim-bar style="width:{pct}%"></div></div>'
                       f'<div class=dim-score>{float(sc):.2f}</div></div>')
        out.append('</div>')

    # ── failure jump links ───────────────────────────────────────────────────
    ordered = sorted(rows, key=lambda d: d["passed"])
    labels = {id(d): d["case"]["id"] + (f"#{d['attempt']}" if summary.get("repeats", 1) > 1 else "")
              for d in rows}
    anchors = {id(d): f"c{n}" for n, d in enumerate(ordered)}
    failed = [d for d in ordered if not d["passed"]]

    if failed:
        out.append(f'<h2>{len(failed)} failure{"s" if len(failed) != 1 else ""}</h2>'
                   '<div class=jump-links>')
        for d in failed[:40]:
            out.append(f'<a class=jump-link href="#{anchors[id(d)]}">{escape(labels[id(d)])}</a>')
        if len(failed) > 40:
            out.append(f'<span style="font-size:.78rem;color:#888">… {len(failed)-40} more</span>')
        out.append('</div>')

    # ── failure reasons ──────────────────────────────────────────────────────
    if summary.get("failure_reasons"):
        out.append('<h2>Failure breakdown</h2><div class=section-box><table>'
                   '<tr><th>reason</th><th>count</th></tr>')
        for r, n in sorted(summary["failure_reasons"].items(), key=lambda kv: -kv[1]):
            out.append(f'<tr><td>{escape(r)}</td><td>{n}</td></tr>')
        out.append('</table></div>')

    # ── per-case results ─────────────────────────────────────────────────────
    out.append('<h2>Results</h2>')
    for d in ordered:
        c, r = d["case"], d["result"]
        label = labels[id(d)]
        is_pass = d["passed"]
        badge_cls = "pass" if is_pass else "fail"
        badge_txt = "PASS" if is_pass else "FAIL"

        out.append(f'<div class=case-card id="{anchors[id(d)]}">')
        out.append(f'<div class=case-header>'
                   f'<span class="badge {badge_cls}">{badge_txt}</span>'
                   f'<span class=case-id>{escape(label)}</span>'
                   f'<span class=case-latency>{r["latency_s"]:.2f}s</span>'
                   f'</div>')
        out.append('<div class=case-body>')

        if r.get("error"):
            out.append(f'<div class=error-box>⚠ {escape(str(r["error"]))}</div>')

        if summary.get("privacy_store") != "scores_only":
            for field, val in [("input", c["input"]), ("expected", c.get("expected")), ("output", r["output"])]:
                if val is None:
                    continue
                out.append(f'<div class=field-label>{field}</div><pre>{_fmt(val)}</pre>')

        if d["scores"]:
            out.append('<div class=field-label>scores</div>')
            for s in d["scores"]:
                sc_cls = "pass" if s["passed"] else "fail"
                out.append(f'<div class=score-row>'
                           f'<div class=score-name>{escape(s["grader"])}</div>'
                           + _bar(s["value"], sc_cls) +
                           f'</div>')
                if s.get("reason"):
                    out.append(f'<div class=score-reason>{escape(s["reason"])}</div>')

        trace = r.get("trace") or []
        if trace:
            out.append(f'<div class=field-label>trace ({len(trace)} step{"s" if len(trace)!=1 else ""})</div>'
                       '<div class=trace-wrap><table>'
                       '<tr><th>#</th><th>tool</th><th>round</th><th>summary</th></tr>')
            for n, step in enumerate(trace[:100], 1):
                if isinstance(step, dict):
                    head = escape(str(step.get("tool") or step.get("step") or ""))
                    rnd = escape(str(step.get("round", "")))
                    rest = {k: v for k, v in step.items() if k not in ("tool","step","round")}
                    parts = [f"{k}={escape(str(v))}" for k in ("model","found","error") if k in rest]
                    detail = _fmt(rest) if rest else ""
                else:
                    head, rnd, parts, detail = "", "", [], _fmt(step)
                out.append(f'<tr class=trace-step-row><td>{n}</td><td>{head}</td>'
                           f'<td>{rnd}</td><td>{", ".join(parts)}</td></tr>')
                if detail:
                    out.append(f'<tr class=trace-detail-row><td colspan=4><pre>{detail}</pre></td></tr>')
            if len(trace) > 100:
                out.append(f'<tr><td colspan=4 style="color:#888">… {len(trace)-100} more steps</td></tr>')
            out.append('</table></div>')

        out.append('</div></div>')  # case-body, case-card

    out.append(_JS)
    out.append('</div>')  # page
    return "".join(out)


def write(run_dir: Path) -> Path:
    p = Path(run_dir) / "report.html"
    p.write_text(render(run_dir), encoding="utf-8")
    return p
