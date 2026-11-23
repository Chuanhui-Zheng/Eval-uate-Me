"""Runs every case through the target, then the graders."""
from __future__ import annotations

import inspect
import json
import os
import random
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from . import registry
from .config import Config, ConfigError, load_cases, suggest
from .graders import ROLES, attach_judge_cache
from .judges import JudgeCache
from .dataset_meta import resolve_meta
from .isolation import wrap_target
from .execution import (ExecPolicy, OutputCache, RateLimiter, call_target, call_target_async, is_async, run_async,
                        run_threaded)
from .manifest import build_manifest, sha256_file
from .splits import record_heldout_look, select
from .privacy import enforce_local_only, redact_result, warn_if_data_leaves
from . import report_html
from .formats import check_version, read_json
from .models import FORMAT_VERSION, Case, CaseResult, Score, TargetOutput
from .stats import bootstrap_ci, mean, pass_at_k


def _run_case(target, graders, case: Case, attempt: int = 0, policy: ExecPolicy | None = None) -> CaseResult:
    return _grade(graders, case, call_target(target, case, attempt, policy or ExecPolicy()), attempt)


async def _run_case_async(target, graders, case: Case, attempt: int, policy: ExecPolicy) -> CaseResult:
    import asyncio
    out = await call_target_async(target, case, attempt, policy)
    return await asyncio.to_thread(_grade, graders, case, out, attempt)  # graders may block (e.g. a judge call)


def _grade(graders, case: Case, out: TargetOutput, attempt: int) -> CaseResult:
    scores: list[Score] = []
    if out.error is None:
        for g in graders:
            role = getattr(g, "role", "required")
            try:
                sc = g.grade(case, out)
            except Exception as e:
                sc = Score(getattr(g, "name", "grader"), 0.0, False, f"grader error: {type(e).__name__}: {e}")
            sc.role = role
            scores.append(sc)
    return CaseResult(case, out, scores, attempt)


def per_case_outcomes(results: list[CaseResult]) -> dict[str, list[bool]]:
    outcomes: dict[str, list[bool]] = {}
    for r in results:
        outcomes.setdefault(r.case.id, []).append(r.passed)
    return outcomes


def case_tags(case: Case) -> list[str]:
    """Tags come from metadata.tags (list) and/or metadata.category (string)."""
    tags = list(case.metadata.get("tags", []))
    if case.metadata.get("category"):
        tags.append(str(case.metadata["category"]))
    return [str(t) for t in tags]


def failure_reasons(r: CaseResult) -> list[str]:
    """Why an attempt failed: a target error, a grader that crashed, or each failing grader by name."""
    if r.passed:
        return []
    if r.result.error is not None:
        return ["target_error"]
    reasons = [("grader_error" if s.reason.startswith("grader error") else f"failed:{s.grader}")
               for s in r.scores if not s.passed and s.role == "required"]
    return reasons or ["no_graders"]


