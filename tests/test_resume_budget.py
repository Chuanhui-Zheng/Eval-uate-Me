"""Tests: resume budget."""
from helpers import *  # noqa: F401,F403


# ---- incremental results and resume ----


def test_interrupt_keeps_finished_work_and_resume_runs_only_the_rest(tmp_path, capsys):
    calls = []
    _counting_target("interruptible", calls, boom_on=3)
    cases = [{"id": str(i), "input": str(i), "expected": str(i)} for i in range(5)]
    f = write_eval(tmp_path, cases, target='type = "interruptible"')
    f.write_text(f.read_text() + "concurrency = 1\n")

    assert main(["run", str(f)]) == 130                     # Ctrl-C style stop
    run_dir = next((tmp_path / "runs").iterdir())
    assert json.loads((run_dir / "manifest.json").read_text())["status"] == "interrupted"
    saved = {json.loads(l)["case"]["id"] for l in (run_dir / "results.jsonl").read_text().splitlines()}
    assert {"0", "1"} <= saved and "2" not in saved          # finished work kept, interrupted job not saved
    assert "resume with" in capsys.readouterr().err         # (a queued job may also finish before cancellation)

    calls.clear()
    results, summary, out = run(load_config(f), resume=run_dir)
    assert out == run_dir and sorted(calls) == sorted({"0", "1", "2", "3", "4"} - saved)   # only missing jobs ran
    assert [r.case.id for r in results] == ["0", "1", "2", "3", "4"] and summary["passed"] == 5
    m = json.loads((run_dir / "manifest.json").read_text())
    assert m["status"] == "complete" and m["resumes"] == 1
    assert len((run_dir / "results.jsonl").read_text().splitlines()) == 5   # no duplicates


def test_resume_refuses_changed_dataset_unless_forced(tmp_path, capsys):
    calls = []
    _counting_target("steady", calls)
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}], target='type = "steady"')
    _, _, run_dir = run(load_config(f))
    (tmp_path / "c.jsonl").write_text(json.dumps({"id": "1", "input": "b", "expected": "b"}))
    assert main(["run", str(f), "--resume", str(run_dir)]) == 2
    assert "changed" in capsys.readouterr().err
    assert main(["run", str(f), "--resume", str(run_dir), "--force"]) == 0


def test_resume_retry_errors_reruns_only_errored_jobs(tmp_path):
    state = {"fail": True, "calls": []}

    @register_target("recovering")
    class Recovering(Target):
        def run(self, case):
            state["calls"].append(case.id)
            return TargetOutput(error="down") if state["fail"] and case.id == "bad" else TargetOutput(output=case.input)

    cases = [{"id": "ok", "input": "a", "expected": "a"}, {"id": "bad", "input": "b", "expected": "b"}]
    f = write_eval(tmp_path, cases, target='type = "recovering"')
    _, summary, run_dir = run(load_config(f))
    assert summary["errors"] == 1
    state.update(fail=False, calls=[])
    results, summary, _ = run(load_config(f), resume=run_dir, retry_errors=True)
    assert state["calls"] == ["bad"] and summary["errors"] == 0 and summary["passed"] == 2
    assert len((run_dir / "results.jsonl").read_text().splitlines()) == 2


def test_resume_on_complete_run_is_a_noop_and_needs_manifest(tmp_path):
    calls = []
    _counting_target("noop", calls)
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}], target='type = "noop"')
    _, _, run_dir = run(load_config(f))
    calls.clear()
    run(load_config(f), resume=run_dir)
    assert calls == []
    from eval_uate_me.runner import ResumeMismatch
    with pytest.raises(ResumeMismatch):
        run(load_config(f), resume=tmp_path)


# ---- cost budget ----


