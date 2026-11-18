"""Targets: the thing under test. A target turns a Case into a TargetOutput."""
from __future__ import annotations

import json
import subprocess
from abc import ABC
from typing import Any

from .models import Case, TargetOutput
from .registry import register_target


class Target(ABC):
    """The system under test. Define `run(case)`, or `async def arun(case)` for a target that mostly waits on the network:
    the harness then keeps up to `run.concurrency` calls in flight on one event loop (hundreds are cheap), with real
    cancellation on `timeout_s`. A target that only defines `arun` still works everywhere (`run` falls back to it).
    """
    # True: sends case data off this machine. False: stays local. None: unknown (arbitrary code).
    # Declared by the plugin author; privacy.local_only refuses True and warns on None. It is a
    # declaration, not enforcement: a plugin that misreports it is not caught.
    network: bool | None = None

    def run(self, case: Case) -> TargetOutput:
        arun = getattr(self, "arun", None)
        if arun is None:
            raise NotImplementedError("a Target must define run(case) or async arun(case)")
        import asyncio
        return asyncio.run(arun(case))


@register_target("echo")
class EchoTarget(Target):
    """Returns the input unchanged. Useful for smoke-testing the harness."""
    network = False

    def run(self, case: Case) -> TargetOutput:
        return TargetOutput(output=case.input, trace=[{"step": "echo"}])


@register_target("command")
class CommandTarget(Target):
    """Runs an external command. Case input is sent as JSON on stdin; stdout is
    parsed as JSON if possible, otherwise kept as text. This lets any agent in any
    language be evaluated without writing Python."""

    def __init__(self, command: list[str] | str, timeout_s: float = 120):
        self.command = command
        self.timeout_s = timeout_s

    def run(self, case: Case) -> TargetOutput:
        shell = isinstance(self.command, str)
        try:
            proc = subprocess.run(
                self.command, input=json.dumps(case.input), capture_output=True,
                text=True, timeout=self.timeout_s, shell=shell,
            )
        except subprocess.TimeoutExpired:
            return TargetOutput(error=f"timeout after {self.timeout_s}s")
        if proc.returncode != 0:
            return TargetOutput(error=f"exit {proc.returncode}: {proc.stderr.strip()[:500]}")
        out: Any = proc.stdout.strip()
        try:
            out = json.loads(out)
        except json.JSONDecodeError:
            pass
        return TargetOutput(output=out, trace=[{"stderr": proc.stderr}] if proc.stderr else [])


@register_target("oracle")
class OracleTarget(Target):
    """Returns the reference answer. A perfect solver: an upper-bound baseline, and proof
    that every case is solvable and every grader accepts a correct answer."""
    network = False

    def run(self, case: Case) -> TargetOutput:
        return TargetOutput(output=case.expected, trace=[{"step": "oracle"}])


@register_target("null")
class NullTarget(Target):
    """Returns nothing. A do-nothing solver: a lower-bound baseline that should fail every case."""
    network = False

    def run(self, case: Case) -> TargetOutput:
        return TargetOutput(output=None)
