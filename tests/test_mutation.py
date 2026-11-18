"""Tests: output-level mutation operators, operator mutants, sensitivity curves and automatic mutation."""
from helpers import *  # noqa: F401,F403

from eval_uate_me import ConfigError, Grader, Score
from eval_uate_me.mutation import (MutatedTarget, apply_operator, discover_sites, generate_mutants, parse_path, resolve, selected)

REAL_CALLS = {"n": 0}
LABELS = ["alpha", "bravo", "charlie"]


@register_target("mut_target")
class MutTarget(Target):
    """Returns a structured report. Only `items` and `label` are ever checked by the graders below."""
    network = False

    def run(self, case):
        REAL_CALLS["n"] += 1
        return TargetOutput(output={"items": [{"id": 1, "extra": "e1"}, {"id": 2, "extra": "e2"}, {"id": 3, "extra": "e3"}],
                                    "label": case.expected["label"], "n": 3, "note": "free text", "meta": {"flag": True}})


@register_grader("m_items")
class MItems(Grader):
    name = "m_items"
    selftest = "guardrail"

    def grade(self, case, out):
        o = out.output
        ok = isinstance(o, dict) and isinstance(o.get("items"), list) and len(o["items"]) == 3 and all("id" in i for i in o["items"])
        return Score(self.name, 1.0 if ok else 0.0, ok, "" if ok else "items wrong")


@register_grader("m_label")
class MLabel(Grader):
    name = "m_label"
    selftest = "guardrail"

    def grade(self, case, out):
        ok = isinstance(out.output, dict) and out.output.get("label") == case.expected["label"]
        return Score(self.name, 1.0 if ok else 0.0, ok, "" if ok else "label wrong")


def _cfg(tmp_path, mutants_toml="", n=40, graders='[[graders]]\ntype = "m_items"\n[[graders]]\ntype = "m_label"'):
    cases = [{"id": f"c{i:02d}", "input": f"q{i}", "expected": {"label": LABELS[i % 3]}} for i in range(n)]
    f = write_eval(tmp_path, cases, target='type = "mut_target"', graders=graders)
    f.write_text(f.read_text().replace("[run]", mutants_toml + "[run]"))
    return f


def _mut(name, operator, path="", extra=""):
    return f'[[mutants]]\nname = "{name}"\noperator = "{operator}"\npath = "{path}"\n{extra}'


def _me(f, *args):
    return main(["meta-eval", str(f), *args])


def _status(data):
    return {m["name"]: m["status"] for m in data["mutants"]}


SAMPLE = {"n": 3, "label": "alpha", "flag": True, "items": [{"a": 1, "b": "p"}, {"a": 2, "b": "q"}]}


def test_paths_address_keys_lists_and_wildcards():
    assert parse_path("") == [] and parse_path("a.b[*].c[0]") == [("a", None), ("b", "*"), ("c", 0)]
    with pytest.raises(ValueError, match="bad path segment"):
        parse_path("a[x]")
    locs = resolve(SAMPLE, "items[*].a")
    assert [c[k] for c, k in locs] == [1, 2]
    assert resolve(SAMPLE, "items[1].b")[0][0]["b"] == "q" and resolve(SAMPLE, "nope") == [] and resolve(SAMPLE, "items[9]") == []


@pytest.mark.parametrize("operator, path, params, check", [
    ("drop_item", "items", {}, lambda o: o["items"] == [{"a": 2, "b": "q"}]),
    ("drop_item", "items", {"which": "last"}, lambda o: o["items"] == [{"a": 1, "b": "p"}]),
    ("duplicate_item", "items", {}, lambda o: len(o["items"]) == 3 and o["items"][1] == o["items"][0]),
    ("reverse_list", "items", {}, lambda o: o["items"][0]["a"] == 2),
    ("drop_key", "items[*].a", {}, lambda o: all("a" not in i for i in o["items"])),
    ("drop_key", "label", {}, lambda o: "label" not in o),
    ("null_value", "label", {}, lambda o: o["label"] is None),
    ("empty_value", "label", {}, lambda o: o["label"] == ""),
    ("empty_value", "items", {}, lambda o: o["items"] == []),
    ("truncate_text", "label", {}, lambda o: o["label"] == "al"),
    ("replace_text", "label", {"pattern": "a", "replacement": "o"}, lambda o: o["label"] == "olpho"),
    ("perturb_number", "n", {}, lambda o: o["n"] == 4),
    ("perturb_number", "n", {"factor": 2}, lambda o: o["n"] == 6),
    ("perturb_number", "items[*].a", {"delta": 10}, lambda o: [i["a"] for i in o["items"]] == [11, 12]),
    ("flip_bool", "flag", {}, lambda o: o["flag"] is False),
    ("empty_output", "", {}, lambda o: o is None),
])
def test_each_operator_changes_what_it_says_and_never_touches_the_original(operator, path, params, check):
    import copy
    before = copy.deepcopy(SAMPLE)
    new, changed = apply_operator(SAMPLE, operator, path, params)
    assert changed and check(new)
    assert SAMPLE == before                                              # the recorded output is never mutated in place


