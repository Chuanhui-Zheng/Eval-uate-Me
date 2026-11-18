"""Core data types. Kept domain-agnostic: input/expected/output are any JSON values."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, TypedDict


class TraceStep(TypedDict, total=False):
    """Recommended schema for a single entry in TargetOutput.trace.

    ``tool`` is required; all other fields are optional and domain-specific.
    LLM-call steps typically carry ``model``; tool-call steps carry domain fields
    (e.g. ``cve_id``, ``found``) alongside the tool name.  ``round`` identifies
    which iteration of a multi-turn loop the step belongs to.

    Plugins are free to add arbitrary extra keys.  Graders that inspect the trace
    should access only the keys they know about and ignore the rest.
    """
    tool: str          # e.g. "openrouter_chat_completion", "lookup_cve", "run_query"
    round: int | str   # loop iteration; "final" for the constrained-output turn
    model: str         # LLM model identifier (for LLM-call steps)
    found: bool        # whether a lookup hit the knowledge base

FORMAT_VERSION = 1  # version of the files eval_uate_me writes; see formats.py


@dataclass
class Case:
    id: str
    input: Any
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetOutput:
    output: Any = None
    trace: list[Any] = field(default_factory=list)  # optional intermediate steps
    error: str | None = None
    latency_s: float = 0.0
    usage: dict[str, float] = field(default_factory=dict)  # e.g. input_tokens, output_tokens, cost_usd
    retries: int = 0
    cached: bool = False  # served from the output cache (no new spend)


@dataclass
class Score:
    grader: str
    value: float  # 0.0 - 1.0
    passed: bool
    reason: str = ""
    role: str = "required"  # "required" decides pass/fail; "advisory" is reported but does not
    cost_usd: float = 0.0  # what grading this cost (e.g. an LLM judge's calls); 0 for a cached reply or an unpriced judge
    detail: dict[str, Any] = field(default_factory=dict)  # optional structure, e.g. per-dimension scores


@dataclass
class CaseResult:
    case: Case
    result: TargetOutput
    scores: list[Score]
    attempt: int = 0  # 0-based index when a case is repeated

    @property
    def passed(self) -> bool:
        required = [s for s in self.scores if s.role == "required"]
        return self.result.error is None and bool(required) and all(s.passed for s in required)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CaseResult":
        c = d["case"]
        case = Case(id=c["id"], input=c.get("input"), expected=c.get("expected"), metadata=c.get("metadata", {}))
        return cls(case, TargetOutput(**d["result"]), [Score(**s) for s in d["scores"]], d.get("attempt", 0))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passed"] = self.passed
        d["format_version"] = FORMAT_VERSION
        return d
