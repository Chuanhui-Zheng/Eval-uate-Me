"""Tests: judges."""
from helpers import *  # noqa: F401,F403


# ---- multi-judge panel ----


def test_panel_aggregation_rules():
    s = _grade(_panel(5, 5, 1))                                          # two of three pass
    assert s.passed and abs(s.value - 2 / 3) < 1e-9
    assert "majority pass (2/3 judges pass; j1=5, j2=5, j3=1)" in s.reason and "judges disagree: j3: r3" in s.reason
    assert not _grade(_panel(5, 1)).passed                               # 1-1 tie: not a majority
    assert not _grade(_panel(5, 5, 1, 1)).passed
    assert _grade(_panel(5, 5)).passed and "disagree" not in _grade(_panel(5, 5)).reason
    assert not _grade(_panel(5, 5, 1, aggregate="unanimous")).passed and _grade(_panel(5, 4, aggregate="unanimous")).passed
    mn = _grade(_panel(5, 3, aggregate="min"))
    assert not mn.passed and mn.value == 0.5
    assert _grade(_panel(5, 4, 4, aggregate="mean")).passed and not _grade(_panel(5, 1, aggregate="mean")).passed


def test_single_judge_keeps_the_old_behaviour_and_panel_validation():
    from eval_uate_me.config import ConfigError
    from eval_uate_me.graders import LLMJudge
    s = LLMJudge(rubric="r", judge={"type": "test_scripted", "reply": '{"score": 4, "reason": "ok"}'}).grade(
        Case("a", "q", "ref"), TargetOutput(output="x"))
    assert s.passed and s.reason == "4/5: ok"
    with pytest.raises(ConfigError, match="either 'judge'"):
        LLMJudge(rubric="r", judge={"type": "test_scripted"}, judges=[{"type": "test_scripted"}])
    with pytest.raises(ConfigError, match="is empty"):
        LLMJudge(rubric="r", judges=[])
    with pytest.raises(ConfigError, match="aggregate must be one of"):
        LLMJudge(rubric="r", judges=[{"type": "test_scripted"}], aggregate="average")


def test_panel_network_flag_and_failing_judge_fails_the_case(tmp_path):
    from eval_uate_me.graders import LLMJudge
    assert LLMJudge(rubric="r", judges=[{"type": "test_scripted"}, {"type": "test_scripted"}]).network is False
    assert LLMJudge(rubric="r", judges=[{"type": "test_scripted"}, {"type": "anthropic"}]).network is True
    broken = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}], graders=(
        '[[graders]]\ntype = "llm_judge"\nrubric = "r"\n[[graders.judges]]\ntype = "test_scripted"\n'
        '[[graders.judges]]\ntype = "test_scripted"\nreply = "not json"'))
    results, _, _ = run(load_config(broken))
    assert not results[0].passed and "grader error" in results[0].scores[0].reason      # never guesses


def test_panel_from_config_end_to_end(tmp_path, capsys):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}], graders=(
        '[[graders]]\ntype = "llm_judge"\nrubric = "matches the reference"\naggregate = "unanimous"\n'
        '[[graders.judges]]\ntype = "test_scripted"\nlabel = "strict"\n[[graders.judges]]\ntype = "test_scripted"\nlabel = "second"'))
    assert main(["check", str(f)]) == 0
    results, _, _ = run(load_config(f))
    assert results[0].passed and "unanimous pass (2/2 judges pass; strict=5, second=5)" in results[0].scores[0].reason
    f.write_text(f.read_text().replace('aggregate = "unanimous"', 'aggregate = "unamimous"'))
    assert main(["check", str(f)]) == 2 and "aggregate must be one of" in capsys.readouterr().err
    f.write_text(f.read_text().replace('type = "test_scripted"\nlabel = "second"', 'type = "unknown_backend"\nlabel = "second"'))
    assert main(["check", str(f)]) == 2


def test_selftest_catches_a_panel_that_always_approves(tmp_path):
    from eval_uate_me.graders import LLMJudge
    from eval_uate_me.selftest import selftest
    cases = [Case(str(i), f"q{i}", f"answer-{i}") for i in range(5)]
    lax = _panel(5, 5, 5)
    good = LLMJudge(rubric="r", judges=[{"type": "test_scripted"}, {"type": "test_scripted"}, {"type": "test_scripted"}], name="panel_ref")
    verdicts = {v.grader: v.verdict for v in selftest(cases, [good, lax]).verdicts}
    assert verdicts == {"panel_ref": "ok", "llm_judge": "too_lenient"}


# ---- pairwise comparison ----