def test_operators_report_no_change_when_there_is_nothing_to_damage():
    for operator, path in (("drop_item", "nope"), ("drop_key", "nope"), ("flip_bool", "label"), ("perturb_number", "label"),
                           ("truncate_text", "n"), ("reverse_list", "label"), ("drop_item", "label")):
        _, changed = apply_operator(SAMPLE, operator, path, {})
        assert not changed, (operator, path)
    assert apply_operator({"items": []}, "drop_item", "items", {})[1] is False          # an empty list has nothing to drop
    assert apply_operator({"label": ""}, "empty_value", "label", {})[1] is False         # already empty
    assert apply_operator(SAMPLE, "swap_value", "label", {}, donor=None)[1] is False
    assert apply_operator(SAMPLE, "swap_value", "label", {}, donor={"label": "alpha"})[1] is False     # same value: no change
    assert apply_operator(SAMPLE, "swap_value", "label", {}, donor={"label": "zulu"})[0]["label"] == "zulu"


def test_the_whole_output_can_be_replaced_and_a_missing_path_is_harmless():
    assert apply_operator("text", "empty_value", "", {}) == ("", True)
    assert apply_operator(5, "perturb_number", "", {}) == (6.0, True)


def test_selection_is_deterministic_and_close_to_the_rate():
    ids = [f"case-{i}" for i in range(2000)]
    picked = [i for i in ids if selected(i, "m", 0, 0.25)]
    assert picked == [i for i in ids if selected(i, "m", 0, 0.25)] and 0.21 < len(picked) / 2000 < 0.29
    assert all(selected(i, "m", 0, 1.0) for i in ids[:50]) and picked != [i for i in ids if selected(i, "m", 1, 0.25)]
    assert set(i for i in ids if selected(i, "m", 0, 0.1)) <= set(i for i in ids if selected(i, "m", 0, 0.5))   # nested: higher rate adds


def test_replay_target_never_calls_the_real_target_and_skips_errors():
    replay = {"a": TargetOutput(output={"n": 1}), "b": TargetOutput(error="down"), "c": TargetOutput(output={"n": 3})}
    t = MutatedTarget(replay, "bump", "perturb_number", "n", 1.0)
    assert t.run(Case("a", "q")).output == {"n": 2.0} and t.run(Case("b", "q")).error == "down" and t.mutated == {"a"}
    assert replay["a"].output == {"n": 1}                                                   # the recorded output is untouched
    t2 = MutatedTarget(replay, "swap", "swap_value", "n", 1.0)
    assert t2.run(Case("a", "q")).output == {"n": 3}                                        # swapped with the next case's value


def test_operator_mutants_run_once_against_recorded_outputs_and_are_judged(tmp_path, capsys):
    f = _cfg(tmp_path, _mut("drop-an-item", "drop_item", "items") + _mut("bump-n", "perturb_number", "n")
             + _mut("nothing-here", "drop_item", "no_such_list"))
    REAL_CALLS["n"] = 0
    assert _me(f, "--json", str(tmp_path / "m.json")) == 1                                  # bump-n survives
    out = capsys.readouterr().out
    data = json.loads((tmp_path / "m.json").read_text())
    assert _status(data) == {"drop-an-item": "killed", "bump-n": "survived", "nothing-here": "no-op"}
    assert REAL_CALLS["n"] == 40                                                            # the real target ran once per case in total
    assert "SURVIVED: 'bump-n'" in out and "no-op: 'nothing-here'" in out and "mutation score: 50%" in out
    killed = next(m for m in data["mutants"] if m["name"] == "drop-an-item")
    assert killed["operator"] == "drop_item" and killed["path"] == "items" and killed["mutated_cases"] == 40
    assert list(killed["caught_by"]) == ["m_items"]


