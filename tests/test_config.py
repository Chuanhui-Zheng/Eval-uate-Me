"""Tests: config."""
from helpers import *  # noqa: F401,F403


# ---- config validation ----


def test_config_reports_all_problems_with_suggestions(tmp_path, capsys):
    f = _write_cfg(tmp_path, 'datset = "c.jsonl"\n[target]\ntype = "echo"\n[run]\nconcurency = 2\nrepeats = 0\n')
    assert main(["check", str(f)]) == 2
    err = capsys.readouterr().err
    assert "unknown key 'datset'" in err and "Did you mean 'dataset'" in err
    assert "missing required key 'dataset'" in err and "missing required key 'graders'" in err
    assert "Did you mean 'concurrency'" in err and "repeats must be an integer >= 1" in err


def test_config_type_and_file_errors(tmp_path, capsys):
    bad_type = _write_cfg(tmp_path, GOOD + '[run]\nconcurrency = "four"\ncache = 1\n')
    assert main(["check", str(bad_type)]) == 2
    err = capsys.readouterr().err
    assert "concurrency must be an integer >= 1, got 'four'" in err and "cache must be true or false" in err
    assert main(["check", str(tmp_path / "nope.toml")]) == 2 and "config file not found" in capsys.readouterr().err
    assert main(["check", str(_write_cfg(tmp_path, "this is = = not toml"))]) == 2
    assert "not valid TOML" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["check", str(_write_cfg(empty, GOOD, dataset=False))]) == 2
    assert "dataset file not found" in capsys.readouterr().err


def test_check_flags_unknown_plugin_and_bad_options(tmp_path, capsys):
    f = _write_cfg(tmp_path, 'dataset = "c.jsonl"\n[target]\ntype = "ecco"\n[[graders]]\ntype = "exact_match"\n')
    assert main(["check", str(f)]) == 2
    assert "unknown target type 'ecco'. Did you mean 'echo'" in capsys.readouterr().err
    f = _write_cfg(tmp_path, GOOD + '[[graders]]\ntype = "regex"\npatern = "x"\n')
    assert main(["check", str(f)]) == 2
    assert "no option 'patern'. Did you mean 'pattern'" in capsys.readouterr().err
    f = _write_cfg(tmp_path, GOOD + '[[graders]]\ntype = "llm_judge"\n')
    assert main(["check", str(f)]) == 2
    assert "needs option(s): rubric" in capsys.readouterr().err
    f = _write_cfg(tmp_path, GOOD + '[[graders]]\ntype = "llm_judge"\nrubric = "r"\n[graders.judge]\ntype = "mok"\n')
    assert main(["check", str(f)]) == 2
    assert "unknown judge 'mok'" in capsys.readouterr().err


def test_check_ok_and_runs_never_start_on_bad_config(tmp_path, capsys):
    f = _write_cfg(tmp_path, GOOD + '[[graders]]\ntype = "max_latency"\nseconds = 5\nrole = "advisory"\n')
    assert main(["check", str(f)]) == 0
    out = capsys.readouterr().out
    assert "ok: 1 cases" in out and "max_latency (advisory)" in out
    bad = _write_cfg(tmp_path, 'dataset = "c.jsonl"\n[target]\ntype = "nope"\n[[graders]]\ntype = "exact_match"\n')
    assert main(["run", str(bad)]) == 2
    assert not (tmp_path / "runs").exists()          # failed before creating any run directory


def test_dataset_errors_are_config_errors(tmp_path, capsys):
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a"}\nnot json')
    f = tmp_path / "e.toml"
    f.write_text(GOOD)
    assert main(["check", str(f)]) == 2
    assert "c.jsonl:2: invalid JSON" in capsys.readouterr().err


# ---- ${CONFIG_DIR} in plugin options ----


def test_config_dir_variable_makes_paths_independent_of_the_working_directory(tmp_path, monkeypatch, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "answer.txt").write_text("42\n")
    f = write_eval(proj, [{"id": "1", "input": "q", "expected": "42"}], target='type = "reads_a_file"\npath = "${CONFIG_DIR}/answer.txt"')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)                                         # not the project directory
    assert main(["check", str(f)]) == 0
    results, _, d = run(load_config(f))
    assert results[0].passed
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["target"]["path"] == "${CONFIG_DIR}/answer.txt"      # the manifest keeps the portable form
    assert str(proj) not in json.dumps(manifest["target"])
    f.write_text(f.read_text().replace("${CONFIG_DIR}/answer.txt", "answer.txt"))
    capsys.readouterr()
    assert main(["check", str(f)]) == 2                                  # without the variable, the path is cwd-relative
    err = capsys.readouterr().err
    assert "could not create target 'reads_a_file': FileNotFoundError" in err and "answer.txt" in err


def test_config_dir_variable_reaches_graders_mutants_and_selftest_oracle(tmp_path):
    from evalharness.config import expand_vars
    base = Path("/base")                                       # str() differs per OS ("/base" vs "\\base")
    assert expand_vars({"a": ["x/${CONFIG_DIR}/y", {"b": "${CONFIG_DIR}"}], "n": 3}, base) == {
        "a": [f"x/{base}/y", {"b": str(base)}], "n": 3}
    (tmp_path / "answer.txt").write_text("1")
    f = _meta_cfg(tmp_path, '[[graders]]\ntype = "exact_match"', [("m", "null")])
    f.write_text(f.read_text().replace('type = "null"', 'type = "reads_a_file"\npath = "${CONFIG_DIR}/answer.txt"'))
    cfg = load_config(f)
    assert Path(cfg.mutants[0]["target"]["path"]) == tmp_path / "answer.txt"     # separators may be mixed on Windows
