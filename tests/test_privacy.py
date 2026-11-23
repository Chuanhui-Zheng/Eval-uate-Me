"""Tests: privacy."""
from helpers import *  # noqa: F401,F403


# ---- privacy mode ----


def test_scores_only_never_writes_or_prints_content(tmp_path, capsys):
    _leaky_target()
    f = _privacy_cfg(tmp_path)
    assert main(["run", str(f)]) == 0
    captured = capsys.readouterr()
    assert SECRET not in captured.out and SECRET not in captured.err
    assert "[redacted]" in captured.out and "privacy mode" in captured.out
    run_dir = next((tmp_path / "runs").iterdir())
    for path in run_dir.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(), f"leaked into {path.name}"
    rows = [json.loads(l) for l in (run_dir / "results.jsonl").read_text().splitlines()]
    ok = next(r for r in rows if r["case"]["id"] == "ok")
    assert ok["case"]["input"] is None and ok["result"]["output"] is None and ok["result"]["trace"] == []
    assert ok["case"]["metadata"] == {"tags": ["t1"]}      # unsafe metadata keys dropped, tags kept
    assert ok["passed"] is True and ok["result"]["usage"] == {"cost_usd": 0.01}
    assert (run_dir / "report.html").read_text().count("Privacy mode") == 1


def test_scores_only_keeps_metrics_intact(tmp_path):
    _leaky_target()
    results, summary, _ = run(load_config(_privacy_cfg(tmp_path)))
    outcome = {r.case.id: r.passed for r in results}
    assert outcome == {"ok": True, "wrong": False, "err": False, "boom": False}
    assert summary["errors"] == 2 and summary["by_tag"]["t1"]["pass_rate"] == 0.5
    assert summary["failure_reasons"] == {"failed:exact_match": 1, "target_error": 2}
    assert summary["privacy_store"] == "scores_only"


def test_scores_only_resume_and_compare_still_work(tmp_path):
    _leaky_target()
    f = _privacy_cfg(tmp_path)
    _, _, d1 = run(load_config(f))
    calls = []
    results, summary, out = run(load_config(f), resume=d1)         # nothing missing: no new work, no crash
    assert out == d1 and len(results) == 4
    _, _, d2 = run(load_config(f))
    assert main(["compare", str(d1), str(d2)]) == 0
    for p in list(d1.rglob("*")) + list(d2.rglob("*")):
        if p.is_file():
            assert SECRET not in p.read_text()


def test_full_mode_still_stores_content(tmp_path):
    _leaky_target()
    f = _privacy_cfg(tmp_path, privacy='store = "full"')
    _, _, d = run(load_config(f))
    assert SECRET in (d / "results.jsonl").read_text()


def test_privacy_config_validation(tmp_path, capsys):
    _leaky_target()
    assert main(["check", str(_privacy_cfg(tmp_path, privacy='store = "none"'))]) == 2
    assert 'store must be "full" or "scores_only"' in capsys.readouterr().err
    f = _privacy_cfg(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, extra_run="")
    f.write_text(f.read_text().replace("[run]", "[run]\ncache = true"))
    assert main(["check", str(f)]) == 2
    assert "cannot be combined" in capsys.readouterr().err
    g = _privacy_cfg(tmp_path / "y" if (tmp_path / "y").mkdir() is None else tmp_path, privacy="colour = 1")
    assert main(["check", str(g)]) == 2
    assert "unknown key 'colour'" in capsys.readouterr().err


def test_local_only_blocks_networked_judge_and_warns_on_opaque_components(tmp_path, capsys):
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    f = tmp_path / "e.toml"
    f.write_text('dataset = "c.jsonl"\n[target]\ntype = "echo"\n[[graders]]\ntype = "llm_judge"\nrubric = "r"\n'
                 '[graders.judge]\ntype = "anthropic"\n[privacy]\nlocal_only = true\n')
    assert main(["run", str(f)]) == 2
    assert "grader 'llm_judge' sends data off this machine" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()

    f.write_text('dataset = "c.jsonl"\n[target]\ntype = "echo"\n[[graders]]\ntype = "llm_judge"\nrubric = "r"\n'
                 '[graders.judge]\ntype = "test_scripted"\n[privacy]\nlocal_only = true\n')
    assert main(["check", str(f)]) == 0                                  # test backend is local

    f.write_text('dataset = "c.jsonl"\n[target]\ntype = "command"\ncommand = [\'' + sys.executable + '\', \'-c\', \'' + COPY_STDIN + '\']\n'
                 '[[graders]]\ntype = "exact_match"\n[privacy]\nlocal_only = true\n')
    assert main(["check", str(f)]) == 0
    assert "does not declare whether it uses the network" in capsys.readouterr().err


def test_scores_only_warns_when_a_judge_sends_content_out(tmp_path, capsys, monkeypatch):
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    f = tmp_path / "e.toml"
    f.write_text('dataset = "c.jsonl"\n[target]\ntype = "echo"\n[[graders]]\ntype = "llm_judge"\nrubric = "r"\n'
                 '[graders.judge]\ntype = "anthropic"\n[privacy]\nstore = "scores_only"\n')
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["run", str(f)])                         # the judge call fails without a key; the warning must still show
    assert "sends case content off this machine" in capsys.readouterr().err
