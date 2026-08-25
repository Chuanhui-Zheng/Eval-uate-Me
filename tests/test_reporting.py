"""Tests: reporting."""
from helpers import *  # noqa: F401,F403


# ---- run history ----


def test_sparkline_scales_to_the_unit_range():
    from evalharness.history import sparkline
    assert sparkline([0, 0.5, 1]) == "▁▅█" and sparkline([1, 1]) == "██" and sparkline([]) == ""


def test_history_flags_a_significant_regression_and_what_changed(tmp_path, capsys):
    _hist_run(tmp_path)
    _hist_run(tmp_path)
    _hist_run(tmp_path, fail={f"c{i}" for i in range(10)}, tag="v2")          # half the cases now fail
    capsys.readouterr()
    assert main(["history", str(tmp_path / "runs")]) == 0
    out = capsys.readouterr().out
    assert "hist-eval  split=all" in out and "(3 runs)" in out and "100% -> 50%" in out and "██▅" in out
    assert "REGRESSION" in out and "-50.0%" in out and "changed: target options: tag" in out
    assert main(["history", str(tmp_path / "runs"), "--fail-on-regression"]) == 1


def test_history_reports_improvement_and_no_change(tmp_path, capsys):
    _hist_run(tmp_path, fail={f"c{i}" for i in range(10)})
    _hist_run(tmp_path)
    capsys.readouterr()
    assert main(["history", str(tmp_path / "runs"), "--fail-on-regression"]) == 0
    assert "-> improved" in capsys.readouterr().out
    _hist_run(tmp_path)
    assert main(["history", str(tmp_path / "runs")]) == 0
    assert "no significant change" in capsys.readouterr().out


def test_a_new_dataset_version_starts_a_new_series_and_is_not_compared(tmp_path, capsys):
    _hist_run(tmp_path, n=20)
    _hist_run(tmp_path, n=20)
    _hist_run(tmp_path, n=24, fail={f"c{i}" for i in range(24)})              # different dataset, everything failing
    capsys.readouterr()
    assert main(["history", str(tmp_path / "runs"), "--fail-on-regression"]) == 0
    out = capsys.readouterr().out
    assert out.count("hist-eval  split=all") == 2 and "(2 runs)" in out and "(1 run)" in out
    assert "REGRESSION" not in out                                              # a one-run series has nothing to compare


def test_history_html_escapes_and_draws_the_chart(tmp_path, capsys):
    _hist_run(tmp_path, name="<b>evil</b>")
    _hist_run(tmp_path, name="<b>evil</b>")
    assert main(["history", str(tmp_path / "runs"), "--html", str(tmp_path / "h.html")]) == 0
    html = (tmp_path / "h.html").read_text()
    assert "<svg" in html and "<polyline" in html and "&lt;b&gt;evil&lt;/b&gt;" in html and "<b>evil</b>" not in html
    assert "wrote" in capsys.readouterr().out