def test_parse_pair_reply_and_sign_test():
    from eval_uate_me.pairwise import parse_pair_reply, sign_test_p
    assert parse_pair_reply('{"winner": "B", "reason": "x"}') == ("B", "x") and parse_pair_reply('{"winner": "TIE"}')[0] == "tie"
    assert parse_pair_reply('noise {"winner": "a"} noise')[0] == "A"
    for bad in ('{"winner": "C"}', "no json", '{"reason": "x"}'):
        with pytest.raises(ValueError):
            parse_pair_reply(bad)
    assert sign_test_p(0, 10) == pytest.approx(2 / 1024) and sign_test_p(5, 5) == 1.0 and sign_test_p(0, 0) == 1.0
    assert sign_test_p(2, 8) == pytest.approx(2 * (1 + 10 + 45) / 1024)


def test_pairwise_finds_the_better_run_and_cancels_position(tmp_path):
    from eval_uate_me.pairwise import compare_runs
    a, b = _pw_runs(tmp_path, *_right_wrong(12))
    r = compare_runs(a, b, DeterministicJudge(), "matches the reference")
    assert (r.b_wins, r.a_wins, r.ties, r.inconsistent, r.errors) == (12, 0, 0, 0, 0)
    assert r.win_rate_b == 1.0 and r.p_value == pytest.approx(2 / 4096) and r.calls == 24     # both orders
    assert r.position_a_rate == 0.5 and r.warnings == []                                      # B was first once, second once
    assert compare_runs(b, a, DeterministicJudge(), "r").a_wins == 12                         # swapping runs swaps winners


def test_pairwise_skips_identical_outputs_and_counts_calls(tmp_path):
    from eval_uate_me.pairwise import compare_runs
    calls = []

    class Counting(DeterministicJudge):
        def complete(self, prompt):
            calls.append(1)
            return super().complete(prompt)

    same = {f"c{i}": f"ref{i}" for i in range(6)}
    a, b = _pw_runs(tmp_path, same, dict(same, c0="nope"))
    r = compare_runs(a, b, Counting(), "r")
    assert r.identical == 5 and r.a_wins == 1 and len(calls) == 2 and r.calls == 2           # only the differing pair is judged
    assert r.win_rate_b == pytest.approx((0 + 0.5 * 5) / 6)


def test_pairwise_exposes_a_position_biased_judge(tmp_path):
    from eval_uate_me.judges import Judge
    from eval_uate_me.pairwise import compare_runs

    class AlwaysFirst(Judge):
        network = False

        def complete(self, prompt):
            return '{"winner": "A", "reason": "first"}'

    a, b = _pw_runs(tmp_path, *_right_wrong(12))
    r = compare_runs(a, b, AlwaysFirst(), "r")
    assert r.inconsistent == 12 and r.b_wins == r.a_wins == 0 and r.win_rate_b == 0.5      # no winner is manufactured
    assert r.position_a_rate == 1.0
    assert any("different winner when the order was swapped" in w for w in r.warnings)
    assert any("position bias" in w for w in r.warnings)


def test_pairwise_single_order_budget_and_errors(tmp_path):
    from eval_uate_me.config import ConfigError
    from eval_uate_me.judges import Judge
    from eval_uate_me.pairwise import compare_runs
    a, b = _pw_runs(tmp_path, *_right_wrong(10))
    r = compare_runs(a, b, DeterministicJudge(), "r", both_orders=False, seed=3)
    assert r.calls == 10 and r.b_wins == 10                                                # half the calls
    with pytest.raises(ConfigError, match="20 judge calls \\(limit 5\\)"):
        compare_runs(a, b, DeterministicJudge(), "r", max_calls=5)
    n = {"k": 0}

    class Flaky(Judge):
        network = False

        def complete(self, prompt):
            n["k"] += 1
            if n["k"] == 1:                      # only the very first call fails -> exactly one pair is lost
                raise RuntimeError("rate limited")
            return DeterministicJudge().complete(prompt)

    r = compare_runs(a, b, Flaky(), "r")
    assert r.errors == 1 and r.b_wins == 9 and any("rate limited" in w for w in r.warnings)