def test_sensitivity_finds_how_often_damage_must_occur_before_it_is_noticed(tmp_path, capsys):
    f = _cfg(tmp_path, _mut("lose-items", "drop_item", "items", "rates = [0.05, 0.1, 0.25, 0.5, 1.0]\n"))
    assert _me(f, "--json", str(tmp_path / "s.json")) == 0
    out = capsys.readouterr().out
    m = json.loads((tmp_path / "s.json").read_text())["mutants"][0]
    curve = m["curve"]
    assert [c["rate"] for c in curve] == [0.05, 0.1, 0.25, 0.5, 1.0]
    assert curve[0]["status"] == "survived" and curve[-1]["status"] == "killed"             # 2 damaged cases cannot be significant
    assert [c["mutated_cases"] for c in curve] == sorted(c["mutated_cases"] for c in curve)
    statuses = [c["status"] for c in curve]
    assert statuses == sorted(statuses, key=lambda s: s != "survived")                      # once noticed, always noticed at higher rates
    assert 0.1 <= m["min_detectable_rate"] <= 0.5 and m["status"] == "killed"
    assert "sensitivity:" in out and "first noticed at" in out


def test_the_sensitivity_flag_uses_default_or_given_rates_and_a_field_nothing_checks_is_never_noticed(tmp_path, capsys):
    f = _cfg(tmp_path, _mut("lose-items", "drop_item", "items") + _mut("bump-n", "perturb_number", "n"))
    assert _me(f, "--sensitivity", "--rates", "0.5,1", "--json", str(tmp_path / "s.json")) == 1
    out = capsys.readouterr().out
    ms = {m["name"]: m for m in json.loads((tmp_path / "s.json").read_text())["mutants"]}
    assert [c["rate"] for c in ms["lose-items"]["curve"]] == [0.5, 1.0] and ms["bump-n"]["min_detectable_rate"] is None
    assert "bump-n: 50%:s  100%:s  -> never noticed, even at the highest rate" in out


def test_auto_mode_finds_the_fields_no_grader_looks_at(tmp_path, capsys):
    f = _cfg(tmp_path)                                                                       # no hand-written mutants at all
    assert _me(f, "--auto", "--json", str(tmp_path / "a.json")) == 0                         # auto survivors are informational by default
    out = capsys.readouterr().out
    d = json.loads((tmp_path / "a.json").read_text())
    for unchecked in ("n", "note", "meta", "meta.flag", "items[*].extra"):
        assert unchecked in d["blind_spots"], unchecked
    for checked in ("label", "items"):
        assert checked not in d["blind_spots"] and d["by_path"][checked]["killed"] >= 2, checked
    assert d["by_path"]["items[*].id"]["killed"] >= 1 and "items[*].extra" in d["by_path"]
    assert "BLIND SPOT: no grader notices damage here" in out and "auto mutation:" in out and "field(s) no grader checks" in out
    assert d["auto_survivors"] > 10 and d["ok"] is True
    assert all(m["source"] == "auto" for m in d["mutants"]) and "empty_output" in _status(d)


def test_auto_mode_gating_caps_and_the_unchecked_field_goes_away_once_it_is_graded(tmp_path, capsys):
    f = _cfg(tmp_path)
    assert _me(f, "--auto", "--max-survivors", "0") == 1                                     # survivors exceed the allowance
    assert _me(f, "--auto", "--max-survivors", "999") == 0
    capsys.readouterr()
    _me(f, "--auto", "--max-mutants", "6", "--json", str(tmp_path / "c.json"))
    assert len(json.loads((tmp_path / "c.json").read_text())["mutants"]) <= 6

    @register_grader("m_n")
    class MN(Grader):
        name = "m_n"
        selftest = "guardrail"

        def grade(self, case, out):
            ok = isinstance(out.output, dict) and out.output.get("n") == 3
            return Score(self.name, 1.0 if ok else 0.0, ok, "")

    g = _cfg(tmp_path / "g" if (tmp_path / "g").mkdir() is None else tmp_path, graders='[[graders]]\ntype = "m_items"\n[[graders]]\ntype = "m_label"\n[[graders]]\ntype = "m_n"')
    _me(g, "--auto", "--json", str(tmp_path / "g.json"))
    assert "n" not in json.loads((tmp_path / "g.json").read_text())["blind_spots"]            # adding a grader closed that blind spot


