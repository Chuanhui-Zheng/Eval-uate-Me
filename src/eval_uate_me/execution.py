"""Execution policy around a target call: rate limiting, retries, and an output cache."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .models import Case, TargetOutput


class RateLimiter:
    """Allows at most `per_second` calls per second across all threads."""

    def __init__(self, per_second: float | None):
        self.interval = 1.0 / per_second if per_second else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            time.sleep(slot - now)


class OutputCache:
    """On-disk cache of successful target outputs, keyed by target spec + case input + attempt.
    Re-running with only grader changes then costs nothing. Errors are never cached."""

    def __init__(self, directory: Path, target_spec: dict):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ns = json.dumps(target_spec, sort_keys=True, default=str)

    def _path(self, case: Case, attempt: int) -> Path:
        raw = json.dumps([self.ns, case.id, case.input, case.expected, case.metadata, attempt],
                         sort_keys=True, default=str)
        return self.dir / (hashlib.sha256(raw.encode()).hexdigest() + ".json")

    def get(self, case: Case, attempt: int) -> TargetOutput | None:
        p = self._path(case, attempt)
        if not p.exists():
            return None
        try:
            return TargetOutput(**json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            return None  # corrupt entry: treat as a miss

    def put(self, case: Case, attempt: int, out: TargetOutput) -> None:
        if out.error is None:
            self._path(case, attempt).write_text(json.dumps(asdict(out), default=str), encoding="utf-8")


@dataclass
class ExecPolicy:
    retries: int = 0
    retry_delay_s: float = 1.0
    limiter: RateLimiter | None = None
    cache: OutputCache | None = None
    timeout_s: float | None = None  # enforced (by cancelling the coroutine) for async targets
    sleep: Callable[[float], None] = time.sleep  # injectable for tests


def call_target(target, case: Case, attempt: int, policy: ExecPolicy) -> TargetOutput:
    if policy.cache and (hit := policy.cache.get(case, attempt)) is not None:
        hit.cached = True
        return hit
    out = TargetOutput(error="not run")
    for n in range(policy.retries + 1):
        if policy.limiter:
            policy.limiter.wait()
        start = time.perf_counter()
        try:
            out = target.run(case)
        except Exception as e:  # a crashing target is a failed case, not a crashed run
            out = TargetOutput(error=f"{type(e).__name__}: {e}")
        out.latency_s = time.perf_counter() - start
        out.retries = n
        if out.error is None:
            break
        if n < policy.retries:
            policy.sleep(policy.retry_delay_s * 2 ** n)
    if policy.cache:
        policy.cache.put(case, attempt, out)
    return out



def is_async(target) -> bool:
    return inspect.iscoroutinefunction(getattr(target, "arun", None))


async def call_target_async(target, case: Case, attempt: int, policy: ExecPolicy) -> TargetOutput:
    """Async twin of call_target: same cache, rate limit, retries and error handling, with a real timeout."""
    if policy.cache:
        hit = await asyncio.to_thread(policy.cache.get, case, attempt)
        if hit is not None:
            hit.cached = True
            return hit
    out = TargetOutput(error="not run")
    for n in range(policy.retries + 1):
        if policy.limiter:
            await asyncio.to_thread(policy.limiter.wait)  # the limiter sleeps; keep that off the event loop
        start = time.perf_counter()
        try:
            out = await asyncio.wait_for(target.arun(case), policy.timeout_s)
        except asyncio.TimeoutError:
            out = TargetOutput(error=f"timeout after {policy.timeout_s}s: the call was cancelled")
        except Exception as e:  # noqa: BLE001
            out = TargetOutput(error=f"{type(e).__name__}: {e}")
        out.latency_s = time.perf_counter() - start
        out.retries = n
        if out.error is None:
            break
        if n < policy.retries:
            await asyncio.sleep(policy.retry_delay_s * 2 ** n)
    if policy.cache:
        await asyncio.to_thread(policy.cache.put, case, attempt, out)
    return out


def run_threaded(jobs, work, workers: int) -> None:
    """Run work(job) for every job on a thread pool, keeping only a small window of jobs submitted at once so a huge
    dataset does not create a huge number of pending futures."""
    window = max(workers * 4, 8)
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    it, pending = iter(jobs), set()
    try:
        while True:
            for j in it:
                pending.add(pool.submit(work, j))
                if len(pending) >= window:
                    break
            if not pending:
                break
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in finished:
                f.result()
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()


def run_async(jobs, awork, concurrency: int) -> None:
    """Run `await awork(job)` for every job on one event loop, at most `concurrency` at a time."""
    async def main() -> None:
        sem = asyncio.Semaphore(max(1, concurrency))
        window = max(concurrency * 4, 8)

        async def one(j):
            async with sem:
                await awork(j)

        it, pending = iter(jobs), set()
        while True:
            for j in it:
                pending.add(asyncio.ensure_future(one(j)))
                if len(pending) >= window:
                    break
            if not pending:
                break
            finished, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in finished:
                t.result()

    asyncio.run(main())
