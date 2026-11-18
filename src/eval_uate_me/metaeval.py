"""Meta-evaluation: does this evaluation actually catch bad systems?

Mutation testing for evals. A mutant is a deliberately damaged variant of the system, run next to the real target on the same
cases and graders. It is

  killed    the evaluation scores it significantly lower (paired sign-flip test, and by at least --min-drop)
  survived  the evaluation cannot tell it from the real thing: a blind spot in the graders or the dataset
  no-op     it produced exactly the real target's output on every case, so it never tested anything

There are three ways to make mutants:
  [[mutants]] with a [mutants.target]   a different target you wrote (e.g. an agent with a known bug)
  [[mutants]] with an `operator`        damage the real target's recorded output at a path (see mutation.py)
  --auto                                generate operator mutants for every field found in the real outputs; a field whose every
                                        mutant survives is a field no grader looks at
and, for operator mutants, a `rates` list (or --sensitivity) measures how OFTEN the damage must occur before the evaluation
notices: the smallest detectable rate. Catching a mutant says the evaluation catches *that* defect, not that it catches yours.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .config import Config, ConfigError
from .isolation import wrap_target
from .models import Case, CaseResult
from .mutation import MutatedTarget, generate_mutants
from .runner import _make, _run_case, build_graders, load_plugins
from .stats import mean, paired_permutation_p

DEFAULT_RATES = (0.05, 0.1, 0.25, 0.5, 1.0)


@dataclass
class MutantResult:
    name: str
    pass_rate: float
    delta: float
    p_value: float
    status: str  # killed | survived | no-op
    caught_by: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    source: str = "config"  # config | auto
    operator: str | None = None
    path: str | None = None
    mutated_cases: int | None = None
    curve: list[dict[str, Any]] = field(default_factory=list)
    min_detectable_rate: float | None = None


def _run_all(target, graders, cases: list[Case], repeats: int, workers: int) -> list[CaseResult]:
    jobs = [(c, a) for c in cases for a in range(repeats)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda j: _run_case(target, graders, j[0], j[1]), jobs))


def _per_case(results: list[CaseResult]) -> dict[str, float]:
    acc: dict[str, list[float]] = {}
    for r in results:
        acc.setdefault(r.case.id, []).append(float(r.passed))
    return {k: mean(v) for k, v in acc.items()}


def _judge(base_rates: dict[str, float], rates: dict[str, float], identical: bool, min_drop: float, alpha: float) -> tuple[float, float, str]:
    ids = sorted(base_rates)
    delta = mean([rates[i] for i in ids]) - mean([base_rates[i] for i in ids])
    p = paired_permutation_p([rates[i] - base_rates[i] for i in ids])
    status = "no-op" if identical else "killed" if (delta <= -min_drop and p < alpha) else "survived"
    return delta, p, status


def _caught_by(results: list[CaseResult], base_by_job: dict[tuple[str, int], CaseResult]) -> dict[str, int]:
    caught: dict[str, int] = {}
    for r in results:
        base_ok = {s.grader for s in base_by_job[(r.case.id, r.attempt)].scores if s.passed}
        for s in r.scores:
            if not s.passed and s.role == "required" and s.grader in base_ok:
                caught[s.grader] = caught.get(s.grader, 0) + 1
    return dict(sorted(caught.items(), key=lambda kv: -kv[1]))


def run_meta_eval(cfg: Config, cases: list[Case], min_drop: float = 0.10, alpha: float = 0.05, repeats: int | None = None, *,
                  sensitivity: list[float] | tuple[float, ...] | None = None, auto: bool = False, max_mutants: int = 150,
                  seed: int = 0, allow_network: bool = False) -> dict[str, Any]:
    if not cfg.mutants and not auto:
        raise ConfigError("no [[mutants]] in the config: list at least one deliberately damaged variant of the target "
                          "(or run with --auto to generate damage for every field of the real outputs)")
    load_plugins(cfg)
    graders = build_graders(cfg)
    if (auto or sensitivity) and any(getattr(g, "network", None) is True for g in graders) and not allow_network:
        raise ConfigError("--auto and --sensitivity run every grader once per mutant, and a grader here sends data to a hosted model "
                          "(that can mean thousands of paid calls): pass --allow-network if that is intended")
    reps = repeats or cfg.repeats
    base_target = wrap_target(cfg, _make("target", cfg.target, "[target]"), cfg.target)
    base = _run_all(base_target, graders, cases, reps, cfg.concurrency)
    base_rates = _per_case(base)
    base_by_job = {(r.case.id, r.attempt): r for r in base}
    base0 = [r for r in base if r.attempt == 0]
    base0_rates = _per_case(base0)
    replay = {r.case.id: r.result for r in base0}
    warnings: list[str] = []
    base_pass = mean(list(base_rates.values()))
    if base_pass < 0.8:
        warnings.append(f"the real target passes only {base_pass:.0%} of cases: kills are measured against a weak baseline and "
                        "mean little until it is fixed")
    if len({c.id for c in cases}) < 6:
        warnings.append("with fewer than 6 cases no difference can reach p < 0.05, so nothing can be 'killed'; add cases")

    specs: list[dict[str, Any]] = [dict(m, _source="config") for m in cfg.mutants]
    if auto:
        taken = {m["name"] for m in specs}
        specs += [dict(m, _source="auto") for m in generate_mutants([o.output for o in replay.values() if o.error is None], max_mutants, seed)
                  if m["name"] not in taken]

    out: list[MutantResult] = []
    for m in specs:
        src = m["_source"]
        if "target" in m:
            target = wrap_target(cfg, _make("target", m["target"], f"mutant '{m['name']}'"), m["target"])
            res = _run_all(target, graders, cases, reps, cfg.concurrency)
            rates = _per_case(res)
            identical = all(json.dumps(r.result.output, sort_keys=True, default=str)
                            == json.dumps(base_by_job[(r.case.id, r.attempt)].result.output, sort_keys=True, default=str) for r in res)
            delta, p, status = _judge(base_rates, rates, identical, min_drop, alpha)
            out.append(MutantResult(m["name"], mean(list(rates.values())), delta, p, status, _caught_by(res, base_by_job),
                                    sum(r.result.error is not None for r in res), src))
            continue
        # an operator mutant: damage the recorded outputs of the real target (attempt 0), at one or several rates
        explicit = m.get("rates") or ([m["rate"]] if "rate" in m else None)
        rates_to_run = list(explicit or (sensitivity if sensitivity else [1.0]))
        params: dict[str, Any] = {k: m[k] for k in ("pattern", "replacement", "delta", "factor", "which") if k in m}
        curve, last = [], None
        for r in sorted(rates_to_run):
            tgt = MutatedTarget(replay, m["name"], m["operator"], m.get("path", ""), r, int(m.get("seed", seed)), params)
            res = _run_all(tgt, graders, cases, 1, cfg.concurrency)
            rr = _per_case(res)
            delta, p, status = _judge(base0_rates, rr, not tgt.mutated, min_drop, alpha)
            curve.append({"rate": r, "pass_rate": mean(list(rr.values())), "delta": delta, "p_value": p, "status": status,
                          "mutated_cases": len(tgt.mutated)})
            last = (res, rr, delta, p, status, tgt)
        assert last is not None
        res, rr, delta, p, status, tgt = last
        killed_rates = [c["rate"] for c in curve if c["status"] == "killed"]
        out.append(MutantResult(m["name"], mean(list(rr.values())), delta, p, status, _caught_by(res, base_by_job),
                                sum(r.result.error is not None for r in res), src, m["operator"], m.get("path", ""),
                                len(tgt.mutated), curve if len(curve) > 1 else [], min(killed_rates) if killed_rates and len(curve) > 1 else None))

    decided = [mr for mr in out if mr.status in ("killed", "survived")]
    score = sum(mr.status == "killed" for mr in decided) / len(decided) if decided else None
    by_path: dict[str, dict[str, Any]] = {}
    for mr in out:
        if mr.operator and mr.path:
            e = by_path.setdefault(mr.path, {"killed": 0, "survived": 0, "no-op": 0, "survivors": []})
            e[mr.status] += 1
            if mr.status == "survived":
                e["survivors"].append(mr.operator)
    blind = sorted(p for p, e in by_path.items() if e["survived"] and not e["killed"])
    return {"cases": len(cases), "repeats": reps, "baseline_pass_rate": base_pass, "min_drop": min_drop, "alpha": alpha,
            "mutants": [mr.__dict__ for mr in out], "mutation_score": score, "warnings": warnings, "auto": auto,
            "by_path": by_path, "blind_spots": blind,
            "auto_survivors": sum(mr.status == "survived" for mr in out if mr.source == "auto"),
            "ok": all(mr.status != "survived" for mr in out if mr.source == "config")}


def format_meta_eval(r: dict[str, Any]) -> str:
    ms = r["mutants"]
    explicit = [m for m in ms if m["source"] == "config"]
    lines = [f"meta-eval: {r['cases']} cases x {r['repeats']} repeat(s); the real target passes "
             f"{r['baseline_pass_rate']:.0%}; killed = lower by >= {r['min_drop']:.0%} with p < {r['alpha']}"]
    if explicit:
        w = max([len(m["name"]) for m in explicit] + [6]) + 2
        lines.append(f"{'mutant':<{w}}{'pass':>6}{'delta':>8}{'p':>8}  {'status':<9} caught by")
        for m in explicit:
            by = ", ".join(f"{g} ({n})" for g, n in list(m["caught_by"].items())[:3]) or "-"
            lines.append(f"{m['name']:<{w}}{m['pass_rate']:>6.0%}{m['delta']:>+8.0%}{m['p_value']:>8.3f}  {m['status']:<9} {by}")
        for m in explicit:
            if m["status"] == "survived":
                lines.append(f"  SURVIVED: '{m['name']}' scores about as well as the real target, so these graders and "
                             "this dataset cannot tell it apart. Add a grader or cases that expose it.")
            if m["status"] == "no-op":
                lines.append(f"  no-op: '{m['name']}' produced the real target's exact output on every case; it tested nothing.")
            if m["errors"]:
                lines.append(f"  note: '{m['name']}' errored on {m['errors']} attempt(s); errors count as failures.")
    curves = [m for m in ms if m["curve"]]
    if curves:
        lines.append("sensitivity: how often the damage must occur before the evaluation notices")
        for m in curves:
            steps = "  ".join(f"{c['rate']:.0%}:{c['status'][0]}" for c in m["curve"])
            tail = (f"first noticed at {m['min_detectable_rate']:.0%} of cases" if m["min_detectable_rate"] is not None
                    else "never noticed, even at the highest rate")
            lines.append(f"  {m['name']}: {steps}  -> {tail}   (k=killed s=survived n=no-op)")
    auto = [m for m in ms if m["source"] == "auto"]
    if auto:
        tot = {k: sum(m["status"] == k for m in auto) for k in ("killed", "survived", "no-op")}
        lines.append(f"auto mutation: {len(auto)} mutants over {len(r['by_path'])} paths: killed {tot['killed']}, "
                     f"survived {tot['survived']}, no-op {tot['no-op']}")
        w = max([len(p) for p in r["by_path"]] + [4]) + 2
        lines.append(f"{'path':<{w}}{'killed':>7}{'survived':>9}  survivors")
        for p, e in sorted(r["by_path"].items(), key=lambda kv: (-kv[1]["survived"], kv[0])):
            if e["survived"] or e["killed"]:
                tag = "   <- BLIND SPOT: no grader notices damage here" if p in r["blind_spots"] else ""
                lines.append(f"{p:<{w}}{e['killed']:>7}{e['survived']:>9}  {', '.join(e['survivors'])}{tag}")
    lines += [f"  warning: {w}" for w in r["warnings"]]
    score = r["mutation_score"]
    lines.append("mutation score: " + ("n/a (no mutant tested anything)" if score is None else f"{score:.0%}")
                 + "  RESULT: " + ("every real mutant was caught" if r["ok"] else "blind spots found")
                 + (f"  ({len(r['blind_spots'])} field(s) no grader checks)" if auto and r["blind_spots"] else ""))
    return "\n".join(lines)
