"""Tests: selftest."""
from helpers import *  # noqa: F401,F403


# ---- selftest (baselines) ----


def test_selftest_passes_for_discriminating_graders(tmp_path, capsys):
    f = _selftest_cfg(tmp_path, '[[graders]]\ntype = "exact_match"\n[[graders]]\ntype = "contains"\n'
                                '[[graders]]\ntype = "max_latency"\nseconds = 5')
    assert main(["selftest", str(f)]) == 0
    out = capsys.readouterr().out
    assert "RESULT: ok" in out and "skipped" in out  # max_latency checks behaviour, not content


def test_selftest_flags_lenient_grader_and_trivial_cases(tmp_path, capsys):
    @register_grader("rubber_stamp")
    class RubberStamp(Grader):
        name = "rubber_stamp"
        def grade(self, case, out):
            return Score(self.name, 1.0, True)

    f = _selftest_cfg(tmp_path, '[[graders]]\ntype = "rubber_stamp"')
    assert main(["selftest", str(f)]) == 1
    out = capsys.readouterr().out
    assert "too_lenient" in out and "trivially passable by 'null'" in out


def test_selftest_flags_strict_grader(tmp_path):
    from eval_uate_me.selftest import selftest
    @register_grader("never")
    class Never(Grader):
        name = "never"
        def grade(self, case, out):
            return Score(self.name, 0.0, False, "no")

    cfg = load_config(_selftest_cfg(tmp_path, '[[graders]]\ntype = "never"'))
    from eval_uate_me.runner import build_graders, load_plugins
    rep = selftest(load_cases(cfg.dataset), build_graders(cfg))
    assert rep.verdicts[0].verdict == "too_strict" and not rep.ok


def test_selftest_catches_judge_that_always_approves(tmp_path):
    from eval_uate_me.selftest import selftest
    from eval_uate_me.graders import LLMJudge
    good = LLMJudge(rubric="r", judge={"type": "test_scripted"}, name="judge_ref")
    lax = LLMJudge(rubric="r", judge={"type": "test_scripted", "reply": '{"score": 5, "reason": "fine"}'}, name="judge_lax")
    cases = [Case(str(i), f"q{i}", f"answer-{i}") for i in range(5)]
    rep = {v.grader: v.verdict for v in selftest(cases, [good, lax]).verdicts}
    assert rep == {"judge_ref": "ok", "judge_lax": "too_lenient"}


def test_selftest_needs_references_and_handles_identical_answers():
    from eval_uate_me.selftest import selftest, wrong_answers
    with pytest.raises(ValueError):
        selftest([Case("a", "q")], [ExactMatch()])
    same = [Case("a", "q1", "x"), Case("b", "q2", "x")]
    assert wrong_answers(same) == {}
    rep = selftest(same, [ExactMatch()])
    assert rep.ok and "shuffled baseline not run" in rep.verdicts[0].note
    assert wrong_answers([Case("a", "q", 1), Case("b", "q", 2)]) == {"a": 2, "b": 1}


def test_oracle_and_null_targets_usable_in_normal_runs(tmp_path):
    for t, expect in (("oracle", True), ("null", False)):
        f = write_eval(tmp_path / t if (tmp_path / t).mkdir() is None else tmp_path, [{"id": "1", "input": "q", "expected": "a"}],
                       target=f'type = "{t}"')
        results, _, _ = run(load_config(f))
        assert results[0].passed is expect


# ---- selftest for structured tasks: custom oracle and guardrail graders ----


def test_selftest_with_a_custom_oracle_handles_structured_outputs(tmp_path, capsys):
    assert main(["selftest", str(_struct_cfg(tmp_path))]) == 0
    out = capsys.readouterr().out
    content = next(l for l in out.splitlines() if l.startswith("struct_content"))
    assert "100%" in content and "0%" in content and content.rstrip().endswith("ok")     # oracle 100, null 0, shuffled 0
    form = next(l for l in out.splitlines() if l.startswith("struct_form"))
    assert "guardrail: only the oracle is checked" in form and "ok" in form and "RESULT: ok" in out


def test_selftest_without_the_oracle_shows_why_one_is_needed(tmp_path, capsys):
    assert main(["selftest", str(_struct_cfg(tmp_path / "n" if (tmp_path / "n").mkdir() is None else tmp_path, oracle=False))]) == 1
    out = capsys.readouterr().out
    assert "too_strict" in next(l for l in out.splitlines() if l.startswith("struct_content"))    # built-in oracle emits the spec


def test_guardrail_grader_that_rejects_the_oracle_is_still_flagged(tmp_path, capsys):
    @register_grader("struct_picky")
    class Picky(Grader):
        name = "struct_picky"
        selftest = "guardrail"

        def grade(self, case, out):
            return Score(self.name, 0.0, False, "never happy")

    f = _struct_cfg(tmp_path, graders='[[graders]]\ntype = "struct_picky"')
    assert main(["selftest", str(f)]) == 1
    assert "too_strict" in capsys.readouterr().out


def test_selftest_oracle_config_validation(tmp_path, capsys):
    f = _struct_cfg(tmp_path)
    f.write_text(f.read_text().replace('[selftest.oracle]\ntype = "structured_ref"', '[selftest]\noracel = 1'))
    assert main(["check", str(f)]) == 2 and "Did you mean 'oracle'" in capsys.readouterr().err
    f.write_text(f.read_text().replace('[selftest]\noracel = 1', '[selftest.oracle]\nname = "x"'))
    assert main(["check", str(f)]) == 2 and "needs a 'type'" in capsys.readouterr().err
    f.write_text(f.read_text().replace('name = "x"', 'type = "nope"'))
    assert main(["selftest", str(f)]) == 2 and "[selftest.oracle]: unknown target type 'nope'" in capsys.readouterr().err


def test_meta_eval_on_the_heldout_split_counts_as_a_look(tmp_path, capsys):
    f = _meta_cfg(tmp_path, '[[graders]]\ntype = "exact_match"', [("nothing", "null")], n=40)
    f.write_text(f.read_text() + '[split]\ndev_fraction = 0.5\nsalt = "m"\n')
    assert main(["meta-eval", str(f)]) == 0                                        # dev: not a look
    assert not (tmp_path / "runs" / "heldout_log.jsonl").exists()
    capsys.readouterr()
    assert main(["meta-eval", str(f), "--split", "heldout"]) == 0
    assert "held-out look #1 on this dataset version" in capsys.readouterr().out
    assert main(["meta-eval", str(f), "--split", "heldout"]) == 0
    captured = capsys.readouterr()
    assert "held-out look #2" in captured.out and "already been evaluated 1 time(s)" in captured.err
    run(load_config(f), split="heldout")                                           # a normal run is look #3
    log = [json.loads(l) for l in (tmp_path / "runs" / "heldout_log.jsonl").read_text().splitlines()]
    assert [l["run"] == "meta-eval" for l in log] == [True, True, False] and len(log) == 3
