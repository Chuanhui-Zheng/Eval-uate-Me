"""Self-contained HTML report (minimal JS for trace drill-down, no external assets) built from a run directory."""
from __future__ import annotations

import json
from html import escape

from pathlib import Path

from .formats import read_json, read_jsonl

_MAX = 2000

_CSS = """
body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#1a1a1a}
h1{font-size:1.4rem;margin-bottom:.2rem}h2{font-size:1.1rem;margin-top:2rem}
.meta{color:#666;font-size:.85rem}
.cards{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}
.card{border:1px solid #ddd;border-radius:8px;padding:.7rem 1rem;min-width:130px}
.card b{display:block;font-size:1.4rem}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #eee;text-align:left;padding:.35rem .5rem}
.pass{color:#0a7d33;font-weight:600}.fail{color:#b3261e;font-weight:600}
details{border-bottom:1px solid #eee;padding:.4rem 0}summary{cursor:pointer}
pre{background:#f6f6f6;padding:.5rem;border-radius:6px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.trace-step{cursor:pointer;user-select:none}.trace-step td:first-child::before{content:"▶ ";font-size:.7rem;color:#999}
.trace-step.open td:first-child::before{content:"▼ ";color:#555}
.trace-detail{display:none}.trace-step.open+.trace-detail{display:table-row}
.trace-detail td{background:#f9f9f9;font-size:.85rem}
"""

