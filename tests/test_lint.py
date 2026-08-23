"""Tests: lint."""
from helpers import *  # noqa: F401,F403


# ---- dataset lint ----


def test_lint_flags_each_problem():
    from evalharness.lint import lint
    cases = [
        Case("a", "capital of France is Paris", "Paris"),         # leakage
        Case("b", "same", "x"), Case("c", "same", "y"),           # duplicate input
        Case("d", "q4", ""),                                      # empty expected
        Case("e", "q5", None),                                    # missing expected
    ]
    codes = {f.code: f for f in lint(cases)}
    assert codes["answer_in_input"].case_ids == ["a"]
    assert codes["duplicate_input"].case_ids == ["b", "c"]
    assert codes["empty_expected"].case_ids == ["d"] and codes["missing_expected"].case_ids == ["e"]
    assert "small_dataset" in codes and codes["no_tags"].level == "info"


def test_lint_constant_answer_and_clean_dataset():
    from evalharness.lint import lint
    const = [Case(str(i), f"q{i}", "yes", {"tags": ["t"]}) for i in range(40)]
    assert [f.code for f in lint(const)] == ["constant_answer"]
    clean = [Case(str(i), f"question {i}", f"answer{i % 7}", {"tags": ["t"]}) for i in range(40)]
    assert lint(clean) == []


def test_lint_partial_tags_and_cli(tmp_path, capsys):
    from evalharness.lint import lint
    cases = [Case("a", "q1", "x", {"tags": ["t"]}), Case("b", "q2", "y")]
    assert {f.code: f.case_ids for f in lint(cases, min_cases=1)}["partially_tagged"] == ["b"]

    p = tmp_path / "d.jsonl"
    p.write_text('{"id":"a","input":"q","expected":"x"}\n{"id":"b","input":"q","expected":"y"}')
    assert main(["lint", str(p)]) == 0                  # warnings alone do not fail
    assert main(["lint", str(p), "--strict"]) == 1      # ...unless --strict
    assert "duplicate_input" in capsys.readouterr().out
    f = write_eval(tmp_path, [{"id": "1", "input": "q", "expected": "a"}])
    assert main(["lint", str(f), "--json", str(tmp_path / "l.json")]) == 0
    assert json.loads((tmp_path / "l.json").read_text())
