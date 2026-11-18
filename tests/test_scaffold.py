"""Tests: scaffold."""
from helpers import *  # noqa: F401,F403


# ---- scaffolds ----


def test_init_project_creates_a_runnable_eval_and_never_overwrites(tmp_path, capsys):
    d = tmp_path / "proj"
    assert main(["init", str(d)]) == 0
    assert {p.name for p in d.iterdir()} == {"eval.toml", "cases.jsonl", "cases.meta.toml", "README.md"}
    assert main(["check", str(d / "eval.toml")]) == 0
    assert main(["lint", str(d / "eval.toml")]) == 0
    assert main(["selftest", str(d / "eval.toml")]) == 0
    capsys.readouterr()
    assert main(["run", str(d / "eval.toml")]) == 0
    assert "2/3 passed" in capsys.readouterr().out
    (d / "eval.toml").write_text("# my edits")
    assert main(["init", str(d)]) == 2                       # refuses; edits survive
    assert (d / "eval.toml").read_text() == "# my edits"
    assert "refusing to overwrite" in capsys.readouterr().err


def test_init_plugin_generates_a_working_package_with_passing_tests(tmp_path, capsys, monkeypatch):
    import subprocess
    import sys
    assert main(["init-plugin", "scratch_widget", "--dir", str(tmp_path)]) == 0
    root = tmp_path / "eval_uate_me-scratch-widget"
    text = (root / "pyproject.toml").read_text()
    assert 'scratch_widget = "scratch_widget:ScratchWidgetTarget"' in text and "eval_uate_me.graders" in text
    monkeypatch.syspath_prepend(str(root))
    assert main(["check", str(root / "eval.toml")]) == 0
    assert main(["selftest", str(root / "eval.toml")]) == 0
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "2 passed" in r.stdout, r.stdout + r.stderr


def test_init_plugin_rejects_bad_names(tmp_path, capsys):
    for bad in ("CVE-Triage", "1abc", "eval_uate_me", "has space"):
        assert main(["init-plugin", bad, "--dir", str(tmp_path)]) == 2
    assert "lowercase letters" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_version_is_consistent_between_package_and_pyproject():
    import tomllib
    import eval_uate_me
    meta = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    assert meta["project"]["version"] == eval_uate_me.__version__
