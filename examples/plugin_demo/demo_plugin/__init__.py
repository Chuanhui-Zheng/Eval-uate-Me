"""A toy plugin showing the full extension surface: one target and one grader.

The target is a stand-in for a real agent. It records tool calls in the trace and
usage in the output, so trace/cost graders work on it without special support.
"""
from __future__ import annotations

import re

from eval_uate_me import Grader, Score, Target, TargetOutput, register_grader, register_target

_OPS = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b, "/": lambda a, b: a / b}


@register_target("calculator")
class CalculatorTarget(Target):
    eval_uate_me_api = 1
    """Answers questions like "12 * 3". `bug_div_zero=true` simulates a regression for demos."""

    def __init__(self, bug_div_zero: bool = False):
        self.bug_div_zero = bug_div_zero

    def run(self, case):
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([-+*/])\s*(-?\d+(?:\.\d+)?)\s*", str(case.input))
        if not m:
            return TargetOutput(error=f"cannot parse {case.input!r}")
        a, op, b = float(m[1]), m[2], float(m[3])
        if op == "/" and b == 0:
            return TargetOutput(output=0.0 if self.bug_div_zero else "undefined",
                                trace=[{"tool": "calc", "args": [a, op, b]}], usage={"input_tokens": 12, "output_tokens": 3})
        return TargetOutput(output=_OPS[op](a, b), trace=[{"tool": "calc", "args": [a, op, b]}],
                            usage={"input_tokens": 12, "output_tokens": 3, "cost_usd": 0.00001})


@register_grader("numeric_close")
class NumericClose(Grader):
    eval_uate_me_api = 1
    name = "numeric_close"

    def __init__(self, tolerance: float = 1e-6):
        self.tolerance = tolerance

    def grade(self, case, out):
        try:
            ok = abs(float(out.output) - float(case.expected)) <= self.tolerance
        except (TypeError, ValueError):
            ok = out.output == case.expected  # non-numeric answers (e.g. "undefined") must match exactly
        return Score(self.name, 1.0 if ok else 0.0, ok, "" if ok else f"expected {case.expected!r}, got {out.output!r}")
