"""Tests: async."""
from helpers import *  # noqa: F401,F403


# ---- async targets and bounded submission ----


def test_async_target_runs_many_calls_concurrently_on_one_event_loop(tmp_path):
    import time
    GAUGE.now = GAUGE.peak = 0
    f = _async_cfg(tmp_path, run_extra="concurrency = 40\n")
    t0 = time.perf_counter()
    results, summary, _ = run(load_config(f))
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.5                                       # 40 calls x 0.2 s = 8 s if serial
    assert GAUGE.peak == 40                                    # all 40 were in flight at once
    assert [r.case.id for r in results] == [f"c{i}" for i in range(40)] and summary["passed"] == 40
    assert summary["usage_total"]["cost_usd"] == pytest.approx(0.4)


def test_async_concurrency_limit_is_respected(tmp_path):
    GAUGE.now = GAUGE.peak = 0
    results, _, _ = run(load_config(_async_cfg(tmp_path, 'type = "async_sleeper"\nseconds = 0.05', "concurrency = 5\n", n=30)))
    assert GAUGE.peak == 5 and len(results) == 30


def test_async_timeout_really_cancels_the_call(tmp_path):
    GAUGE.now = GAUGE.peak = 0
    f = _async_cfg(tmp_path, 'type = "async_sleeper"\nseconds = 5', "timeout_s = 0.3\nconcurrency = 3\n", n=3)
    results, summary, _ = run(load_config(f))
    assert all("timeout after 0.3s: the call was cancelled" in r.result.error for r in results)
    assert GAUGE.now == 0                                      # the coroutines were cancelled, not left running


def test_async_retries_cache_rate_limit_and_budget(tmp_path):
    import time
    calls = {"n": 0}

    @register_target("async_flaky_once")
    class AsyncFlaky(Target):
        network = False

        async def arun(self, case):
            calls["n"] += 1
            return TargetOutput(error="transient") if calls["n"] == 1 else TargetOutput(output=case.input, usage={"cost_usd": 1.0})

    f = _async_cfg(tmp_path, 'type = "async_flaky_once"', "retries = 2\nretry_delay_s = 0\nconcurrency = 1\ncache = true\n", n=3)
    r1 = run(load_config(f))[0]
    assert all(r.passed for r in r1) and r1[0].result.retries == 1 and calls["n"] == 4
    run(load_config(f))
    assert calls["n"] == 4                                     # second run served from the cache
    g = _async_cfg(tmp_path / "rl" if (tmp_path / "rl").mkdir() is None else tmp_path,
                   'type = "async_sleeper"\nseconds = 0', "max_per_second = 20\nconcurrency = 10\n", n=10)
    t0 = time.perf_counter()
    run(load_config(g))
    assert time.perf_counter() - t0 >= 0.4                     # 10 calls at 20/s
    h = _async_cfg(tmp_path / "bud" if (tmp_path / "bud").mkdir() is None else tmp_path,
                   'type = "async_sleeper"\nseconds = 0', "max_cost_usd = 0.025\nconcurrency = 1\n", n=10)
    _, summary, _ = run(load_config(h))
    assert summary["incomplete"] > 0 and summary["budget_exhausted"]


def test_async_interrupt_keeps_finished_work_and_resume_finishes(tmp_path, capsys):
    calls, armed = [], {"on": True}

    @register_target("async_interruptible")
    class AsyncInterruptible(Target):
        network = False

        async def arun(self, case):
            calls.append(case.id)
            if armed["on"] and len(calls) == 3:
                raise KeyboardInterrupt
            return TargetOutput(output=case.input)

    f = _async_cfg(tmp_path, 'type = "async_interruptible"', "concurrency = 1\n", n=6)
    assert main(["run", str(f)]) == 130
    d = next((tmp_path / "runs").iterdir())
    saved = {json.loads(l)["case"]["id"] for l in (d / "results.jsonl").read_text().splitlines()}
    assert {"c0", "c1"} <= saved and "c2" not in saved
    calls.clear()
    armed["on"] = False                                          # the second run is not interrupted
    results, summary, _ = run(load_config(f), resume=d)
    assert sorted(calls) == sorted({f"c{i}" for i in range(6)} - saved) and summary["passed"] == 6


def test_async_only_target_works_with_sync_executors_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", TESTS_DIR)
    import iso_targets  # noqa: F401
    f = _async_cfg(tmp_path, 'type = "iso_async_only"', 'concurrency = 2\n', n=4)
    f.write_text('plugins = ["iso_targets"]\n' + f.read_text())
    assert all(r.passed for r in run(load_config(f))[0])                  # async executor
    iso = tmp_path / "iso"
    iso.mkdir()
    g = _async_cfg(iso, 'type = "iso_async_only"', 'isolation = "process"\n', n=2)
    g.write_text('plugins = ["iso_targets"]\n' + g.read_text())
    assert all(r.passed for r in run(load_config(g))[0])                  # worker process uses the run() fallback
    from evalharness.targets import Target as T

    class Neither(T):
        pass

    with pytest.raises(NotImplementedError, match="run\\(case\\) or async arun"):
        Neither().run(Case("a", "q"))


def test_async_target_with_privacy_mode(tmp_path):
    f = _async_cfg(tmp_path, run_extra='[privacy]\nstore = "scores_only"\n', n=3)
    results, summary, d = run(load_config(f))
    assert all(r.case.input is None for r in results) and summary["privacy_store"] == "scores_only"


def test_threaded_submission_is_bounded(tmp_path):
    """A huge dataset must not become a huge number of pending futures."""
    import threading
    import time
    from evalharness.execution import run_threaded
    consumed, finished, worst = {"n": 0}, {"n": 0}, {"gap": 0}
    lock = threading.Lock()

    def jobs():
        for i in range(2000):
            with lock:
                consumed["n"] += 1
                worst["gap"] = max(worst["gap"], consumed["n"] - finished["n"])
            yield i

    def work(_):
        time.sleep(0.0005)
        with lock:
            finished["n"] += 1

    run_threaded(jobs(), work, workers=4)
    assert finished["n"] == 2000 and worst["gap"] <= 4 * 4 + 2        # window = 4 workers x 4, plus the one being created