_JS = """
<script>
document.addEventListener('click', function(e) {
  var row = e.target.closest('.trace-step');
  if (!row) return;
  row.classList.toggle('open');
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


def render(run_dir: Path) -> str:
    run_dir = Path(run_dir)
    summary = read_json(run_dir / "summary.json")
    mf = run_dir / "manifest.json"
    manifest = read_json(mf) if mf.exists() else {}
    rows = read_jsonl(run_dir / "results.jsonl")

    lo, hi = summary["pass_rate_ci95"]
    cards = [("Pass rate", _pct(summary["pass_rate"])), ("95% CI", f"{_pct(lo)}–{_pct(hi)}"),
             ("Cases", str(summary["cases"])), ("Attempts", str(summary["total"])),
             ("Errors", f"{summary['errors']} ({summary.get('error_rate', 0):.0%})"),
             ("Pass (answered only)", _pct(summary.get("pass_rate_answered", summary["pass_rate"]))), ("p50 latency", f"{summary['latency_p50_s']:.2f}s")]
    if summary.get("split", "all") != "all":
        cards.append(("Split", summary["split"] + (f" (look #{summary['heldout_looks']})" if summary.get("heldout_looks") else "")))
    for k, v in sorted(summary.get("usage_total", {}).items()):
        cards.append((k, f"{v:g}"))

    out = [f"<!doctype html><html lang=en><meta charset=utf-8><title>{escape(summary['name'])}</title>",
           f"<style>{_CSS}</style>", f"<h1>{escape(summary['name'])}</h1>",
           f"<div class=meta>{escape(str(manifest.get('started_at', '')))} · dataset "
           f"{escape(str(manifest.get('dataset_sha256', ''))[:12])}"
           + (f" ({escape((manifest.get('dataset_meta') or {}).get('name', ''))} v{escape((manifest.get('dataset_meta') or {}).get('version', '?'))}"
              f", {escape((manifest.get('dataset_meta') or {}).get('license', 'licence unrecorded'))})" if manifest.get('dataset_meta') else "")
           + f" · git "
           f"{escape(str((manifest.get('git') or {}).get('commit') or '-')[:10])}</div>",
           "<div class=cards>" + "".join(f"<div class=card>{escape(k)}<b>{escape(v)}</b></div>" for k, v in cards) + "</div>"]

    if summary.get("privacy_store") == "scores_only":
        out.append("<p class=meta><b>Privacy mode:</b> inputs, references, outputs, traces and failure reasons "
                   "were not stored; only ids, verdicts, scores, latency and usage.</p>")
    if summary.get("by_tag"):
        out.append("<h2>By tag</h2><table><tr><th>tag</th><th>cases</th><th>pass rate</th></tr>")
        for t, d in sorted(summary["by_tag"].items(), key=lambda kv: kv[1]["pass_rate"]):
            out.append(f"<tr><td>{escape(t)}</td><td>{d['cases']}</td><td>{_pct(d['pass_rate'])}</td></tr>")
        out.append("</table>")

    if summary.get("failure_reasons"):
        out.append("<h2>Failure reasons</h2><table><tr><th>reason</th><th>attempts</th></tr>")
        for r, n in sorted(summary["failure_reasons"].items(), key=lambda kv: -kv[1]):
            out.append(f"<tr><td>{escape(r)}</td><td>{n}</td></tr>")
        out.append("</table>")

    ordered = sorted(rows, key=lambda d: d["passed"])  # failures first
    labels = {id(d): d["case"]["id"] + (f"#{d['attempt']}" if summary.get("repeats", 1) > 1 else "") for d in rows}
    anchors = {id(d): f"case-{n}" for n, d in enumerate(ordered)}

    def link(d) -> str:
        return f'<a href="#{anchors[id(d)]}">{escape(labels[id(d)])}</a>'

    failed = [d for d in ordered if not d["passed"]]
    if failed:
        out.append("<h2>Jump to failures</h2><p>" + " · ".join(link(d) for d in failed[:30])
                   + (f" · … {len(failed) - 30} more" if len(failed) > 30 else "") + "</p>")
    slow = sorted(rows, key=lambda d: -d["result"]["latency_s"])[:5]
    costly = [d for d in sorted(rows, key=lambda d: -(d["result"].get("usage") or {}).get("cost_usd", 0.0))[:5]
              if (d["result"].get("usage") or {}).get("cost_usd", 0.0) > 0]
    out.append("<h2>Slowest and costliest</h2><table><tr><th>slowest</th><th>latency</th>"
               + ("<th>costliest</th><th>cost</th>" if costly else "") + "</tr>")
    for i, d in enumerate(slow):
        extra = ""
        if costly:
            extra = (f"<td>{link(costly[i])}</td><td>${costly[i]['result']['usage']['cost_usd']:.4f}</td>" if i < len(costly)
                     else "<td></td><td></td>")
        out.append(f"<tr><td>{link(d)}</td><td>{d['result']['latency_s']:.2f}s</td>{extra}</tr>")
    out.append("</table>")

    out.append("<h2>Results</h2>")
    for d in ordered:
        c, r = d["case"], d["result"]
        label = labels[id(d)]
        cls, word = ("pass", "PASS") if d["passed"] else ("fail", "FAIL")
        out.append(f'<details id="{anchors[id(d)]}"><summary><span class={cls}>{word}</span> {escape(label)} '
                   f"<span class=meta>{r['latency_s']:.2f}s</span></summary>")
        facts = []
        if r.get("retries"):
            facts.append(f"{r['retries']} retr{'y' if r['retries'] == 1 else 'ies'}")
        if r.get("cached"):
            facts.append("served from cache")
        if r.get("usage"):
            facts.append(", ".join(f"{escape(str(k))} {v:g}" for k, v in sorted(r["usage"].items())))
        if facts:
            out.append(f"<p class=meta>{' · '.join(facts)}</p>")
        if r.get("error"):
            out.append(f"<p class=fail>error: {escape(str(r['error']))}</p>")
        if summary.get("privacy_store") != "scores_only":
            out.append(f"<b>input</b><pre>{_fmt(c['input'])}</pre><b>expected</b><pre>{_fmt(c['expected'])}</pre>"
                       f"<b>output</b><pre>{_fmt(r['output'])}</pre>")
        if d["scores"]:
            out.append("<table><tr><th>grader</th><th>score</th><th>result</th><th>reason</th></tr>")
            for s in d["scores"]:
                sc, sw = ("pass", "pass") if s["passed"] else ("fail", "fail")
                out.append(f"<tr><td>{escape(s['grader'])}{' <i>(advisory)</i>' if s.get('role') == 'advisory' else ''}</td><td>{s['value']:.2f}</td>"
                           f"<td class={sc}>{sw}</td><td>{escape(s['reason'])}</td></tr>")
            out.append("</table>")
        trace = r.get("trace") or []
        if trace:
            out.append(f"<b>trace</b> <span class=meta>({len(trace)} step{'s' if len(trace) != 1 else ''} — click to expand)</span>"
                       "<table><tr><th>#</th><th>tool / step</th><th>round</th><th>summary</th></tr>")
            for n, step in enumerate(trace[:100], 1):
                if isinstance(step, dict):
                    head = escape(str(step.get("tool") or step.get("step") or ""))
                    rnd = escape(str(step.get("round", "")))
                    rest = {k: v for k, v in step.items() if k not in ("tool", "step", "round")}
                    summary_parts = []
                    for k in ("model", "cve_id", "found", "error"):
                        if k in rest:
                            summary_parts.append(f"{k}={escape(str(rest[k]))}")
                    inline = ", ".join(summary_parts[:3])
                    detail = _fmt(rest) if rest else ""
                else:
                    head, rnd, inline, detail = "", "", "", _fmt(step)
                out.append(f"<tr class=trace-step><td>{n}</td><td>{head}</td><td>{rnd}</td><td>{inline}</td></tr>")
                if detail:
                    out.append(f"<tr class=trace-detail><td colspan=4><pre>{detail}</pre></td></tr>")
            if len(trace) > 100:
                out.append(f"<tr><td colspan=4>… {len(trace) - 100} more steps</td></tr>")
            out.append("</table>")
        out.append("</details>")
    out.append(_JS)
    return "".join(out)


def write(run_dir: Path) -> Path:
    p = Path(run_dir) / "report.html"
    p.write_text(render(run_dir), encoding="utf-8")
    return p
