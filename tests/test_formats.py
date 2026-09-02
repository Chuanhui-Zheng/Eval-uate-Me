"""Tests: versioned on-disk formats."""
from helpers import *  # noqa: F401,F403


def _rewrite(path, fn):
    """Apply fn(dict) -> dict to a JSON file, or to every row of a JSONL file."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        out = "".join(json.dumps(fn(json.loads(l)), ensure_ascii=False) + "\n" for l in text.splitlines() if l.strip())
    else:
        out = json.dumps(fn(json.loads(text)), indent=2)
    path.write_text(out, encoding="utf-8")


def _drop_version(d):
    d.pop("format_version", None)
    return d


def _set_version(v):
    def f(d):
        d["format_version"] = v
        return d
    return f


def _labelled(tmp_path):
    d = _labelled_run(tmp_path, n=4)
    _sheet_with(d, ["yes", "no", "yes", "no"], "ana", "a.csv")
    return d


def test_every_file_a_run_writes_carries_the_format_version(tmp_path):
    d = _labelled(tmp_path)
    assert json.loads((d / "manifest.json").read_text())["format_version"] == 1
    assert json.loads((d / "summary.json").read_text())["format_version"] == 1
    assert all(json.loads(l)["format_version"] == 1 for l in (d / "results.jsonl").read_text().splitlines())
    assert all(json.loads(l)["format_version"] == 1 for l in (d / "labels.jsonl").read_text().splitlines())


def test_files_from_before_versioning_still_read_fine(tmp_path, capsys):
    a = _labelled_run(tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path, n=4)
    d = _labelled(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path)
    for run_dir in (a, d):
        for name in ("manifest.json", "summary.json", "results.jsonl", "labels.jsonl"):
            if (run_dir / name).exists():
                _rewrite(run_dir / name, _drop_version)        # what an older evalharness wrote
    capsys.readouterr()
    assert main(["show", str(d)]) == 0
    assert main(["compare", str(a), str(d)]) == 0
    assert main(["report", str(d)]) == 0
    assert main(["history", str(d.parent)]) == 0
    assert main(["calibrate", str(d), "--grader", "overall"]) == 0
    assert main(["label", "export", str(d), "-o", str(d / "again.csv")]) == 0
    assert "error" not in capsys.readouterr().err.lower()


@pytest.mark.parametrize("name", ["manifest.json", "summary.json", "results.jsonl", "labels.jsonl"])
def test_files_from_a_newer_format_are_refused_with_the_fix(tmp_path, capsys, name):
    d = _labelled(tmp_path)
    _rewrite(d / name, _set_version(99))
    capsys.readouterr()
    commands = [["show", str(d)], ["compare", str(d), str(d)], ["calibrate", str(d), "--grader", "overall"],
                ["label", "export", str(d), "-o", str(d / "x.csv"), "--force"], ["history", str(d.parent)]]
    refused = 0
    for cmd in commands:
        code = main(cmd)
        err = capsys.readouterr().err
        if code == 2 and "written by a newer evalharness" in err and "format_version 99" in err and "upgrade evalharness" in err:
            refused += 1
    assert refused >= 1, f"no command refused a newer {name}"       # every file type is refused by at least one reader


def test_every_reader_of_every_file_checks_the_version(tmp_path, capsys):
    """The commands that read each file type must each refuse a newer version (not just one of them)."""
    expectations = {   # {d} = the run directory, {runs} = the folder holding it
        "manifest.json": [["show", "{d}"], ["history", "{runs}"]],
        "summary.json": [["show", "{d}"], ["history", "{runs}"], ["report", "{d}"]],
        "results.jsonl": [["compare", "{d}", "{d}"], ["report", "{d}"], ["calibrate", "{d}", "--grader", "overall"]],
        "labels.jsonl": [["calibrate", "{d}", "--grader", "overall"], ["label", "disagreements", "{d}"]],
    }
    for name, commands in expectations.items():
        for k, template in enumerate(commands):
            sub = tmp_path / f"case-{name}-{k}"
            sub.mkdir()
            d = _labelled(sub)
            _rewrite(d / name, _set_version(99))
            capsys.readouterr()
            argv = [a.format(d=d, runs=d.parent) for a in template]
            assert main(argv) == 2, (name, template)
            assert "written by a newer evalharness" in capsys.readouterr().err, (name, template)


def test_a_non_integer_format_version_is_rejected(tmp_path, capsys):
    d = _labelled_run(tmp_path, n=2)
    _rewrite(d / "summary.json", _set_version("one"))
    assert main(["show", str(d)]) == 2
    assert "format_version must be a non-negative integer" in capsys.readouterr().err


def test_resume_refuses_a_run_from_a_newer_format(tmp_path):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    _, _, d = run(load_config(f))
    _rewrite(d / "manifest.json", _set_version(99))
    from evalharness import ConfigError
    with pytest.raises(ConfigError, match="newer evalharness"):
        run(load_config(f), resume=d)


def test_dataset_rows_may_declare_a_schema_version(tmp_path, capsys):
    f = tmp_path / "c.jsonl"
    f.write_text('{"id":"a","input":1,"expected":1,"schema_version":1}\n{"id":"b","input":2,"expected":2}\n')
    assert [c.id for c in load_cases(f)] == ["a", "b"]
    f.write_text('{"id":"a","input":1,"schema_version":2}\n')
    from evalharness import ConfigError
    with pytest.raises(ConfigError, match="c.jsonl:1: case schema_version 2 is newer"):
        load_cases(f)
    f.write_text('{"id":"a","input":1,"schema_version":"x"}\n')
    with pytest.raises(ConfigError, match="schema_version must be a positive integer"):
        load_cases(f)
    f.write_text('{"id":"a","input":1,"schema_version":0}\n')
    with pytest.raises(ConfigError, match="positive integer"):
        load_cases(f)