def test_swap_value_uses_another_cases_output(tmp_path):
    f = _cfg(tmp_path, _mut("wrong-label", "swap_value", "label"))
    assert _me(f, "--json", str(tmp_path / "w.json")) == 0
    assert _status(json.loads((tmp_path / "w.json").read_text())) == {"wrong-label": "killed"}


def test_generated_mutants_are_deterministic_unique_and_typed_by_what_they_find():
    outs = [SAMPLE, {"n": 5, "label": "bravo", "flag": False, "items": []}]
    a, b = generate_mutants(outs, 150, 0), generate_mutants(outs, 150, 0)
    assert a == b and len({m["name"] for m in a}) == len(a) and a[0]["operator"] == "empty_output"
    names = {m["name"] for m in a}
    assert {"flip_bool:flag", "perturb_number:n", "truncate_text:label", "drop_item:items", "drop_key:items[*].a",
            "swap_value:label"} <= names
    sites = discover_sites(outs)
    assert sites["items\0list"].count == 2 and sites["n\0number"].count == 2 and sites["flag\0bool"].count == 2
    assert len(generate_mutants(outs, 5, 0)) == 5


def test_hosted_graders_need_an_explicit_flag_before_auto_or_sensitivity(tmp_path, capsys):
    @register_grader("m_hosted")
    class MHosted(Grader):
        name = "m_hosted"
        network = True
        selftest = "guardrail"

        def grade(self, case, out):
            return Score(self.name, 1.0, True, "")

    f = _cfg(tmp_path, _mut("lose-items", "drop_item", "items"), graders='[[graders]]\ntype = "m_items"\n[[graders]]\ntype = "m_hosted"')
    assert _me(f, "--auto") == 2 and "pass --allow-network" in capsys.readouterr().err
    assert _me(f, "--sensitivity") == 2
    assert _me(f) in (0, 1)                                                                  # explicit mutants alone are not refused
    assert _me(f, "--auto", "--allow-network") in (0, 1)


def test_mutant_config_validation(tmp_path, capsys):
    cases = [("operator = \"drop_itme\"\npath = \"items\"", "Did you mean 'drop_item'"),
             ("operator = \"drop_item\"\n[mutants.target]\ntype = \"null\"", "exactly one of"),
             ("path = \"items\"", "exactly one of"), ("operator = \"drop_item\"\nrate = 0", "rate must be number(s) in (0, 1]"),
             ("operator = \"drop_item\"\nrates = [0.5, 2]", "rates must be number(s) in (0, 1]"),
             ("operator = \"drop_item\"\npath = 3", "path must be text"),
             ("operator = \"drop_item\"\nsurprise = 1", "unknown key 'surprise'"),
             ("rate = 0.5\n[mutants.target]\ntype = \"null\"", "only apply with 'operator'")]
    for body, message in cases:
        sub = tmp_path / str(abs(hash(body)))
        sub.mkdir()
        f = _cfg(sub, f'[[mutants]]\nname = "m"\n{body}\n')
        assert main(["check", str(f)]) == 2, body
        assert message in capsys.readouterr().err, body
    dup = _cfg(tmp_path / "dup", _mut("a", "drop_item", "items") + _mut("a", "drop_item", "items")) if (tmp_path / "dup").mkdir() is None else None
    assert main(["check", str(dup)]) == 2 and "name 'a' is used twice" in capsys.readouterr().err
    none = _cfg(tmp_path / "none") if (tmp_path / "none").mkdir() is None else None
    assert _me(none) == 2 and "--auto" in capsys.readouterr().err
    assert _me(none, "--auto", "--sensitivity", "--rates", "0,2") == 2 and "(0, 1]" in capsys.readouterr().err
    assert _me(none, "--auto", "--sensitivity", "--rates", "abc") == 2