def test_pairwise_cli_end_to_end_and_refusals(tmp_path, capsys):
    a, b = _pw_runs(tmp_path, *_right_wrong(8))
    assert main(["pairwise", str(a), str(b), "--rubric", "matches the reference", "--judge", "test_scripted",
                 "--json", str(tmp_path / "pw.json")]) == 0
    out = capsys.readouterr().out
    assert "8 pairs compared (16 judge calls)" in out and "B wins 8, A wins 0" in out and "p = 0.008" in out
    data = json.loads((tmp_path / "pw.json").read_text())
    assert data["b_wins"] == 8 and len(data["pairs"]) == 8
    assert main(["pairwise", str(a), str(b), "--rubric", "r", "--judge", "nope"]) == 2
    assert "unknown judge 'nope'" in capsys.readouterr().err
    assert main(["pairwise", str(a), str(b), "--rubric", "r", "--judge", "test_scripted", "--judge-opt", "oops"]) == 2
    assert main(["pairwise", str(a), str(b), "--rubric", "r", "--judge", "test_scripted", "--max-calls", "3"]) == 2
    assert main(["pairwise", str(a), str(b), "--rubric", "r", "--judge", "test_scripted",
                 "--judge-opt", 'reply={"winner": "tie"}']) == 0
    assert "ties 8" in capsys.readouterr().out
    priv = _labelled_run(tmp_path / "priv" if (tmp_path / "priv").mkdir() is None else tmp_path,
                         privacy='[privacy]\nstore = "scores_only"\n')
    assert main(["pairwise", str(priv), str(b), "--rubric", "r", "--judge", "test_scripted"]) == 2 and "nothing to compare" in capsys.readouterr().err


# ---- judge-check (bias probes) ----


def test_judge_check_passes_a_sound_judge(tmp_path, capsys):
    f = _probe_cfg(tmp_path, "test_scripted")
    assert main(["judge-check", str(f), "--json", str(tmp_path / "jc.json")]) == 0
    out = capsys.readouterr().out
    assert "RESULT: no concerns on these probes" in out and "12 cases, 3 repeats" in out
    data = json.loads((tmp_path / "jc.json").read_text())
    by = {c["name"]: c for c in data["checks"]}
    assert data["ok"] and by["repeatability"]["value"] == 1.0 and by["position_first_rate"]["value"] == 0.5
    assert by["length_rescues_wrong"]["value"] == 0.0 and by["injection_rescues_wrong"]["value"] == 0.0


@pytest.mark.parametrize("judge_type, expected_concerns", [
    ("probe_lengthy", {"length_rescues_wrong"}),
    ("probe_injectable", {"injection_rescues_wrong"}),
    ("probe_verbosity_hater", {"length_penalises_correct"}),
    ("probe_first", {"pairwise_accuracy", "position_first_rate"}),
    ("probe_flaky", {"repeatability", "accepts_correct", "rejects_wrong"}),
])
def test_judge_check_flags_each_known_bias(tmp_path, capsys, judge_type, expected_concerns):
    assert main(["judge-check", str(_probe_cfg(tmp_path, judge_type))]) == 1
    out = capsys.readouterr().out
    got = _concerns(out)
    assert expected_concerns <= got, (judge_type, got)
    assert "concerns found: do not trust this judge" in out
    if judge_type != "probe_flaky":                      # the targeted bias is the *only* thing flagged
        assert got == expected_concerns, (judge_type, got)


def test_judge_check_guards_and_errors(tmp_path, capsys):
    f = _probe_cfg(tmp_path, "test_scripted")
    assert main(["judge-check", str(f), "--max-calls", "20"]) == 2
    assert "judge calls (limit 20)" in capsys.readouterr().err
    assert main(["judge-check", str(f), "--sample", "4", "--repeats", "1", "--max-calls", "40"]) == 0     # 4*(1+4)+8 = 28
    assert "4 cases, 1 repeats" in capsys.readouterr().out
    plain = write_eval(tmp_path / "p" if (tmp_path / "p").mkdir() is None else tmp_path,
                       [{"id": "1", "input": "a", "expected": "a"}])
    assert main(["judge-check", str(plain)]) == 2 and "no llm_judge grader" in capsys.readouterr().err
    assert main(["judge-check", str(f), "--grader", "other"]) == 2
    same = write_eval(tmp_path / "s" if (tmp_path / "s").mkdir() is None else tmp_path,
                      [{"id": "1", "input": "a", "expected": "x"}, {"id": "2", "input": "b", "expected": "x"}],
                      graders='[[graders]]\ntype = "llm_judge"\nrubric = "r"\n[graders.judge]\ntype = "test_scripted"')
    assert main(["judge-check", str(same)]) == 2 and "at least two different references" in capsys.readouterr().err
    capsys.readouterr()