def test_budget_stops_new_jobs_and_resume_finishes(tmp_path, capsys):
    calls = []
    _costly_target("pricey", calls)
    f = _budget_cfg(tmp_path, "pricey", "max_cost_usd = 2.5\n")
    assert main(["run", str(f)]) == 3                          # exit 3 = incomplete
    run_dir = next((tmp_path / "runs").iterdir())
    s = json.loads((run_dir / "summary.json").read_text())
    assert calls == ["0", "1", "2"] and s["incomplete"] == 2 and s["budget_exhausted"] is True
    assert s["cost_usd_spent"] == 3.0 and json.loads((run_dir / "manifest.json").read_text())["status"] == "incomplete"
    err = capsys.readouterr()
    assert "INCOMPLETE" in err.out and "--max-cost" in err.err

    calls.clear()
    assert main(["run", str(f), "--resume", str(run_dir), "--max-cost", "100"]) == 0
    assert calls == ["3", "4"]                                  # only the jobs the budget skipped
    s = json.loads((run_dir / "summary.json").read_text())
    assert s["incomplete"] == 0 and s["passed"] == 5 and s["cost_usd_spent"] == 5.0


def test_cached_results_do_not_spend_budget(tmp_path):
    calls = []
    _costly_target("cheapcache", calls)
    f = _budget_cfg(tmp_path, "cheapcache", "cache = true\n")
    run(load_config(f))
    cfg = load_config(f)
    cfg.max_cost_usd = 0.5
    results, summary, _ = run(cfg)
    assert len(results) == 5 and summary["incomplete"] == 0 and summary["cost_usd_spent"] == 0.0


def test_budget_warns_when_target_reports_no_cost(tmp_path):
    calls = []
    _costly_target("freebie", calls, cost=0)
    f = _budget_cfg(tmp_path, "freebie", "max_cost_usd = 1\n")
    _, summary, _ = run(load_config(f))
    assert summary["incomplete"] == 0 and "could not be enforced" in summary["budget_warning"]


# ---- regression: issue #1 — resume forgets grader costs ----


def test_resume_includes_grader_costs_in_spent(tmp_path):
    """Resume must not reset grader costs to zero; a judge budget must not be re-spendable."""
    @register_grader("paid_grader_resume")
    class PaidGrader:
        name = "paid_grader_resume"
        def grade(self, case, output):
            return Score(self.name, 1.0, True, cost_usd=1.0)

    import json as _json
    from eval_uate_me.config import Config
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("\n".join(
        _json.dumps({"id": str(i), "input": str(i)}) for i in range(3)
    ))
    cfg = Config(name="grader_budget", dataset=cases_path, target={"type": "echo"},
                 graders=[{"type": "paid_grader_resume"}], concurrency=1,
                 max_cost_usd=1.0, output_dir=tmp_path / "runs")
    # first run: processes one case before budget is exhausted
    _, first, run_dir = run(cfg)
    assert first["cost_usd_spent"] >= 1.0

    # resume without raising budget must not start any new jobs
    _, resumed, _ = run(cfg, resume=run_dir)
    # spent on resume must reflect previously incurred grader costs, not start from zero
    assert resumed["cost_usd_spent"] >= first["cost_usd_spent"]
    assert resumed["incomplete"] == first["incomplete"]


# ---- regression: issue #2 — cache key omits case fields used by targets ----


def test_cache_does_not_mix_cases_with_same_input_but_different_expected(tmp_path):
    """oracle target uses case.expected; caching must not share outputs across distinct cases."""
    import json as _json
    from eval_uate_me.config import Config
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("\n".join(
        _json.dumps({"id": str(i), "input": "same", "expected": str(i)}) for i in range(3)
    ))
    cfg = Config(name="cache_key", dataset=cases_path, target={"type": "oracle"},
                 graders=[{"type": "exact_match"}], concurrency=1,
                 cache=True, output_dir=tmp_path / "runs")
    results, summary, _ = run(cfg)
    assert summary["pass_rate"] == 1.0, \
        f"cache mixed distinct cases: outputs were {[(r.case.id, r.result.output) for r in results]}"