def summarize(results: list[CaseResult], name: str, planned: int | None = None) -> dict:
    outcomes = per_case_outcomes(results)
    n = len(results)
    passed = sum(r.passed for r in results)
    rates = [mean([float(x) for x in v]) for v in outcomes.values()]
    repeats = max((len(v) for v in outcomes.values()), default=1)

    # Target errors (outage, timeout, crash) say nothing about answer quality, so also report the
    # pass rate over attempts that actually produced an answer.
    answered_outcomes: dict[str, list[bool]] = {}
    for r in results:
        if r.result.error is None:
            answered_outcomes.setdefault(r.case.id, []).append(r.passed)
    answered_rates = [mean([float(x) for x in v]) for v in answered_outcomes.values()]

    by_grader: dict[str, list[float]] = {}
    for r in results:
        for s in r.scores:
            by_grader.setdefault(s.grader, []).append(s.value)
    lat = sorted(r.result.latency_s for r in results)
    usage: dict[str, float] = {}
    for r in results:
        for k, v in r.result.usage.items():
            usage[k] = usage.get(k, 0.0) + v

    tag_rates: dict[str, dict[str, list[float]]] = {}
    for r in results:
        for t in case_tags(r.case):
            tag_rates.setdefault(t, {}).setdefault(r.case.id, []).append(float(r.passed))
    advisory: dict[str, int] = {}
    for r in results:
        for sc in r.scores:
            if sc.role == "advisory" and not sc.passed:
                advisory[sc.grader] = advisory.get(sc.grader, 0) + 1
    reasons: dict[str, int] = {}
    for r in results:
        for why in failure_reasons(r):
            reasons[why] = reasons.get(why, 0) + 1

    summary = {
        "format_version": FORMAT_VERSION,
        "name": name,
        "cases": len(outcomes),
        "repeats": repeats,
        "total": n,
        "planned": planned if planned is not None else n,
        "incomplete": (planned - n) if planned is not None else 0,
        "passed": passed,
        "failed": n - passed,
        "errors": sum(r.result.error is not None for r in results),
        "pass_rate": mean(rates),
        "pass_rate_ci95": list(bootstrap_ci(rates)),
        "error_rate": (sum(r.result.error is not None for r in results) / n) if n else 0.0,
        "cases_answered": len(answered_outcomes),
        "pass_rate_answered": mean(answered_rates),
        "pass_rate_answered_ci95": list(bootstrap_ci(answered_rates)),
        "mean_score_by_grader": {k: mean(v) for k, v in by_grader.items()},
        "by_tag": {t: {"cases": len(c), "pass_rate": mean([mean(v) for v in c.values()])}
                   for t, c in sorted(tag_rates.items())},
        "failure_reasons": reasons,
        "advisory_failures": advisory,
        "retried": sum(r.result.retries > 0 for r in results),
        "usage_total": usage,
        "latency_p50_s": lat[n // 2] if n else 0.0,
        "latency_max_s": lat[-1] if n else 0.0,
    }
    summary["judge_cost_usd"] = sum(sc.cost_usd for r in results for sc in r.scores)
    dims: dict[str, dict[str, list[float]]] = {}
    for r in results:
        for sc in r.scores:
            for d, v in (sc.detail.get("dimensions") or {}).items():
                dims.setdefault(sc.grader, {}).setdefault(d, []).append(v)
    if dims:
        summary["dimension_means"] = {g: {d: mean(v) for d, v in per.items()} for g, per in dims.items()}
    if repeats > 1:
        summary["pass_at_1"] = mean([pass_at_k(len(v), sum(v), 1) for v in outcomes.values()])
        summary[f"pass_at_{repeats}"] = mean([pass_at_k(len(v), sum(v), repeats) for v in outcomes.values() if len(v) == repeats])
        summary["pass_all"] = mean([float(all(v)) for v in outcomes.values()])
        summary["flaky"] = sorted(k for k, v in outcomes.items() if 0 < sum(v) < len(v))
    return summary


def _new_run_dir(root: Path, name: str) -> Path:
    """Create a fresh run directory; never reuse one (two runs in the same second must not overwrite)."""
    root.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "run"  # a name like "a/b" must not become a path
    base = f"{safe}-{datetime.now():%Y%m%d-%H%M%S}"
    for i in range(1000):
        d = root / (base if i == 0 else f"{base}-{i}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError(f"could not create a run directory under {root}")


def load_plugins(cfg: Config) -> None:
    # A Python target's import paths may also contain its grader/plugin package.
    # Make them available before importing configured plugins, not only later in
    # PythonTarget.__init__, so `check` and `run` work without a manual PYTHONPATH.
    paths = cfg.target.get("paths", [])
    if isinstance(paths, list):
        for path in reversed(paths):
            if isinstance(path, str) and path and path not in sys.path:
                sys.path.insert(0, path)
    registry.load_entry_points()
    registry.load_modules(cfg.plugins)


_KIND_KEY = {"target": "targets", "grader": "graders", "judge": "judges"}


def _make(kind: str, spec: dict, label: str):
    """Instantiate a plugin from its config table, turning mistakes into readable ConfigErrors."""
    spec = dict(spec)
    typ = spec.pop("type")
    names = registry.available()[_KIND_KEY[kind]]
    if typ not in names:
        why = registry.LOAD_ERRORS.get(f"{kind} '{typ}'")
        raise ConfigError(f"{label}: unknown {kind} type '{typ}'.{suggest(typ, names)} Available: {', '.join(names)}"
                          + (f". The plugin that provides it failed to load: {why}" if why else ""))
    params = inspect.signature(registry.factory(kind, typ)).parameters
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        for k in spec:
            if k not in params:
                raise ConfigError(f"{label}: {kind} '{typ}' has no option '{k}'.{suggest(k, params)} "
                                  f"Options: {', '.join(params) or '(none)'}")
    missing = [n for n, p in params.items() if p.default is inspect.Parameter.empty
               and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY) and n not in spec]
    if missing:
        raise ConfigError(f"{label}: {kind} '{typ}' needs option(s): {', '.join(missing)}")
    try:
        return registry.get(kind, typ, **spec)
    except ConfigError:
        raise
    except (KeyError, TypeError) as e:
        raise ConfigError(f"{label}: {e}") from e
    except Exception as e:  # e.g. a missing data file: say what failed, not a traceback
        raise ConfigError(f"{label}: could not create {kind} '{typ}': {type(e).__name__}: {e}") from e


def build_target(cfg: Config):
    return _make("target", cfg.target, "[target]")


def build_graders(cfg: Config) -> list:
    graders = []
    for n, g in enumerate(cfg.graders, 1):
        g = dict(g)
        role = g.pop("role", "required")
        label = f"[[graders]] #{n} ({g['type']})"
        if role not in ROLES:
            raise ConfigError(f"{label}: role must be one of {ROLES}, got {role!r}")
        grader = _make("grader", g, label)
        grader.role = role
        graders.append(grader)
    if graders and not any(g.role == "required" for g in graders):
        raise ConfigError("at least one grader must have role = \"required\" (otherwise nothing can fail)")
    return graders


class RunInterrupted(Exception):
    """Raised on Ctrl-C. Finished results are already on disk and the run can be resumed."""

    def __init__(self, out_dir: Path, completed: int, planned: int):
        super().__init__(f"interrupted after {completed}/{planned} jobs")
        self.out_dir, self.completed, self.planned = out_dir, completed, planned


class ResumeMismatch(Exception):
    pass


def _read_results(path: Path) -> dict[tuple[str, int], CaseResult]:
    """Load a results file; if a job appears twice the later line wins."""
    out: dict[tuple[str, int], CaseResult] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = CaseResult.from_dict(check_version(json.loads(line), path))
                out[(r.case.id, r.attempt)] = r
    return out


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written file


def run(cfg: Config, resume: Path | None = None, retry_errors: bool = False,
        force: bool = False, split: str | None = None) -> tuple[list[CaseResult], dict, Path]:
    """Run an eval. Each finished job is appended to results.jsonl immediately, so an interrupted run
    keeps its work; pass `resume=<run dir>` to run only the jobs that are missing."""
    started = datetime.now()
    if cfg.seed is not None:
        random.seed(cfg.seed)
    load_plugins(cfg)
    cases = load_cases(cfg.dataset)
    resolve_meta(cfg.dataset, cfg.dataset_meta)  # raises ConfigError on a malformed file, before anything is created
    splits_in_use = cfg.split_dev_fraction is not None or any("split" in c.metadata for c in cases)
    if split is None:  # when splits exist, the safe default is the dev split, never silently the held-out one
        split = "dev" if splits_in_use else "all"
        if splits_in_use:
            print("running the dev split (use --split heldout for the final held-out number, or --split all)",
                  file=sys.stderr)
    cases = select(cases, split, cfg.split_dev_fraction, cfg.split_salt)
    real_target = build_target(cfg)
    target = wrap_target(cfg, real_target, cfg.target)
    graders = build_graders(cfg)
    notes = enforce_local_only(real_target, graders) if cfg.local_only else []
    if cfg.privacy_store == "scores_only":
        notes += warn_if_data_leaves(real_target, graders)
    if cfg.judge_cache:
        attach_judge_cache(graders, JudgeCache(cfg.output_dir / ".judge_cache"))
    for n in notes:
        print(f"privacy warning: {n}", file=sys.stderr)

    policy = ExecPolicy(
        retries=cfg.retries, retry_delay_s=cfg.retry_delay_s, limiter=RateLimiter(cfg.max_per_second),
        cache=OutputCache(cfg.output_dir / ".cache", cfg.target) if cfg.cache else None, timeout_s=cfg.timeout_s)
    jobs = [(c, a) for c in cases for a in range(cfg.repeats)]
    keys = [(c.id, a) for c, a in jobs]

    done: dict[tuple[str, int], CaseResult] = {}
    prior: dict = {}
    if resume is not None:
        out_dir = Path(resume)
        mf = out_dir / "manifest.json"
        if not mf.exists():
            raise ResumeMismatch(f"{out_dir} has no manifest.json; is it a run directory?")
        prior = read_json(mf)
        if not force and prior.get("split", "all") != split:
            raise ResumeMismatch(f"this run used the '{prior.get('split', 'all')}' split but you asked for '{split}'")
        if not force and (prior.get("config_sha256") != cfg.config_sha256
                          or prior.get("dataset_sha256") != sha256_file(cfg.dataset)):
            raise ResumeMismatch("config or dataset changed since this run started; resuming would mix "
                                 "results from different evals (use --force to override)")
        done = _read_results(out_dir / "results.jsonl")
        if retry_errors:
            done = {k: r for k, r in done.items() if r.result.error is None}
        started = datetime.fromisoformat(prior["started_at"]) if prior.get("started_at") else started
    else:
        out_dir = _new_run_dir(cfg.output_dir, cfg.name)
    resumes = prior.get("resumes", 0) + (1 if resume is not None else 0)

    # A "look" is a run that includes held-out cases. Each extra look makes the held-out score less independent
    # of your tuning, so say how many there have been. This is an honesty aid, not enforcement.
    looks = prior.get("heldout_looks", 0) if resume is not None else 0
    if resume is None and splits_in_use and split in ("heldout", "all"):
        looks = record_heldout_look(cfg.output_dir, cfg.dataset, cfg.config_sha256, split, out_dir.name)

    def write_manifest(status: str, finished: datetime | None) -> None:
        m = build_manifest(cfg, len(cases), started, finished, status)
        m["resumes"] = resumes
        m["privacy"] = {"store": cfg.privacy_store, "local_only": cfg.local_only}
        m["split"] = split
        if looks:
            m["heldout_looks"] = looks
        _write_json(out_dir / "manifest.json", m)

    write_manifest("running", None)
    todo = [j for j, k in zip(jobs, keys) if k not in done]
    lock = threading.Lock()
    budget = cfg.max_cost_usd
    # Money already spent by earlier (resumed) jobs; cache hits cost nothing new.
    spent = sum(r.result.usage.get("cost_usd", 0.0) for r in done.values() if not r.result.cached)
    spent += sum(s.cost_usd for r in done.values() for s in r.scores)
    skipped = 0
    results_file = (out_dir / "results.jsonl").open("a", encoding="utf-8")

    def skip_for_budget() -> bool:
        nonlocal skipped
        with lock:
            if budget is not None and spent >= budget:
                skipped += 1  # budget reached: do not start new jobs (jobs already running still finish)
                return True
        return False

    def record(r: CaseResult) -> None:
        nonlocal spent
        if cfg.privacy_store == "scores_only":
            r = redact_result(r)  # before it is stored, summarised or printed
        with lock:
            if not r.result.cached:
                spent += r.result.usage.get("cost_usd", 0.0)
            spent += sum(s.cost_usd for s in r.scores)  # judge calls cost money too (0 for cached replies)
            done[(r.case.id, r.attempt)] = r
            results_file.write(json.dumps(r.to_dict(), ensure_ascii=False, default=str) + "\n")
            results_file.flush()

    def work(job: tuple[Case, int]) -> None:
        if not skip_for_budget():
            record(_run_case(target, graders, job[0], job[1], policy))

    async def awork(job: tuple[Case, int]) -> None:
        if not skip_for_budget():
            record(await _run_case_async(target, graders, job[0], job[1], policy))

    try:
        if is_async(target):
            run_async(todo, awork, cfg.concurrency)
        else:
            run_threaded(todo, work, cfg.concurrency)
    except KeyboardInterrupt:
        results_file.close()
        write_manifest("interrupted", datetime.now())
        raise RunInterrupted(out_dir, len(done), len(jobs)) from None
    results_file.close()

    results = [done[k] for k in keys if k in done]  # job order, regardless of completion order
    tmp = out_dir / "results.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, out_dir / "results.jsonl")

    summary = summarize(results, cfg.name, planned=len(jobs))
    summary["cost_usd_spent"] = spent
    summary["privacy_store"] = cfg.privacy_store
    summary["split"] = split
    if looks:
        summary["heldout_looks"] = looks
    if budget is not None:
        summary["max_cost_usd"] = budget
        summary["budget_exhausted"] = skipped > 0
        if spent == 0 and results:
            summary["budget_warning"] = "target reported no usage.cost_usd, so the budget could not be enforced"
    _write_json(out_dir / "summary.json", summary)
    write_manifest("incomplete" if summary["incomplete"] else "complete", datetime.now())
    report_html.write(out_dir)
    return results, summary, out_dir
