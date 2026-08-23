"""Validate the *evaluation* before trusting it, using baselines with known answers.

  oracle   returns the reference answer      -> every semantic grader should PASS it
  null     returns nothing                   -> every semantic grader should FAIL it
  shuffled returns another case's reference  -> plausible but wrong; should FAIL

A grader the oracle fails is too strict (or the reference data is wrong). A grader the null or
shuffled baseline passes is too lenient: it would also pass a bad agent. Cases that a baseline
passes on every semantic grader are trivially passable and carry no signal.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import Case, TargetOutput
from .runner import _run_case
from .targets import NullTarget, OracleTarget, Target

BAD_VERDICTS = ("too_strict", "too_lenient", "broken")


class _ShuffledTarget(Target):
    def __init__(self, wrong: dict[str, object]):
        self.wrong = wrong

    def run(self, case: Case) -> TargetOutput:
        return TargetOutput(output=self.wrong[case.id])


def wrong_cases(cases: list[Case]) -> dict[str, Case]:
    """For each case, the nearest other case whose reference differs (its 'wrong neighbour')."""
    out: dict[str, Case] = {}
    for i, c in enumerate(cases):
        for step in range(1, len(cases)):
            other = cases[(i + step) % len(cases)]
            if other.expected != c.expected:
                out[c.id] = other
                break
    return out


class _CrossInput(Target):
    """Run a real target on another case's input: a well-formed answer to the wrong question."""

    def __init__(self, target, neighbours: dict[str, Case]):
        self.target, self.neighbours = target, neighbours

    def run(self, case: Case) -> TargetOutput:
        other = self.neighbours[case.id]
        return self.target.run(Case(case.id, other.input, other.expected, other.metadata))


def wrong_answers(cases: list[Case]) -> dict[str, object]:
    """For each case, the reference answer of the nearest other case whose answer differs."""
    out: dict[str, object] = {}
    for i, c in enumerate(cases):
        for step in range(1, len(cases)):
            other = cases[(i + step) % len(cases)]
            if other.expected != c.expected:
                out[c.id] = other.expected
                break
    return out


@dataclass
class GraderVerdict:
    grader: str
    verdict: str  # ok | too_strict | too_lenient | broken | skipped
    oracle: float | None = None
    null: float | None = None
    shuffled: float | None = None
    note: str = ""


@dataclass
class SelfTestReport:
    cases_used: int
    cases_skipped: int
    verdicts: list[GraderVerdict] = field(default_factory=list)
    trivial_cases: dict[str, list[str]] = field(default_factory=dict)  # baseline -> case ids

    @property
    def ok(self) -> bool:
        return not any(v.verdict in BAD_VERDICTS for v in self.verdicts)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def _pass_rates(target, graders, cases: list[Case]):  # noqa: E302
    """Per-grader pass rate, plus ids of cases passed by every semantic grader."""
    results = [_run_case(target, graders, c) for c in cases]
    rates = []
    for i in range(len(graders)):
        passes = [(r.scores[i].passed if i < len(r.scores) else False) for r in results]
        rates.append(sum(passes) / len(passes) if passes else None)
    sem = [i for i, g in enumerate(graders) if g.semantic]
    trivial = [r.case.id for r in results
               if sem and all(i < len(r.scores) and r.scores[i].passed for i in sem)]
    return rates, trivial


def selftest(cases: list[Case], graders: list, min_oracle: float = 0.95, max_bad: float = 0.05,
             oracle_target=None) -> SelfTestReport:
    """`oracle_target`: a target that produces a perfect answer. Needed when the reference (`expected`) is a scoring
    spec rather than the output itself; it also supplies the 'shuffled' baseline (it answers another case's input)."""
    usable = [c for c in cases if c.expected is not None]
    report = SelfTestReport(cases_used=len(usable), cases_skipped=len(cases) - len(usable))
    if not usable:
        raise ValueError("no cases with an `expected` value; baselines need a reference answer")

    wrong = wrong_answers(usable)
    shuffled_cases = [c for c in usable if c.id in wrong]

    o_rates, _ = _pass_rates(oracle_target or OracleTarget(), graders, usable)
    n_rates, n_triv = _pass_rates(NullTarget(), graders, usable)
    if shuffled_cases:
        bad_target = (_CrossInput(oracle_target, wrong_cases(usable)) if oracle_target is not None
                      else _ShuffledTarget(wrong))
        s_rates, s_triv = _pass_rates(bad_target, graders, shuffled_cases)
    else:
        s_rates, s_triv = [None] * len(graders), []

    for i, g in enumerate(graders):
        mode = g.selftest or ("content" if g.semantic else "skip")
        if mode == "skip":
            report.verdicts.append(GraderVerdict(
                g.name, "skipped", note="checks behaviour (trace/cost/latency), not answer content"))
            continue
        if mode == "guardrail":
            strict_g = o_rates[i] is not None and o_rates[i] < min_oracle
            report.verdicts.append(GraderVerdict(
                g.name, "too_strict" if strict_g else "ok", o_rates[i], None, None,
                (f"oracle passes only {o_rates[i]:.0%}: the grader rejects correct answers, or references are wrong; "
                 if strict_g else "") + "guardrail: only the oracle is checked here; use meta-eval to test detection"))
            continue
        strict = o_rates[i] is not None and o_rates[i] < min_oracle
        lenient = any(r is not None and r > max_bad for r in (n_rates[i], s_rates[i]))
        verdict = "broken" if strict and lenient else "too_strict" if strict else "too_lenient" if lenient else "ok"
        notes = []
        if strict:
            notes.append(f"oracle passes only {o_rates[i]:.0%}: grader rejects correct answers, or references are wrong")
        if lenient:
            notes.append("passes wrong answers: would not catch a bad agent")
        if not shuffled_cases:
            notes.append("shuffled baseline not run (all references identical)")
        report.verdicts.append(GraderVerdict(g.name, verdict, o_rates[i], n_rates[i], s_rates[i], "; ".join(notes)))

    report.trivial_cases = {k: v for k, v in (("null", n_triv), ("shuffled", s_triv)) if v}
    return report


def format_report(r: SelfTestReport) -> str:
    def pct(x):
        return "  -  " if x is None else f"{x:4.0%}"

    lines = [f"selftest: {r.cases_used} cases with references ({r.cases_skipped} skipped: no `expected`)",
             f"{'grader':<16}{'oracle':>8}{'null':>8}{'shuffled':>10}  verdict"]
    for v in r.verdicts:
        lines.append(f"{v.grader:<16}{pct(v.oracle):>8}{pct(v.null):>8}{pct(v.shuffled):>10}  {v.verdict}"
                     + (f"  ({v.note})" if v.note else ""))
    for name, ids in r.trivial_cases.items():
        lines.append(f"trivially passable by '{name}' baseline ({len(ids)}): {ids[:10]}{' ...' if len(ids) > 10 else ''}")
    lines.append("RESULT: " + ("ok" if r.ok else "problems found"))
    return "\n".join(lines)
