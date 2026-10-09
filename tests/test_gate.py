"""Tests: baselines and the CI gate."""
from helpers import *  # noqa: F401,F403

COST = {"per_case": 1.0}


@register_target("gate_cost_target")
class GateCostTarget(Target):
    network = False

    def run(self, case):
        return TargetOutput(output=case.input, usage={"cost_usd": COST["per_case"]})


def _gcfg(tmp_path, gate_toml, n=20, target='type = "hist_target"'):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"q{i}", "metadata": {"tags": ["a" if i < n // 2 else "b"]}}
             for i in range(n)]
    f = write_eval(tmp_path, cases, target=target)
    f.write_text(f.read_text() + gate_toml)
    return f


def _do(f, fail=()):
    HIST_FAIL.clear()
    HIST_FAIL.update(fail)
    return run(load_config(f))[2]


def _gate(f, *extra):
    return main(["gate", str(f), *extra])


def _promote(f):
    assert main(["baseline", "promote", "--config", str(f)]) == 0
    return f.with_suffix(".baseline.json")


BASIC = '\n[gate.max_drop]\npass_rate = 0.05\n'


def test_promote_writes_a_self_contained_baseline(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    d = _do(f)
    capsys.readouterr()
    path = _promote(f)
    out = capsys.readouterr().out
    assert "promoted" in out and "commit this file" in out and "pass_rate = 1.0000" in out
    b = json.loads(path.read_text())
    assert b["format_version"] == 1 and b["run_id"] == d.name and b["metrics"]["pass_rate"] == 1.0
    assert len(b["case_rates"]) == 20 and b["case_tags"]["c0"] == ["a"] and b["split"] == "all"
    assert b["dataset_sha256"] == json.loads((d / "manifest.json").read_text())["dataset_sha256"]
    assert b["metrics"]["tag.a"] == 1.0
    _do(f, fail={"c0"})
    assert main(["baseline", "promote", "--config", str(f)]) == 0 and "replaced" in capsys.readouterr().out


def test_only_a_complete_run_can_be_promoted(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    d = _do(f)
    m = json.loads((d / "manifest.json").read_text())
    m["status"] = "interrupted"
    (d / "manifest.json").write_text(json.dumps(m))
    assert main(["baseline", "promote", str(d), "--config", str(f)]) == 2
    assert "only a complete run can be a baseline" in capsys.readouterr().err


def test_gate_passes_an_unchanged_run_and_fails_a_real_drop(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    _do(f)
    _promote(f)
    _do(f)
    capsys.readouterr()
    assert _gate(f) == 0 and "GATE PASSED" in capsys.readouterr().out
    _do(f, fail={f"c{i}" for i in range(10)})
    assert _gate(f) == 1
    out = capsys.readouterr().out
    assert "pass_rate dropped 0.5000 vs the baseline 1.0000 (allowed 0.0500)" in out and "GATE FAILED (1 problem(s))" in out


def test_significant_only_ignores_noise_but_still_catches_real_drops(tmp_path, capsys):
    f = _gcfg(tmp_path, '[gate]\nsignificant_only = true\n[gate.max_drop]\npass_rate = 0.05\n')
    _do(f)
    _promote(f)
    _do(f, fail={"c0", "c1"})                                   # 10% drop, but only 2 cases: indistinguishable from noise
    capsys.readouterr()
    assert _gate(f) == 0
    out = capsys.readouterr().out
    assert "pass_rate dropped 0.1000 (allowed 0.0500) but over 20 cases that is within noise (p = 0.500" in out
    _do(f, fail={f"c{i}" for i in range(10)})                   # half the cases flip: unmistakable
    assert _gate(f) == 1 and "p = 0.002" in capsys.readouterr().out
    plain = _gcfg(tmp_path / "plain" if (tmp_path / "plain").mkdir() is None else tmp_path, BASIC)
    _do(plain)
    _promote(plain)
    _do(plain, fail={"c0", "c1"})
    assert _gate(plain) == 1                                    # the fixed threshold alone is fooled by noise


def test_fail_on_significant_drop_catches_a_drop_inside_the_allowance(tmp_path, capsys):
    f = _gcfg(tmp_path, '[gate]\nfail_on_significant_drop = true\n[gate.max_drop]\npass_rate = 0.9\n')
    _do(f)
    _promote(f)
    _do(f, fail={f"c{i}" for i in range(8)})                   # drop 0.4 is within the 0.9 allowance, yet real
    capsys.readouterr()
    assert _gate(f) == 1 and "pass_rate fell significantly" in capsys.readouterr().out


def test_floors_ceilings_and_a_missing_metric_fails_closed(tmp_path, capsys):
    f = _gcfg(tmp_path, '[gate.min]\npass_rate = 0.9\n[gate.max]\nerror_rate = 0.1\n')
    _do(f)
    assert _gate(f) == 0                                        # no baseline needed for floors and ceilings
    _do(f, fail={"c0", "c1", "c2"})
    capsys.readouterr()
    assert _gate(f) == 1 and "pass_rate 0.8500 is below the minimum 0.9000" in capsys.readouterr().out
    typo = _gcfg(tmp_path / "typo" if (tmp_path / "typo").mkdir() is None else tmp_path, '[gate.min]\npass_rat = 0.5\n')
    _do(typo)
    assert _gate(typo) == 1 and "metric 'pass_rat' is missing from the run" in capsys.readouterr().out


def test_tag_metrics_and_their_significance_are_per_slice(tmp_path, capsys):
    f = _gcfg(tmp_path, '[gate]\nsignificant_only = true\n[gate.max_drop]\n"tag.b" = 0.2\n')
    _do(f)
    _promote(f)
    _do(f, fail={f"c{i}" for i in range(10, 20)})               # everything in slice b fails
    capsys.readouterr()
    assert _gate(f) == 1 and "tag.b dropped 1.0000" in capsys.readouterr().out
    _do(f, fail={f"c{i}" for i in range(0, 10)})                # only slice a fails: the b rule is unaffected
    assert _gate(f) == 0


def test_cost_increase_fails_and_warns_by_percentage(tmp_path, capsys):
    f = _gcfg(tmp_path, '[gate.max_increase_pct]\ncost_usd = 25\n[gate.warn_increase_pct]\ncost_usd = 10\n', n=10,
              target='type = "gate_cost_target"')
    COST["per_case"] = 1.0
    run(load_config(f))
    _promote(f)
    COST["per_case"] = 1.2                                        # +20%: warns, does not fail
    run(load_config(f))
    capsys.readouterr()
    assert _gate(f) == 0 and "cost_usd rose 20.0% vs the baseline (allowed 10.0%)" in capsys.readouterr().out
    COST["per_case"] = 1.5                                        # +50%: fails
    run(load_config(f))
    assert _gate(f) == 1 and "cost_usd rose 50.0% vs the baseline (allowed 25.0%)" in capsys.readouterr().out
    COST["per_case"] = 1.0


def test_a_baseline_for_another_dataset_or_split_is_refused_unless_allowed(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    _do(f)
    path = _promote(f)
    with (tmp_path / "c.jsonl").open("a") as fh:
        fh.write('\n{"id": "extra", "input": "z", "expected": "z"}')
    _do(f)
    capsys.readouterr()
    assert _gate(f) == 1 and "different dataset version" in capsys.readouterr().out
    f.write_text(f.read_text().replace("[gate.max_drop]", "[gate]\nallow_dataset_change = true\n[gate.max_drop]"))
    assert _gate(f) == 0
    b = json.loads(path.read_text())
    b["split"] = "dev"
    path.write_text(json.dumps(b))
    assert _gate(f) == 1 and "the baseline is for split 'dev' but this run used 'all'" in capsys.readouterr().out


def test_no_baseline_incomplete_runs_and_flags(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    d = _do(f)
    capsys.readouterr()
    assert _gate(f) == 1 and "no baseline: run `evalharness baseline promote`" in capsys.readouterr().out
    _promote(f)
    m = json.loads((d / "manifest.json").read_text())
    m["status"] = "incomplete"
    (d / "manifest.json").write_text(json.dumps(m))
    assert _gate(f, "--run", str(d)) == 1 and "the run did not complete" in capsys.readouterr().out
    other = tmp_path / "elsewhere.baseline.json"
    other.write_text((tmp_path / "e.baseline.json").read_text())
    (tmp_path / "e.baseline.json").unlink()
    good = _do(f)
    assert _gate(f, "--run", str(good), "--baseline", str(other)) == 0


def test_the_latest_run_of_the_config_is_checked_by_default(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    _do(f)
    _promote(f)
    _do(f, fail={f"c{i}" for i in range(10)})
    bad = _do(f)                                                  # the newest run is healthy again
    capsys.readouterr()
    assert _gate(f) == 0 and bad.name in capsys.readouterr().out


def test_github_actions_annotations(tmp_path, capsys, monkeypatch):
    f = _gcfg(tmp_path, '[gate.min]\npass_rate = 1.1\n')
    _do(f)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    capsys.readouterr()
    assert _gate(f) == 1
    assert "::error::evalharness gate: pass_rate 1.0000 is below the minimum 1.1000" in capsys.readouterr().out


def test_gate_config_validation_and_errors(tmp_path, capsys):
    f = _gcfg(tmp_path, '[gate]\nsignificnt_only = true\nalpha = 2\nallow_dataset_change = "yes"\n[gate.min]\npass_rate = "high"\n')
    assert main(["check", str(f)]) == 2
    err = capsys.readouterr().err
    assert "Did you mean 'significant_only'" in err and "alpha must be a number between 0 and 1" in err
    assert "allow_dataset_change must be true or false" in err and "[gate.min] must map metric names to numbers >= 0" in err
    plain = write_eval(tmp_path / "p" if (tmp_path / "p").mkdir() is None else tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    run(load_config(plain))
    assert main(["gate", str(plain)]) == 2 and "has no [gate] section" in capsys.readouterr().err
    assert main(["gate", str(tmp_path / "nope.toml")]) == 2
    empty = _gcfg(tmp_path / "e2" if (tmp_path / "e2").mkdir() is None else tmp_path, BASIC)
    assert main(["gate", str(empty)]) == 2 and "no finished runs named" in capsys.readouterr().err


def test_a_baseline_from_a_newer_format_is_refused(tmp_path, capsys):
    f = _gcfg(tmp_path, BASIC)
    _do(f)
    path = _promote(f)
    b = json.loads(path.read_text())
    b["format_version"] = 99
    path.write_text(json.dumps(b))
    assert _gate(f) == 2 and "written by a newer evalharness" in capsys.readouterr().err
