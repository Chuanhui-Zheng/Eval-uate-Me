"""Tests: data governance."""
from helpers import *  # noqa: F401,F403


# ---- dataset provenance ----


def test_meta_loads_unquoted_dates_and_reports_every_problem(tmp_path):
    from evalharness.config import ConfigError
    from evalharness.dataset_meta import load_meta
    m = load_meta(_meta(tmp_path, FULL_META))
    assert m.retrieved == "2026-09-15" and m.version == "1.0" and m.contains_personal_data is False and m.sha256
    with pytest.raises(ConfigError) as e:
        load_meta(_meta(tmp_path, 'licence = "x"\nversion = 1.0\nretrieved = "last week"\ncontains_personal_data = "no"\n'))
    msg = " | ".join(e.value.problems)
    assert "unknown key 'licence'. Did you mean 'license'" in msg
    assert "'version' must be text, got 1.0 (put it in quotes)" in msg
    assert "'retrieved' must be a date like 2026-09-15" in msg and "'contains_personal_data' must be true or false" in msg
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_meta(_meta(tmp_path, "= = ="))
    with pytest.raises(ConfigError, match="not found"):
        load_meta(tmp_path / "nope.toml")


def test_find_meta_by_convention_and_config_override(tmp_path):
    from evalharness.dataset_meta import find_meta_path
    (tmp_path / "d.jsonl").write_text("{}")
    assert find_meta_path(tmp_path / "d.jsonl") is None
    p = _meta(tmp_path, FULL_META)
    assert find_meta_path(tmp_path / "d.jsonl") == p
    other = _meta(tmp_path, FULL_META, "other.toml")
    assert find_meta_path(tmp_path / "d.jsonl", other) == other


def test_lint_metadata_findings(tmp_path):
    from datetime import date
    from evalharness.dataset_meta import load_meta
    from evalharness.lint import lint
    clean = [Case(str(i), f"question {i}", f"answer{i % 7}", {"tags": ["t"]}) for i in range(40)]
    assert [f.code for f in lint(clean, check_meta=True)] == ["no_metadata"]
    ok = load_meta(_meta(tmp_path, FULL_META))
    assert lint(clean, check_meta=True, meta=ok, privacy_store="full", today=date(2026, 10, 1)) == []

    bare = load_meta(_meta(tmp_path, 'name = "x"\n', "b.meta.toml"))
    codes = {f.code: f for f in lint(clean, check_meta=True, meta=bare)}
    assert "version, source, retrieved, license" in codes["incomplete_metadata"].message
    assert "personal_data_undeclared" in codes

    risky = load_meta(_meta(tmp_path, FULL_META.replace("= false", "= true").replace("CC0-1.0", "dbGaP controlled access"), "r.meta.toml"))
    codes = {f.code for f in lint(clean, check_meta=True, meta=risky, privacy_store="full")}
    assert {"personal_data_without_privacy_mode", "restrictive_license"} <= codes
    assert "personal_data_without_privacy_mode" not in {f.code for f in lint(clean, check_meta=True, meta=risky, privacy_store="scores_only")}

    old = lint(clean, check_meta=True, meta=ok, today=date(2028, 3, 1))
    assert [f.code for f in old] == ["old_snapshot"] and old[0].level == "info"


def test_lint_flags_restricted_data_that_git_would_publish(tmp_path):
    import subprocess
    from evalharness.dataset_meta import load_meta
    from evalharness.lint import lint
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    data = tmp_path / "d.jsonl"
    data.write_text('{"id":"1","input":"a","expected":"a"}')
    meta = load_meta(_meta(tmp_path, FULL_META.replace("redistributable = true", "redistributable = false")))
    cases = [Case("1", "a", "a")]
    codes = lambda: {f.code for f in lint(cases, check_meta=True, meta=meta, dataset_path=data)}   # noqa: E731
    assert "restricted_data_not_ignored" in codes()                         # untracked but not ignored
    (tmp_path / ".gitignore").write_text("d.jsonl\n")
    assert not ({"restricted_data_not_ignored", "restricted_data_tracked"} & codes())   # properly ignored
    (tmp_path / ".gitignore").write_text("")
    subprocess.run(["git", "add", "d.jsonl"], cwd=tmp_path, check=True)
    assert "restricted_data_tracked" in codes()                             # already staged: the worst case


