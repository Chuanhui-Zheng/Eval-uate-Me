"""Tests: metaeval."""
from helpers import *  # noqa: F401,F403


# ---- meta-eval (mutation testing for evals) ----


def test_meta_eval_flags_a_blind_spot_then_closes_it(tmp_path, capsys):
    lenient = _meta_cfg(tmp_path, '[[graders]]\ntype = "contains"',
                        [("returns-nothing", "null"), ("adds-bang", "suffix_bang"), ("copy-of-real", "oracle")])
    assert main(["meta-eval", str(lenient)]) == 1
    out = capsys.readouterr().out
    assert "returns-nothing" in out and "killed" in out.split("returns-nothing")[1].splitlines()[0]
    assert "survived" in out.split("adds-bang")[1].splitlines()[0]
    assert "no-op" in out.split("copy-of-real")[1].splitlines()[0]
    assert "SURVIVED: 'adds-bang'" in out and "mutation score: 50%" in out and "blind spots found" in out

    strict = _meta_cfg(tmp_path / "s" if (tmp_path / "s").mkdir() is None else tmp_path,
                       '[[graders]]\ntype = "contains"\n[[graders]]\ntype = "exact_match"',
                       [("returns-nothing", "null"), ("adds-bang", "suffix_bang")])
    assert main(["meta-eval", str(strict), "--json", str(tmp_path / "me.json")]) == 0
    data = json.loads((tmp_path / "me.json").read_text())
    by = {m["name"]: m for m in data["mutants"]}
    assert data["mutation_score"] == 1.0 and data["ok"] and by["adds-bang"]["status"] == "killed"
    assert list(by["adds-bang"]["caught_by"]) == ["exact_match"]          # only the strict grader sees it
    assert by["adds-bang"]["delta"] == -1.0 and by["adds-bang"]["p_value"] < 0.01
    assert "mutation score: 100%" in capsys.readouterr().out


def test_meta_eval_warns_about_weak_baselines_and_tiny_datasets(tmp_path, capsys):
    weak = _meta_cfg(tmp_path, '[[graders]]\ntype = "exact_match"', [("better", "oracle")], base='type = "null"')
    assert main(["meta-eval", str(weak)]) == 1                            # 'better' is better than a broken baseline
    assert "passes only 0%" in capsys.readouterr().out
    tiny = _meta_cfg(tmp_path / "t" if (tmp_path / "t").mkdir() is None else tmp_path,
                     '[[graders]]\ntype = "exact_match"', [("nothing", "null")], n=4)
    assert main(["meta-eval", str(tiny)]) == 1
    out = capsys.readouterr().out
    assert "fewer than 6 cases" in out and "survived" in out.split("nothing")[1].splitlines()[0]


def test_meta_eval_config_validation_and_errors(tmp_path, capsys):
    f = _meta_cfg(tmp_path, '[[graders]]\ntype = "exact_match"', [("a", "null")])
    plain = write_eval(tmp_path / "p" if (tmp_path / "p").mkdir() is None else tmp_path,
                       [{"id": "1", "input": "a", "expected": "a"}])
    assert main(["meta-eval", str(plain)]) == 2 and "no [[mutants]]" in capsys.readouterr().err
    text = f.read_text()
    f.write_text(text.replace('name = "a"', 'name = "a"\n[mutants.extra]\nx = 1').replace('[run]', '[[mutants]]\nname = "a"\n[mutants.target]\ntype = "null"\n[run]'))
    assert main(["check", str(f)]) == 2 and "name 'a' is used twice" in capsys.readouterr().err
    f.write_text(text.replace('type = "null"', 'type = "nul"'))
    assert main(["meta-eval", str(f)]) == 2
    assert "mutant 'a': unknown target type 'nul'. Did you mean 'null'" in capsys.readouterr().err
    f.write_text(text.replace('name = "a"\n', ''))
    assert main(["check", str(f)]) == 2 and "needs a 'name'" in capsys.readouterr().err


def test_meta_eval_uses_the_dev_split_by_default(tmp_path, capsys):
    f = _meta_cfg(tmp_path, '[[graders]]\ntype = "exact_match"', [("nothing", "null")], n=40)
    f.write_text(f.read_text() + '[split]\ndev_fraction = 0.5\nsalt = "m"\n')
    assert main(["meta-eval", str(f), "--json", str(tmp_path / "x.json")]) == 0
    d = json.loads((tmp_path / "x.json").read_text())
    assert d["split"] == "dev" and 10 < d["cases"] < 30
