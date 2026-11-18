"""Tests: the programmatic API (evaluate, run_eval, EvalResult)."""
from helpers import *  # noqa: F401,F403

import eval_uate_me
from eval_uate_me import ConfigError, EvalResult, evaluate, run_eval


def test_evaluate_a_plain_function_with_mixed_case_forms():
    r = evaluate(lambda s: s.upper(), cases=[{"id": "a", "input": "x", "expected": "X"}, ("y", "Y"), ("z", "nope")])
    assert isinstance(r, EvalResult) and r.run_dir is None
    assert [x.case.id for x in r.results] == ["a", "case-2", "case-3"] and abs(r.pass_rate - 2 / 3) < 1e-9
    assert [x.case.id for x in r.failures()] == ["case-3"] and r.summary["passed"] == 2 and r.summary["format_version"] == 1


def test_evaluate_writes_nothing_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    evaluate(lambda s: s, [("a", "a")])
    assert list(tmp_path.iterdir()) == []


def test_graders_can_be_names_tuples_objects_or_functions():
    r = evaluate(lambda s: s + "!", [("a", "a!"), ("b", "b!")], graders=[
        "exact_match", ("regex", {"pattern": "!$"}), lambda case, out: out.output.endswith("!"), ExactMatch()])
    assert r.pass_rate == 1.0
    assert [s.grader for s in r.results[0].scores] == ["exact_match", "regex", "<lambda>", "exact_match"]
    only_regex = evaluate(lambda s: s, [("a", None)], graders=[("regex", {"pattern": "^a$"})])
    assert only_regex.pass_rate == 1.0
    from eval_uate_me import Score

    def scored(case, out):
        return Score("half", 0.5, False, "meh")
    r = evaluate(lambda s: s, [("a", "a")], graders=[scored])
    assert r.results[0].scores[0].value == 0.5 and r.pass_rate == 0.0


def test_a_grader_function_must_return_a_bool_or_score():
    r = evaluate(lambda s: s, [("a", "a")], graders=[lambda case, out: 1])
    assert not r.results[0].passed and "must return a bool or a Score" in r.results[0].scores[0].reason      # fails the case, not the run


def test_errors_repeats_usage_and_rows():
    from eval_uate_me import TargetOutput

    def flaky(text):
        if text == "boom":
            raise RuntimeError("down")
        return TargetOutput(output=text, usage={"cost_usd": 0.25})

    r = evaluate(flaky, [("ok", "ok"), ("boom", "boom")], repeats=2)
    assert len(r.results) == 4 and r.summary["errors"] == 2 and r.summary["cost_usd_spent"] == 0.5
    rows = r.to_rows()
    assert rows[0]["case_id"] == "case-1" and rows[0]["score:exact_match"] == 1.0 and rows[2]["error"] == "RuntimeError: down"
    assert {"case_id", "attempt", "passed", "error", "latency_s", "input", "expected", "output"} <= set(rows[0])


def test_async_functions_and_module_function_strings(tmp_path, monkeypatch):
    import asyncio
    import time

    async def slow(text):
        await asyncio.sleep(0.2)
        return text

    t0 = time.perf_counter()
    r = evaluate(slow, [(f"q{i}", f"q{i}") for i in range(25)], concurrency=25)
    assert r.pass_rate == 1.0 and time.perf_counter() - t0 < 3
    (tmp_path / "evalmod_api.py").write_text("def shout(t):\n    return t.upper()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert evaluate("evalmod_api:shout", [("a", "A")]).pass_rate == 1.0


def test_evaluate_accepts_a_target_instance_and_retries():
    from eval_uate_me.targets import EchoTarget
    assert evaluate(EchoTarget(), [("a", "a")]).pass_rate == 1.0
    n = {"k": 0}

    def once_bad(text):
        n["k"] += 1
        if n["k"] == 1:
            raise RuntimeError("blip")
        return text

    r = evaluate(once_bad, [("a", "a")], retries=2)
    assert r.pass_rate == 1.0 and r.results[0].result.retries == 1


def test_evaluate_validates_its_inputs():
    with pytest.raises(ConfigError, match="at least one case"):
        evaluate(lambda s: s, [])
    with pytest.raises(ConfigError, match="duplicate case ids"):
        evaluate(lambda s: s, [{"id": "a", "input": 1}, {"id": "a", "input": 2}])
    with pytest.raises(TypeError, match="target must be"):
        evaluate(42, [("a", "a")])
    with pytest.raises(TypeError, match="a case must be"):
        evaluate(lambda s: s, [42])
    with pytest.raises(TypeError, match="a grader must be"):
        evaluate(lambda s: s, [("a", "a")], graders=[42])


def test_run_eval_matches_the_command_line(tmp_path, capsys):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}, {"id": "2", "input": "a", "expected": "b"}])
    r = run_eval(f)
    assert r.run_dir is not None and (r.run_dir / "summary.json").exists() and r.pass_rate == 0.5
    assert main(["run", str(f)]) == 0
    assert "1/2 passed" in capsys.readouterr().out
    again = run_eval(load_config(f), split=None)                     # a Config object works too
    assert again.pass_rate == 0.5 and again.run_dir != r.run_dir
    resumed = run_eval(f, resume=r.run_dir)
    assert resumed.run_dir == r.run_dir and resumed.pass_rate == 0.5


def test_the_public_names_and_signatures_are_stable():
    import inspect
    assert {"EvalResult", "evaluate", "run_eval"} <= set(eval_uate_me.__all__)
    assert str(inspect.signature(evaluate)) == (
        "(target: 'Any', cases: 'Iterable[Any]', graders: 'Iterable[Any] | None' = None, *, repeats: 'int' = 1, "
        "concurrency: 'int' = 4, retries: 'int' = 0, timeout_s: 'float | None' = None, name: 'str' = 'eval') -> 'EvalResult'")
    assert str(inspect.signature(run_eval)) == (
        "(config: 'str | Path | Config', *, split: 'str | None' = None, resume: 'str | Path | None' = None, "
        "retry_errors: 'bool' = False, force: 'bool' = False) -> 'EvalResult'")