def test_judge_check_uses_the_whole_panel_for_grading(tmp_path, capsys):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"answer-{i}"} for i in range(8)]
    f = write_eval(tmp_path, cases, graders=(
        '[[graders]]\ntype = "llm_judge"\nrubric = "r"\n[[graders.judges]]\ntype = "test_scripted"\n'
        '[[graders.judges]]\ntype = "probe_lengthy"\n[[graders.judges]]\ntype = "probe_lengthy"'))
    assert main(["judge-check", str(f)]) == 1             # two of three judges are length-biased, so the majority is
    out = capsys.readouterr().out
    assert "length_rescues_wrong" in _concerns(out)
    assert "panel: test_scripted1, probe_lengthy2, probe_lengthy3" in out


# ---- the Anthropic judge's HTTP client, against a local fake server (no real API is contacted) ----


def test_anthropic_judge_sends_the_documented_request_and_reads_the_reply(monkeypatch):
    from eval_uate_me.judges import AnthropicJudge
    api = _FakeAPI([_ok('{"score": 4, "reason": "fine"}')])
    try:
        monkeypatch.setenv("FAKE_KEY_ENV", "sk-test-123")
        judge = AnthropicJudge(model="some-model", max_tokens=99, api_key_env="FAKE_KEY_ENV", base_url=api.url + "/")
        assert judge.complete("grade this") == '{"score": 4, "reason": "fine"}'
        req = api.requests[0]
        assert req["path"] == "/v1/messages"
        assert req["headers"]["x-api-key"] == "sk-test-123" and req["headers"]["anthropic-version"] == "2023-06-01"
        assert req["json"] == {"model": "some-model", "max_tokens": 99, "temperature": 0,
                               "messages": [{"role": "user", "content": "grade this"}]}
        assert judge.network is True
    finally:
        api.close()


def test_anthropic_judge_retries_transient_errors_but_not_client_errors(monkeypatch):
    from eval_uate_me import judges
    monkeypatch.setattr(judges.time, "sleep", lambda s: None)
    monkeypatch.setenv("FAKE_KEY_ENV", "k")
    api = _FakeAPI([(429, {"error": "slow down"}), (529, {"error": "overloaded"}), _ok("done")])
    try:
        j = judges.AnthropicJudge(api_key_env="FAKE_KEY_ENV", base_url=api.url)
        assert j.complete("x") == "done" and len(api.requests) == 3            # two retries, then success
    finally:
        api.close()
    api = _FakeAPI([(401, {"error": "bad key"})])
    try:
        with pytest.raises(RuntimeError, match="judge HTTP 401"):
            judges.AnthropicJudge(api_key_env="FAKE_KEY_ENV", base_url=api.url).complete("x")
        assert len(api.requests) == 1                                          # no retry on a client error
    finally:
        api.close()
    api = _FakeAPI([(500, {"e": 1})] * 5)
    try:
        with pytest.raises(RuntimeError, match="judge HTTP 500"):
            judges.AnthropicJudge(api_key_env="FAKE_KEY_ENV", base_url=api.url, retries=3).complete("x")
        assert len(api.requests) == 3                                          # gave up after `retries` attempts
    finally:
        api.close()


def test_anthropic_judge_errors_without_a_key_or_a_server(monkeypatch):
    from eval_uate_me import judges
    monkeypatch.delenv("NO_SUCH_KEY_ENV", raising=False)
    with pytest.raises(RuntimeError, match="NO_SUCH_KEY_ENV is not set"):
        judges.AnthropicJudge(api_key_env="NO_SUCH_KEY_ENV").complete("x")
    monkeypatch.setattr(judges.time, "sleep", lambda s: None)
    monkeypatch.setenv("FAKE_KEY_ENV", "k")
    with pytest.raises(RuntimeError, match="judge network error"):
        judges.AnthropicJudge(api_key_env="FAKE_KEY_ENV", base_url="http://127.0.0.1:1", retries=2, timeout_s=2).complete("x")


def test_llm_judge_grader_works_end_to_end_against_the_fake_api(monkeypatch):
    from eval_uate_me.graders import LLMJudge
    monkeypatch.setenv("FAKE_KEY_ENV", "k")
    api = _FakeAPI([_ok('Sure. {"score": 5, "reason": "matches"}'), _ok('{"score": 1, "reason": "no"}')])
    try:
        g = LLMJudge(rubric="r", judge={"type": "anthropic", "api_key_env": "FAKE_KEY_ENV", "base_url": api.url})
        assert g.grade(Case("a", "q", "ref"), TargetOutput(output="x")).passed
        assert not g.grade(Case("b", "q", "ref"), TargetOutput(output="y")).passed
        assert "<rubric>" in api.requests[0]["json"]["messages"][0]["content"]       # the real prompt went over the wire
    finally:
        api.close()
