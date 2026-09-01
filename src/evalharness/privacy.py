"""Privacy controls for evaluating sensitive data.

  store = "scores_only"  results, reports and logs keep ids, verdicts, scores, latency and usage, but never
                         the case input, expected value, target output, trace, error text or grader reasons.
  local_only = true     refuse to run components that declare they send data off this machine.

Redaction happens as each result is produced, before it is written, summarised or printed, so no later stage
(console, results.jsonl, summary.json, report.html) can leak what was removed. Target and graders still see the
real data while they run; this controls what is *kept*, not what is *processed*.
"""
from __future__ import annotations

from .config import ConfigError
from .models import Case, CaseResult, Score, TargetOutput

STORE_MODES = ("full", "scores_only")
SAFE_METADATA = ("tags", "category", "human_pass")  # needed for slice breakdowns and calibration
REDACTED = "[redacted]"


def redact_result(r: CaseResult) -> CaseResult:
    case = Case(id=r.case.id, input=None, expected=None,
                metadata={k: v for k, v in r.case.metadata.items() if k in SAFE_METADATA})
    o = r.result
    out = TargetOutput(output=None, trace=[], error=REDACTED if o.error is not None else None,
                       latency_s=o.latency_s, usage=dict(o.usage), retries=o.retries, cached=o.cached)
    scores = []
    for s in r.scores:
        # keep the "grader error" marker so failure categories survive redaction
        reason = f"grader error {REDACTED}" if s.reason.startswith("grader error") else (REDACTED if s.reason else "")
        scores.append(Score(s.grader, s.value, s.passed, reason, s.role, s.cost_usd))  # detail dropped: it can quote content
    return CaseResult(case, out, scores, r.attempt)


def component_network(obj) -> bool | None:
    """True = sends data off-machine, False = stays local, None = unknown (e.g. an arbitrary command)."""
    return getattr(obj, "network", None)


def enforce_local_only(target, graders: list) -> list[str]:
    """Raise ConfigError if any component sends data off-machine; return warnings for opaque ones."""
    blockers, warnings = [], []
    for label, obj in [("target", target)] + [(f"grader '{g.name}'", g) for g in graders]:
        net = component_network(obj)
        if net is True:
            blockers.append(f"{label} sends data off this machine, which privacy.local_only forbids")
        elif net is None:
            warnings.append(f"{label} does not declare whether it uses the network; local_only cannot verify it")
    if blockers:
        raise ConfigError(blockers)
    return warnings


def warn_if_data_leaves(target, graders: list) -> list[str]:
    """For non-local runs: tell the user which components send case content elsewhere."""
    return [f"{label} sends case content off this machine"
            for label, obj in [("target", target)] + [(f"grader '{g.name}'", g) for g in graders]
            if component_network(obj) is True]
