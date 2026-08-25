"""Tests: scoring policy."""
from helpers import *  # noqa: F401,F403


# ---- errors vs wrong answers ----


def test_summary_separates_errors_from_wrong_answers(tmp_path):
    _, s, _ = run(load_config(_mixed_run(tmp_path)))
    assert s["errors"] == 1 and abs(s["error_rate"] - 1 / 3) < 1e-9
    assert abs(s["pass_rate"] - 1 / 3) < 1e-9                    # errors count as failures
    assert s["pass_rate_answered"] == 0.5 and s["cases_answered"] == 2   # outage excluded


def test_max_error_rate_gate_and_report_text(tmp_path, capsys):
    f = _mixed_run(tmp_path)
    assert main(["run", str(f), "--max-error-rate", "0.5"]) == 0
    assert "answered cases only: 50%" in capsys.readouterr().out
    assert main(["run", str(f), "--max-error-rate", "0.1"]) == 1


def test_all_errors_do_not_crash_summary(tmp_path):
    @register_target("alldown")
    class AllDown(Target):
        def run(self, case):
            return TargetOutput(error="down")

    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}], target='type = "alldown"')
    _, s, out = run(load_config(f))
    assert s["cases_answered"] == 0 and s["pass_rate_answered"] == 0.0 and s["error_rate"] == 1.0
    assert (out / "report.html").exists()


# ---- grader roles ----


def test_advisory_grader_does_not_affect_pass_but_is_reported(tmp_path, capsys):
    f = write_eval(tmp_path, [{"id": "1", "input": "abc", "expected": "abc"}],
                   graders='[[graders]]\ntype = "exact_match"\n[[graders]]\ntype = "regex"\npattern = "^zzz"\nrole = "advisory"')
    results, summary, out = run(load_config(f))
    r = results[0]
    assert r.passed and [s.role for s in r.scores] == ["required", "advisory"] and not r.scores[1].passed
    assert summary["pass_rate"] == 1.0 and summary["advisory_failures"] == {"regex": 1}
    assert summary["failure_reasons"] == {}
    assert main(["run", str(f)]) == 0
    assert "(advisory)" in capsys.readouterr().out
    assert "advisory" in (out / "report.html").read_text()


def test_required_grader_still_fails_the_case(tmp_path):
    f = write_eval(tmp_path, [{"id": "1", "input": "abc", "expected": "nope"}],
                   graders='[[graders]]\ntype = "exact_match"\n[[graders]]\ntype = "regex"\npattern = "abc"\nrole = "advisory"')
    results, summary, _ = run(load_config(f))
    assert not results[0].passed and summary["failure_reasons"] == {"failed:exact_match": 1}


def test_role_validation(tmp_path):
    bad = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}],
                     graders='[[graders]]\ntype = "exact_match"\nrole = "optional"')
    with pytest.raises(ValueError, match="role"):
        run(load_config(bad))
    only_adv = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}],
                          graders='[[graders]]\ntype = "exact_match"\nrole = "advisory"')
    with pytest.raises(ValueError, match="at least one grader"):
        run(load_config(only_adv))
