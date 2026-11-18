"""Run evals from Python (a notebook, a script, a test) without a config file.

    from eval_uate_me import evaluate

    result = evaluate(my_function, cases=[{"input": "2+2", "expected": "4"}, ("3+3", "6")])
    result.pass_rate            # 1.0
    result.failures()           # the CaseResults that failed
    result.to_rows()            # flat dicts, ready for a table or a DataFrame

`evaluate` works in memory (nothing is written to disk). `run_eval("eval.toml")` runs a config exactly as the command line does
and returns the same kind of result, with the run directory. Both are part of the stable API.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import registry
from .adapters import PythonTarget
from .config import Config, ConfigError, load_config
from .execution import ExecPolicy, is_async, run_async, run_threaded
from .graders import ExactMatch, Grader
from .models import Case, CaseResult, FORMAT_VERSION, Score, TargetOutput
from .runner import _grade, _run_case, _run_case_async, run, summarize
from .targets import Target


@dataclass
class EvalResult:
    """What an evaluation produced. `run_dir` is None for in-memory runs."""
    results: list[CaseResult]
    summary: dict[str, Any]
    run_dir: Path | None = None
    _rows: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @property
    def pass_rate(self) -> float:
        return float(self.summary["pass_rate"])

    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed]

    def to_rows(self) -> list[dict[str, Any]]:
        """One flat dict per attempt: case_id, attempt, passed, error, latency_s, input, expected, output and one
        `score:<grader>` column per grader."""
        rows = []
        for r in self.results:
            row: dict[str, Any] = {"case_id": r.case.id, "attempt": r.attempt, "passed": r.passed, "error": r.result.error,
                                   "latency_s": r.result.latency_s, "input": r.case.input, "expected": r.case.expected,
                                   "output": r.result.output}
            row.update({f"score:{s.grader}": s.value for s in r.scores})
            rows.append(row)
        return rows


class _FunctionTarget(Target):
    eval_uate_me_api = 1

    def __init__(self, fn: Callable[..., Any]):
        self.fn = fn
        if inspect.iscoroutinefunction(fn):
            self.arun = self._arun

    def run(self, case: Case) -> TargetOutput:
        if inspect.iscoroutinefunction(self.fn):
            import asyncio
            return asyncio.run(self._arun(case))
        v = self.fn(case.input)
        return v if isinstance(v, TargetOutput) else TargetOutput(output=v)

    async def _arun(self, case: Case) -> TargetOutput:
        v = await self.fn(case.input)
        return v if isinstance(v, TargetOutput) else TargetOutput(output=v)


class _FunctionGrader(Grader):
    eval_uate_me_api = 1

    def __init__(self, fn: Callable[[Case, TargetOutput], Any]):
        self.fn, self.name = fn, getattr(fn, "__name__", "function_grader")

    def grade(self, case: Case, out: TargetOutput) -> Score:
        v = self.fn(case, out)
        if isinstance(v, Score):
            return v
        if isinstance(v, bool):
            return Score(self.name, 1.0 if v else 0.0, v, "" if v else "returned False")
        raise TypeError(f"grader function '{self.name}' must return a bool or a Score, got {type(v).__name__}")


def _target(t: Any) -> Target:
    if isinstance(t, Target):
        return t
    if isinstance(t, str):
        return PythonTarget(callable=t)
    if callable(t):
        return _FunctionTarget(t)
    raise TypeError("target must be a Target, a function, or a 'module:function' string")


def _case(c: Any, n: int) -> Case:
    if isinstance(c, Case):
        return c
    if isinstance(c, dict):
        return Case(id=str(c.get("id", f"case-{n}")), input=c.get("input"), expected=c.get("expected"), metadata=dict(c.get("metadata", {})))
    if isinstance(c, (tuple, list)) and len(c) in (1, 2):
        return Case(id=f"case-{n}", input=c[0], expected=c[1] if len(c) == 2 else None)
    raise TypeError("a case must be a Case, a dict, or an (input, expected) tuple")


def _grader(g: Any) -> Grader:
    if isinstance(g, Grader):
        return g
    if isinstance(g, str):
        return registry.get_grader(g)
    if isinstance(g, tuple) and len(g) == 2 and isinstance(g[0], str) and isinstance(g[1], dict):
        return registry.get_grader(g[0], **g[1])
    if callable(g):
        return _FunctionGrader(g)
    raise TypeError("a grader must be a Grader, a registered name, a (name, options) tuple, or a function(case, output) -> bool")


def evaluate(target: Any, cases: Iterable[Any], graders: Iterable[Any] | None = None, *, repeats: int = 1, concurrency: int = 4,
             retries: int = 0, timeout_s: float | None = None, name: str = "eval") -> EvalResult:
    """Run `target` over `cases` and grade each answer, in memory.

    target   a Target, a function(input) -> output (sync or async), or "module:function"
    cases    Case objects, dicts {id?, input, expected?, metadata?}, or (input, expected) tuples
    graders  Grader objects, registered names ("exact_match"), (name, {options}) tuples, or function(case, output) -> bool;
             default: exact_match
    """
    tgt = _target(target)
    case_list = [_case(c, n) for n, c in enumerate(cases, 1)]
    if not case_list:
        raise ConfigError("evaluate() needs at least one case")
    ids = [c.id for c in case_list]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    grader_list = [_grader(g) for g in (graders if graders is not None else [ExactMatch()])]
    policy = ExecPolicy(retries=retries, retry_delay_s=0.0 if retries else 1.0, timeout_s=timeout_s)
    jobs = [(c, a) for c in case_list for a in range(max(1, repeats))]
    done: dict[tuple[str, int], CaseResult] = {}

    def work(job: tuple[Case, int]) -> None:
        r = _run_case(tgt, grader_list, job[0], job[1], policy)
        done[(r.case.id, r.attempt)] = r

    async def awork(job: tuple[Case, int]) -> None:
        r = await _run_case_async(tgt, grader_list, job[0], job[1], policy)
        done[(r.case.id, r.attempt)] = r

    if is_async(tgt):
        run_async(jobs, awork, concurrency)
    else:
        run_threaded(jobs, work, concurrency)
    results = [done[(c.id, a)] for c, a in jobs]
    summary = summarize(results, name, planned=len(jobs))
    summary["cost_usd_spent"] = sum(r.result.usage.get("cost_usd", 0.0) for r in results)
    summary["format_version"] = FORMAT_VERSION
    return EvalResult(results, summary, None)


def run_eval(config: str | Path | Config, *, split: str | None = None, resume: str | Path | None = None,
             retry_errors: bool = False, force: bool = False) -> EvalResult:
    """Run an eval from a config file exactly as `eval_uate_me run` does (the run directory is written) and return the result."""
    cfg = config if isinstance(config, Config) else load_config(config)
    results, summary, run_dir = run(cfg, resume=Path(resume) if resume else None, retry_errors=retry_errors, force=force, split=split)
    return EvalResult(results, summary, run_dir)
