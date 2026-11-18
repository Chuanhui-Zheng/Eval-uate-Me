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
