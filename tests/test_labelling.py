"""Tests: labelling."""
from helpers import *  # noqa: F401,F403


# ---- human labelling: export / import ----


def test_export_is_blind_by_default_and_roundtrips_unicode(tmp_path, capsys):
    d = _labelled_run(tmp_path)
    assert main(["label", "export", str(d)]) == 0
    rows = _read_sheet(d / "label_sheet.csv")
    assert [r["case_id"] for r in rows] == [f"c{i}" for i in range(6)]
    assert rows[0]["input"] == "café ticket 0" and rows[0]["output"] == "café ticket 0"
    assert "auto_pass" not in rows[0] and "human_pass" in rows[0] and rows[0]["human_pass"] == ""
    assert "automatic verdicts are hidden" in capsys.readouterr().out
    assert main(["label", "export", str(d), "-o", str(d / "v.csv"), "--show-verdicts"]) == 0
    v = _read_sheet(d / "v.csv")
    assert v[0]["auto_pass"] == "yes" and v[1]["auto_pass"] == "no" and v[1]["auto:exact_match"] == "no"


def test_export_refuses_overwrite_and_privacy_runs(tmp_path, capsys):
    d = _labelled_run(tmp_path)
    assert main(["label", "export", str(d)]) == 0
    assert main(["label", "export", str(d)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert main(["label", "export", str(d), "--force"]) == 0
    p = _labelled_run(tmp_path / "priv" if (tmp_path / "priv").mkdir() is None else tmp_path,
                      privacy='[privacy]\nstore = "scores_only"\n')
    assert main(["label", "export", str(p)]) == 2
    assert "nothing to show reviewers" in capsys.readouterr().err


def test_export_neutralises_spreadsheet_formulas_and_skips_errors(tmp_path):
    @register_target("formula")
    class Formula(Target):
        def run(self, case):
            return TargetOutput(error="down") if case.id == "bad" else TargetOutput(output='=HYPERLINK("http://x")')

    f = write_eval(tmp_path, [{"id": "a", "input": "+1", "expected": "-2"}, {"id": "bad", "input": "x", "expected": "y"}],
                   target='type = "formula"')
    _, _, d = run(load_config(f))
    assert main(["label", "export", str(d)]) == 0
    rows = _read_sheet(d / "label_sheet.csv")
    assert len(rows) == 1                                   # the errored attempt has nothing to label
    assert rows[0]["output"].startswith("'=") and rows[0]["input"] == "'+1" and rows[0]["expected"] == "'-2"


def test_export_sampling_is_reproducible_and_balanced(tmp_path):
    d = _labelled_run(tmp_path, n=20)                        # 10 pass, 10 fail
    def ids(args):
        out = d / "s.csv"
        assert main(["label", "export", str(d), "-o", str(out), "--force", *args]) == 0
        return [r["case_id"] for r in _read_sheet(out)]
    a, b = ids(["--sample", "6", "--seed", "1"]), ids(["--sample", "6", "--seed", "1"])
    assert a == b and len(a) == 6 and ids(["--sample", "6", "--seed", "2"]) != a
    bal = ids(["--sample", "6", "--balance"])
    assert sum(int(i[1:]) % 2 == 0 for i in bal) == 3        # 3 passes (even), 3 failures
    assert len(ids(["--sample", "500"])) == 20               # sample larger than the run: take everything


def test_import_reads_verdict_words_skips_blanks_and_records_output_hash(tmp_path, capsys):
    from eval_uate_me.labels import load_labels, output_hash
    d = _labelled_run(tmp_path, n=4)
    main(["label", "export", str(d)])
    sheet = d / "label_sheet.csv"
    _fill(sheet, ["Yes", " NO ", "", "pass"], labeler="ana")
    capsys.readouterr()
    assert main(["label", "import", str(d), str(sheet)]) == 0
    assert "imported 3 labels (0 replaced earlier ones, 1 blank rows skipped) from ana" in capsys.readouterr().out
    labels = load_labels(d)
    assert labels[("c0", 0)]["ana"]["human_pass"] is True and labels[("c1", 0)]["ana"]["human_pass"] is False
    assert ("c2", 0) not in labels and labels[("c3", 0)]["ana"]["human_pass"] is True
    assert labels[("c0", 0)]["ana"]["output_sha256"] == output_hash("café ticket 0")


def test_import_is_all_or_nothing_with_clear_line_numbers(tmp_path, capsys):
    d = _labelled_run(tmp_path, n=4)
    main(["label", "export", str(d)])
    sheet = d / "label_sheet.csv"
    _fill(sheet, ["yes", "maybe", "no", "yes"])
    rows = _read_sheet(sheet)
    rows[3]["case_id"] = "ghost"
    import csv
    with open(sheet, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    assert main(["label", "import", str(d), str(sheet)]) == 2
    err = capsys.readouterr().err
    assert "nothing was imported" in err and "line 3: 'maybe' is not a verdict" in err
    assert "line 5: no result for case 'ghost'" in err and "keep case_id as text" in err
    assert not (d / "labels.jsonl").exists()                 # the valid rows were not half-imported


def test_import_multiple_labelers_replacement_and_bad_sheets(tmp_path, capsys):
    from eval_uate_me.labels import load_labels
    d = _labelled_run(tmp_path, n=2)
    main(["label", "export", str(d)])
    sheet = d / "label_sheet.csv"
    _fill(sheet, ["yes", "no"])
    assert main(["label", "import", str(d), str(sheet), "--labeler", "ana"]) == 0
    assert main(["label", "import", str(d), str(sheet), "--labeler", "ben"]) == 0
    _fill(sheet, ["no", "no"])
    capsys.readouterr()
    assert main(["label", "import", str(d), str(sheet), "--labeler", "ana"]) == 0
    assert "2 replaced earlier ones" in capsys.readouterr().out
    labels = load_labels(d)
    assert labels[("c0", 0)]["ana"]["human_pass"] is False and labels[("c0", 0)]["ben"]["human_pass"] is True
    dup = d / "dup.csv"
    dup.write_text("case_id,attempt,human_pass\nc0,0,yes\nc0,0,no\n", encoding="utf-8")
    assert main(["label", "import", str(d), str(dup)]) == 2 and "labelled twice" in capsys.readouterr().err
    bad = d / "bad.csv"
    bad.write_text("id,verdict\nc0,yes\n", encoding="utf-8")
    assert main(["label", "import", str(d), str(bad)]) == 2 and "missing column(s): case_id, human_pass" in capsys.readouterr().err
    assert main(["label", "import", str(d), str(d / "nope.csv")]) == 2


def test_import_works_for_privacy_runs_using_a_self_made_sheet(tmp_path):
    from eval_uate_me.labels import load_labels
    d = _labelled_run(tmp_path, n=2, privacy='[privacy]\nstore = "scores_only"\n')
    sheet = tmp_path / "mine.csv"
    sheet.write_text("case_id,human_pass,labeler\nc0,yes,ana\nc1,no,ana\n", encoding="utf-8")
    assert main(["label", "import", str(d), str(sheet)]) == 0
    assert load_labels(d)[("c1", 0)]["ana"]["human_pass"] is False


# ---- calibration against human labels ----


def test_calibrate_uses_labels_and_reports_hand_computed_numbers(tmp_path, capsys):
    from eval_uate_me.calibration import calibrate
    d = _labelled_run(tmp_path, n=8)                 # auto: even cases pass, odd cases fail
    human = ["yes", "yes", "yes", "no", "yes", "no", "yes", "no"]   # differs from auto only on c1
    _sheet_with(d, human, "ana", "a.csv")
    r = calibrate(d, "overall")
    assert r["source"] == "labels.jsonl" and r["n"] == 8
    assert r["confusion"] == {"tp": 4, "fp": 0, "fn": 1, "tn": 3}
    assert r["agreement"] == 0.875 and abs(r["kappa"] - 0.75) < 1e-9
    assert r["precision"] == 1.0 and r["recall"] == 0.8 and r["specificity"] == 1.0
    lo, hi = r["ci95"]["kappa"]
    assert -1 <= lo <= hi <= 1
    assert any("only 8 labelled attempts" in w for w in r["warnings"])
    assert calibrate(d, "exact_match")["confusion"] == r["confusion"]      # one grader == overall here
    capsys.readouterr()
    assert main(["calibrate", str(d), "--grader", "overall", "--json", str(d / "cal.json")]) == 0
    out = capsys.readouterr().out
    assert "agreement=88% kappa=0.75" in out and "precision" in out
    assert json.loads((d / "cal.json").read_text())["n"] == 8


def test_calibrate_majority_ties_and_inter_labeler_agreement(tmp_path):
    from eval_uate_me.calibration import calibrate
    d = _labelled_run(tmp_path, n=4)
    _sheet_with(d, ["yes", "no", "yes", "no"], "ana", "a.csv")
    _sheet_with(d, ["yes", "yes", "yes", "yes"], "ben", "b.csv")      # ben disagrees on c1, c3
    _sheet_with(d, ["yes", "no", "yes", "yes"], "cho", "c.csv")       # cho sides with ana on c1, ben on c3
    r = calibrate(d, "overall")
    # c0,c2: all yes. c1: ana no, ben yes, cho no -> no. c3: ana no, ben yes, cho yes -> yes (auto says no)
    assert r["n"] == 4 and r["disputed"] == 0 and r["labelers"] == ["ana", "ben", "cho"]
    assert r["confusion"] == {"tp": 2, "fp": 0, "fn": 1, "tn": 1}
    pairs = {(p["a"], p["b"]): p for p in r["labeler_agreement"]["pairs"]}
    assert pairs[("ana", "ben")]["agreement"] == 0.5 and pairs[("ana", "cho")]["agreement"] == 0.75
    # a 1-1 tie between two reviewers sets the attempt aside instead of guessing
    d2 = _labelled_run(tmp_path / "t" if (tmp_path / "t").mkdir() is None else tmp_path, n=4)
    _sheet_with(d2, ["yes", "no", "yes", "no"], "ana", "a.csv")
    _sheet_with(d2, ["yes", "yes", "yes", "no"], "ben", "b.csv")
    r2 = calibrate(d2, "overall")
    assert r2["disputed"] == 1 and r2["n"] == 3


def test_calibrate_ignores_stale_labels_and_needs_labels(tmp_path):
    from eval_uate_me.calibration import calibrate
    d = _labelled_run(tmp_path, n=4)
    with pytest.raises(ValueError, match="no labelled attempts"):
        calibrate(d, "overall")
    _sheet_with(d, ["yes", "no", "yes", "no"], "ana", "a.csv")
    # the output of c0 changes after it was labelled (e.g. the case was re-run): its label must not apply
    rows = [json.loads(l) for l in (d / "results.jsonl").read_text().splitlines()]
    rows[0]["result"]["output"] = "something else"
    (d / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    r = calibrate(d, "overall")
    assert r["n"] == 3 and r["stale"] == 1 and any("output they judged has changed" in w for w in r["warnings"])
    with pytest.raises(ValueError, match="no labelled attempts"):
        calibrate(d, "no_such_grader")


def test_calibrate_still_reads_metadata_human_pass_without_labels(tmp_path):
    from eval_uate_me.calibration import calibrate
    cases = [{"id": str(i), "input": "x", "expected": "x", "metadata": {"human_pass": h}}
             for i, h in enumerate([True, True, False, False])]
    _, _, d = run(load_config(write_eval(tmp_path, cases)))
    r = calibrate(d, "exact_match")
    assert r["source"] == "metadata.human_pass" and r["agreement"] == 0.5 and r["kappa"] == 0.0


def test_cohen_kappa_edges():
    from eval_uate_me.stats import cohen_kappa
    assert cohen_kappa([True, False, True], [True, False, True]) == 1.0
    assert cohen_kappa([True, True], [True, True]) == 1.0           # both always yes: perfect agreement, no spread
    assert abs(cohen_kappa([True, False], [False, True]) + 1.0) < 1e-9   # total disagreement
    with pytest.raises(ValueError):
        cohen_kappa([], [])


# ---- disagreements ----


def test_disagreements_lists_false_pass_false_fail_and_reviewer_ties(tmp_path, capsys):
    from eval_uate_me.calibration import disagreements
    d = _labelled_run(tmp_path, n=4)                    # auto: c0,c2 pass; c1,c3 fail
    sheet = d / "a.csv"
    main(["label", "export", str(d), "-o", str(sheet)])
    import csv
    rows = _read_sheet(sheet)
    for r, v in zip(rows, ["no", "yes", "yes", "no"]):  # c0: grader passed but human says fail; c1: grader failed, human pass
        r["human_pass"] = v
        r["labeler"] = "ana"
    rows[0]["notes"] = "output is fine but misses the units"
    with open(sheet, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    assert main(["label", "import", str(d), str(sheet)]) == 0
    _sheet_with(d, ["yes", "yes", "yes", "no"], "ben", "b.csv")     # ben vs ana: tie on c0 only
    items = disagreements(d, "overall")
    kinds = {(i["case_id"], i["kind"]) for i in items}
    assert kinds == {("c0", "reviewers_disagree"), ("c1", "false_fail")}   # c1: ana yes + ben yes vs grader fail
    assert next(i for i in items if i["case_id"] == "c0")["notes"] == {"ana": "output is fine but misses the units"}
    capsys.readouterr()
    assert main(["label", "disagreements", str(d), "--show-output"]) == 0
    out = capsys.readouterr().out
    assert "2 disagreement(s)" in out and "grader FAILED, humans said pass" in out
    assert "note (ana): output is fine but misses the units" in out and "exact_match: expected 'other'" in out
    assert "output: café ticket 1" in out


def test_disagreements_false_pass_comes_first_and_none_is_reported(tmp_path, capsys):
    from eval_uate_me.calibration import disagreements
    d = _labelled_run(tmp_path, n=4)
    _sheet_with(d, ["no", "yes", "yes", "no"], "ana", "a.csv")
    items = disagreements(d, "exact_match")
    assert [(i["case_id"], i["kind"]) for i in items] == [("c0", "false_pass"), ("c1", "false_fail")]
    agree = _labelled_run(tmp_path / "ok" if (tmp_path / "ok").mkdir() is None else tmp_path, n=2)
    _sheet_with(agree, ["yes", "no"], "ana", "a.csv")
    capsys.readouterr()
    assert main(["label", "disagreements", str(agree)]) == 0
    assert "no disagreements" in capsys.readouterr().out


# ---- carrying labels across runs ----


def test_carry_copies_labels_only_where_the_output_is_identical(tmp_path, capsys):
    from eval_uate_me.labels import load_labels
    a, b = _two_label_runs(tmp_path)
    _sheet_with(a, ["yes", "yes", "no", "yes", "no", "yes"], "ana", "a.csv")
    rows = [json.loads(l) for l in (b / "results.jsonl").read_text().splitlines()]
    rows[2]["result"]["output"] = "different text now"                    # c2's output changed
    rows[5]["case"]["id"] = "renamed"                                       # c5 is gone from the new run
    (b / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    capsys.readouterr()
    assert main(["label", "carry", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "carried 4 labels" in out and "2 not carried" in out
    got = load_labels(b)
    assert sorted(k[0] for k in got) == ["c0", "c1", "c3", "c4"]
    lab = got[("c3", 0)]["ana"]
    assert lab["human_pass"] is True and lab["carried_from"] == a.name and lab["labeled_at"]
    capsys.readouterr()
    assert main(["label", "carry", str(a), str(b)]) == 0                    # idempotent: nothing new to copy
    assert "carried 0 labels" in capsys.readouterr().out
    from eval_uate_me.calibration import calibrate
    assert calibrate(b, "overall")["n"] == 4                                # carried labels are usable at once


def test_carry_never_overrides_and_skips_labelled_in_export(tmp_path, capsys):
    from eval_uate_me.labels import load_labels
    a, b = _two_label_runs(tmp_path, n=4)
    _sheet_with(a, ["yes", "yes", "yes", "yes"], "ana", "a.csv")
    _sheet_with(a, ["no", "no", "no", "no"], "ben", "b.csv")
    _sheet_with(b, ["no", "no", "no", "no"], "ana", "x.csv")                 # ana already labelled b herself
    assert main(["label", "carry", str(a), str(b)]) == 0
    got = load_labels(b)
    assert all(got[(f"c{i}", 0)]["ana"]["human_pass"] is False for i in range(4))   # her own labels kept
    assert all(got[(f"c{i}", 0)]["ben"]["human_pass"] is False and "carried_from" in got[(f"c{i}", 0)]["ben"] for i in range(4))
    c = _labelled_run(tmp_path / "r3" if (tmp_path / "r3").mkdir() is None else tmp_path, n=4)
    _sheet_with(a, ["yes", "yes", "yes", "yes"], "cho", "c.csv")
    assert main(["label", "carry", str(a), str(c)]) == 0
    capsys.readouterr()
    assert main(["label", "export", str(c), "-o", str(c / "rest.csv"), "--unlabelled-only"]) == 2   # all four carried
    assert "everything is already labelled" in capsys.readouterr().err
    d = _labelled_run(tmp_path / "r4" if (tmp_path / "r4").mkdir() is None else tmp_path, n=4)
    _sheet_with(d, ["yes", "", "", ""], "ana", "p.csv")                      # only c0 labelled
    assert main(["label", "export", str(d), "-o", str(d / "rest.csv"), "--unlabelled-only"]) == 0
    assert [r["case_id"] for r in _read_sheet(d / "rest.csv")] == ["c1", "c2", "c3"]
    assert "wrote 3 of 3 attempts" in capsys.readouterr().out


def test_carry_maps_to_every_repeat_with_the_same_output_and_refuses_bad_input(tmp_path, capsys):
    from eval_uate_me.labels import load_labels
    cases = [{"id": "c0", "input": "x", "expected": "x"}]
    f = write_eval(tmp_path / "rep" if (tmp_path / "rep").mkdir() is None else tmp_path, cases)
    f.write_text(f.read_text() + "repeats = 3\n")
    _, _, many = run(load_config(f))
    a = _labelled_run(tmp_path / "one" if (tmp_path / "one").mkdir() is None else tmp_path, n=1)
    (a / "results.jsonl").write_text((a / "results.jsonl").read_text().replace("café ticket 0", "x"))   # same output "x" as `many`
    rows = [json.loads(l) for l in (a / "results.jsonl").read_text().splitlines()]
    rows[0]["case"]["id"] = "c0"
    (a / "results.jsonl").write_text(json.dumps(rows[0], ensure_ascii=False) + "\n")
    _sheet_with(a, ["yes"], "ana", "s.csv")
    assert main(["label", "carry", str(a), str(many)]) == 0
    assert sorted(k for k in load_labels(many)) == [("c0", 0), ("c0", 1), ("c0", 2)]
    capsys.readouterr()
    assert main(["label", "carry", str(a), str(a)]) == 2 and "same directory" in capsys.readouterr().err
    fresh = _labelled_run(tmp_path / "fresh" if (tmp_path / "fresh").mkdir() is None else tmp_path, n=2)
    assert main(["label", "carry", str(fresh), str(many)]) == 2 and "has no labels" in capsys.readouterr().err
    priv = _labelled_run(tmp_path / "pv" if (tmp_path / "pv").mkdir() is None else tmp_path, n=2,
                         privacy='[privacy]\nstore = "scores_only"\n')
    assert main(["label", "carry", str(a), str(priv)]) == 2 and "no way to tell whether an output is identical" in capsys.readouterr().err