def test_run_records_metadata_and_bad_metadata_stops_before_any_run(tmp_path, capsys):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    _meta(tmp_path, FULL_META, "c.meta.toml")
    results, _, d = run(load_config(f))
    m = json.loads((d / "manifest.json").read_text())
    assert m["dataset_meta"]["name"] == "demo" and m["dataset_meta"]["license"] == "CC0-1.0"
    capsys.readouterr()
    assert main(["show", str(d)]) == 0
    assert "dataset: demo v1.0 | source: hand written | retrieved: 2026-09-15 | licence: CC0-1.0" in capsys.readouterr().out
    assert "demo v1.0, CC0-1.0" in (d / "report.html").read_text()
    assert main(["check", str(f)]) == 0 and "dataset metadata: demo v1.0, licence CC0-1.0" in capsys.readouterr().out

    _meta(tmp_path, 'licence = "x"\n', "c.meta.toml")
    runs_before = len(list((tmp_path / "runs").iterdir()))
    assert main(["run", str(f)]) == 2 and "unknown key 'licence'" in capsys.readouterr().err
    assert len(list((tmp_path / "runs").iterdir())) == runs_before          # no new run directory was created


def test_config_dataset_meta_override_and_cli_lint(tmp_path, capsys):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    elsewhere = _meta(tmp_path, FULL_META, "provenance.toml")
    f.write_text('dataset_meta = "provenance.toml"\n' + f.read_text())
    assert load_config(f).dataset_meta == elsewhere
    assert main(["lint", str(f), "--strict"]) == 1                    # one case: small_dataset still warns
    out = capsys.readouterr().out
    assert "no_metadata" not in out and "small_dataset" in out
    f.write_text(f.read_text().replace("provenance.toml", "missing.toml"))
    assert main(["check", str(f)]) == 2 and "dataset_meta file not found" in capsys.readouterr().err
    (tmp_path / "bare.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    assert main(["lint", str(tmp_path / "bare.jsonl")]) == 0
    assert "no_metadata" in capsys.readouterr().out


# ---- dev / held-out splits ----


def test_split_assignment_is_stable_reproducible_and_roughly_proportional():
    from evalharness.splits import case_split
    cases = [Case(f"c{i}", "q") for i in range(1000)]
    first = {c.id: case_split(c, 0.3, "v1") for c in cases}
    assert first == {c.id: case_split(c, 0.3, "v1") for c in cases}                     # reproducible
    assert 0.25 < sum(v == "dev" for v in first.values()) / 1000 < 0.35                 # about 30% dev
    extra = [Case(f"new{i}", "q") for i in range(50)]
    assert all(case_split(c, 0.3, "v1") == first[c.id] for c in cases)                  # adding cases moves nothing
    assert [case_split(c, 0.3, "v1") for c in extra] == [case_split(c, 0.3, "v1") for c in extra]
    other = {c.id: case_split(c, 0.3, "v2") for c in cases}
    assert other != first                                                              # a new salt draws a new split
    assert case_split(Case("x", "q"), None) is None                                    # no config: unassigned


def test_explicit_split_wins_and_is_validated():
    from evalharness.config import ConfigError
    from evalharness.splits import case_split, select, split_cases
    forced = Case("a", "q", metadata={"split": "heldout"})
    assert all(case_split(forced, 0.99999, salt) == "heldout" for salt in ("", "x", "y"))
    with pytest.raises(ConfigError, match="metadata.split must be one of"):
        case_split(Case("a", "q", metadata={"split": "train"}), 0.3)
    with pytest.raises(ConfigError, match="have no split"):
        split_cases([Case("a", "q"), Case("b", "q", metadata={"split": "dev"})], None)
    assert select([Case("a", "q")], "all", None) == [Case("a", "q")]                  # "all" needs no split info
    with pytest.raises(ConfigError, match="has no cases"):
        select([Case("a", "q", metadata={"split": "dev"})], "heldout", None)


def test_split_config_validation(tmp_path, capsys):
    base = 'dataset = "c.jsonl"\n[target]\ntype = "echo"\n[[graders]]\ntype = "exact_match"\n'
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    for bad, msg in (('[split]\ndev_fraction = 1.2\n', "between 0 and 1"), ('[split]\ndev_fraction = "0.3"\n', "between 0 and 1"),
                     ('[split]\nsalts = "x"\n', "Did you mean 'salt'"), ('[split]\nsalt = 3\n', "salt must be text")):
        f = tmp_path / "e.toml"
        f.write_text(base + bad)
        assert main(["check", str(f)]) == 2 and msg in capsys.readouterr().err
    f.write_text(base + '[split]\ndev_fraction = 0.3\nsalt = "v1"\n')
    cfg = load_config(f)
    assert cfg.split_dev_fraction == 0.3 and cfg.split_salt == "v1"


def test_split_command_counts_and_exports_without_overwriting(tmp_path, capsys):
    f = _split_cfg(tmp_path, extra='[split]\ndev_fraction = 0.5\nsalt = "t"\n')
    assert main(["split", str(f)]) == 0
    out = capsys.readouterr().out
    assert "dev" in out and "heldout" in out and "0 case(s) set metadata.split explicitly" in out
    assert main(["split", str(f), "--export", str(tmp_path / "parts")]) == 0
    dev = [json.loads(l) for l in (tmp_path / "parts" / "dev.jsonl").read_text().splitlines()]
    held = [json.loads(l) for l in (tmp_path / "parts" / "heldout.jsonl").read_text().splitlines()]
    assert len(dev) + len(held) == 40 and not {d["id"] for d in dev} & {h["id"] for h in held}
    assert dev[0]["input"] == f"q{dev[0]['id'][1:]}" and dev[0]["expected"] == dev[0]["input"]   # full records
    assert main(["split", str(f), "--export", str(tmp_path / "parts")]) == 2                    # no overwrite
    assert "refusing to overwrite" in capsys.readouterr().err
    assert main(["split", str(f), "--export", str(tmp_path / "parts"), "--only", "dev", "--force"]) == 0
    (tmp_path / "only").mkdir()
    assert main(["split", str(f), "--export", str(tmp_path / "only"), "--only", "heldout"]) == 0
    assert [p.name for p in (tmp_path / "only").iterdir()] == ["heldout.jsonl"]


def test_split_command_requires_split_information(tmp_path, capsys):
    f = _split_cfg(tmp_path)
    assert main(["split", str(f)]) == 2 and "have no split" in capsys.readouterr().err


def test_lint_split_findings(tmp_path):
    from evalharness.lint import lint
    big = [Case(f"c{i}", f"question {i}", f"a{i % 9}", {"tags": ["t"], "split": "dev" if i < 20 else "heldout"})
           for i in range(40)]
    assert lint(big) == []
    small = big[:22]                                           # 20 dev, 2 heldout
    codes = {f.code: f for f in lint(small)}
    assert "heldout" in codes["split_too_small"].message and "2 case(s)" in codes["split_too_small"].message
    leaky = big + [Case("dup", "question 0", "a0", {"tags": ["t"], "split": "heldout"})]
    assert {"split_leakage"} <= {f.code for f in lint(leaky)}
    mixed = big[:30] + [Case("loose", "zzz", "z", {"tags": ["t"]})]
    assert "split_unassigned" in {f.code for f in lint(mixed)}
    assert not any(f.code.startswith("split_") for f in lint([Case(str(i), f"q{i}", "x", {"tags": ["t"]}) for i in range(40)]))
    hashed = [Case(f"c{i}", f"question {i}", f"a{i % 9}", {"tags": ["t"]}) for i in range(60)]
    assert not any(f.code == "split_unassigned" for f in lint(hashed, split_dev_fraction=0.5, split_salt="x"))


# ---- running a split, held-out looks ----


def test_default_is_dev_when_splits_exist_and_all_otherwise(tmp_path, capsys):
    from evalharness.splits import split_cases
    f = _split_run_cfg(tmp_path)
    cfg = load_config(f)
    parts = split_cases(load_cases(cfg.dataset), cfg.split_dev_fraction, cfg.split_salt)
    results, summary, d = run(cfg)
    assert _ids(results) == {c.id for c in parts["dev"]} and summary["split"] == "dev"
    assert "running the dev split" in capsys.readouterr().err
    assert json.loads((d / "manifest.json").read_text())["split"] == "dev"
    assert not (tmp_path / "runs" / "heldout_log.jsonl").exists()                # dev runs are not looks
    plain, s2, _ = run(load_config(write_eval(tmp_path / "p" if (tmp_path / "p").mkdir() is None else tmp_path,
                                             [{"id": "1", "input": "a", "expected": "a"}])))
    assert len(plain) == 1 and s2["split"] == "all" and "heldout_looks" not in s2


def test_heldout_looks_are_counted_per_dataset_version(tmp_path, capsys):
    from evalharness.splits import split_cases
    f = _split_run_cfg(tmp_path)
    cfg = load_config(f)
    held = {c.id for c in split_cases(load_cases(cfg.dataset), 0.5, "t")["heldout"]}
    r1, s1, d1 = run(cfg, split="heldout")
    assert _ids(r1) == held and s1["heldout_looks"] == 1
    assert "already been evaluated" not in capsys.readouterr().err
    _, s2, d2 = run(load_config(f), split="heldout")
    assert s2["heldout_looks"] == 2 and "already been evaluated 1 time(s)" in capsys.readouterr().err
    assert json.loads((d2 / "manifest.json").read_text())["heldout_looks"] == 2
    _, s3, _ = run(load_config(f), split="all")                                  # "all" includes held-out: a look
    assert s3["heldout_looks"] == 3
    log = [json.loads(l) for l in (tmp_path / "runs" / "heldout_log.jsonl").read_text().splitlines()]
    assert [l["split"] for l in log] == ["heldout", "heldout", "all"] and log[0]["run"] == d1.name
    run(load_config(f), split="dev")
    assert len((tmp_path / "runs" / "heldout_log.jsonl").read_text().splitlines()) == 3
    with (tmp_path / "c.jsonl").open("a") as fh:                                # a new dataset version starts over
        fh.write('\n{"id": "extra", "input": "z", "expected": "z"}')
    _, s4, _ = run(load_config(f), split="heldout")
    assert s4["heldout_looks"] == 1


def test_console_and_report_show_split_and_look(tmp_path, capsys):
    f = _split_run_cfg(tmp_path)
    assert main(["run", str(f), "--split", "heldout"]) == 0
    out = capsys.readouterr().out
    assert "split: heldout" in out and "held-out look #1" in out
    assert main(["run", str(f), "--split", "heldout"]) == 0
    assert "repeated looks make this score less independent" in capsys.readouterr().out
    d = sorted((tmp_path / "runs").glob("t-*"))[-1]
    assert "heldout (look #2)" in (d / "report.html").read_text()
    capsys.readouterr()
    assert main(["show", str(d)]) == 0 and "heldout_looks: 2" in capsys.readouterr().out


def test_split_flag_errors_and_resume_must_match_split(tmp_path, capsys):
    plain = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    assert main(["run", str(plain), "--split", "dev"]) == 2
    assert "have no split" in capsys.readouterr().err
    f = _split_run_cfg(tmp_path / "s" if (tmp_path / "s").mkdir() is None else tmp_path)
    _, _, d = run(load_config(f), split="dev")
    assert main(["run", str(f), "--split", "heldout", "--resume", str(d)]) == 2
    assert "used the 'dev' split but you asked for 'heldout'" in capsys.readouterr().err
    assert main(["run", str(f), "--split", "dev", "--resume", str(d)]) == 0
    _, _, h = run(load_config(f), split="heldout")
    before = (tmp_path / "s" / "runs" / "heldout_log.jsonl").read_text()
    run(load_config(f), split="heldout", resume=h)                              # resuming is not a new look
    assert (tmp_path / "s" / "runs" / "heldout_log.jsonl").read_text() == before
    assert json.loads((h / "manifest.json").read_text())["heldout_looks"] == 1


def test_compare_warns_when_splits_differ(tmp_path, capsys):
    f = _split_run_cfg(tmp_path)
    _, _, dev = run(load_config(f), split="dev")
    _, _, held = run(load_config(f), split="heldout")
    capsys.readouterr()
    main(["compare", str(dev), str(held)])
    out = capsys.readouterr().out
    assert "different splits (dev vs heldout)" in out
    main(["compare", str(dev), str(dev)])
    assert "different splits" not in capsys.readouterr().out