def test_history_filters_ignores_non_runs_and_explains_empty_folders(tmp_path, capsys):
    _hist_run(tmp_path, name="alpha")
    _hist_run(tmp_path, name="beta")
    (tmp_path / "runs" / ".cache").mkdir()
    (tmp_path / "runs" / "half-written").mkdir()
    (tmp_path / "runs" / "heldout_log.jsonl").write_text("{}\n")
    capsys.readouterr()
    assert main(["history", str(tmp_path / "runs"), "--name", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" not in out
    assert main(["history", str(tmp_path / "runs"), "--name", "nope"]) == 2 and "no finished runs found" in capsys.readouterr().err
    assert main(["history", str(tmp_path / "missing")]) == 2 and "runs folder not found" in capsys.readouterr().err


def test_eval_names_with_slashes_or_odd_characters_make_a_valid_run_directory(tmp_path):
    d = _hist_run(tmp_path, name="a/b <c>: d")
    assert d.parent == tmp_path / "runs" and d.name.startswith("a-b-c-d-")
    assert json.loads((d / "summary.json").read_text())["name"] == "a/b <c>: d"       # the real name is kept
    assert _hist_run(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, name="///").name.startswith("run-")


# ---- Markdown comparison for pull requests; trace drill-down in the report ----


def test_markdown_comparison_for_a_pull_request_comment(tmp_path, capsys):
    base, cand = _two_systems(tmp_path)
    capsys.readouterr()
    assert main(["compare", str(base), str(cand), "--markdown", "--title", "Eval: PR 12"]) == 0     # candidate improves
    out = capsys.readouterr().out
    assert out.startswith("### Eval: PR 12") and "| | baseline | candidate | change |" in out
    assert ":green_circle: **improvement**" in out and "| pass rate (24 cases) | 0.0% | 54.2% |" in out
    assert "| tag | cases | change | adjusted p |" in out and "| easy | 12 | +100.0% |" in out
    assert "Holm-adjusted" in out and "**Regressed cases (0):** none" in out
    assert main(["compare", str(cand), str(base), "--markdown"]) == 1                              # reversed: a regression
    out = capsys.readouterr().out
    assert ":red_circle: **regression**" in out and "**Regressed cases (13):**" in out and "`e0`" in out and "more" not in out


def test_markdown_comparison_escapes_table_cells_and_shows_warnings(tmp_path, capsys):
    from evalharness.report import markdown_compare
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"q{i}", "metadata": {"tags": ["a|b<i>"]}} for i in range(8)]
    dirs = []
    for fail in (set(), {f"c{i}" for i in range(8)}):
        sub = tmp_path / ("x" if not fail else "y")
        sub.mkdir()
        HIST_FAIL.clear()
        HIST_FAIL.update(fail)
        dirs.append(run(load_config(write_eval(sub, cases, target='type = "hist_target"')))[2])
    manifest = json.loads((dirs[1] / "manifest.json").read_text())
    manifest["split"] = "dev"
    (dirs[1] / "manifest.json").write_text(json.dumps(manifest))
    text, n = markdown_compare(dirs[0], dirs[1])
    assert n == 8 and "a\\|b&lt;i&gt;" in text and "a|b<i>" not in text
    assert "> :warning: runs use different splits (all vs dev)" in text


def test_html_report_drills_down_into_traces_cost_and_failures(tmp_path):
    f = write_eval(tmp_path, [{"id": f"c{i}", "input": f"q{i}", "expected": f"q{i}"} for i in range(3)], target='type = "traced"')
    _, _, d = run(load_config(f))
    html = (d / "report.html").read_text()
    assert "Jump to failures" in html and 'href="#case-0">c1</a>' in html and 'id="case-0"' in html      # the failure comes first
    assert "<th>#</th><th>tool / step</th><th>round</th><th>summary</th>" in html and "(3 steps" in html
    assert "<td>search</td>" in html and "<td>think</td>" in html and "plain note" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert" not in html
    assert "Slowest and costliest" in html and "<th>costliest</th>" in html and "$0.5000" in html
    assert "cost_usd 0.5, input_tokens 120" in html
    clean = write_eval(tmp_path / "ok" if (tmp_path / "ok").mkdir() is None else tmp_path, [{"id": "a", "input": "q", "expected": "q"}])
    _, _, d2 = run(load_config(clean))
    html2 = (d2 / "report.html").read_text()
    assert "Jump to failures" not in html2 and "<th>costliest</th>" not in html2 and "Slowest and costliest" in html2


def test_html_report_notes_retries_and_cache(tmp_path):
    calls = {"n": 0}

    @register_target("retry_then_ok")
    class RetryThenOk(Target):
        network = False

        def run(self, case):
            calls["n"] += 1
            return TargetOutput(error="blip") if calls["n"] == 1 else TargetOutput(output=case.input)

    f = write_eval(tmp_path, [{"id": "a", "input": "q", "expected": "q"}], target='type = "retry_then_ok"')
    f.write_text(f.read_text() + "retries = 2\nretry_delay_s = 0\ncache = true\n")
    _, _, d1 = run(load_config(f))
    assert "1 retry" in (d1 / "report.html").read_text()
    _, _, d2 = run(load_config(f))
    assert "served from cache" in (d2 / "report.html").read_text()
