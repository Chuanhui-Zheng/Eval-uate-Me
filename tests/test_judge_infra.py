"""Tests: judge usage and cost, the reply cache, prompt versions, dimensions and context."""
from helpers import *  # noqa: F401,F403

import eval_uate_me.graders as graders_mod
from eval_uate_me import Judge, register_judge
from eval_uate_me.judges import CachingJudge, JudgeCache

CAPTURED: list = []


@register_judge("capture_judge")
class CaptureJudge(Judge):
    network = False

    def complete(self, prompt):
        CAPTURED.append(prompt)
        return json.dumps({"score": 5, "reason": "ok"})


def _usage_ok(text, tin=1000, tout=500):
    return 200, {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": tin, "output_tokens": tout}}


GOOD = '{"score": 5, "reason": "fine"}'


def _judge_cfg(tmp_path, api_url, n=4, run_extra="", judge_extra="", grader_extra=""):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"a{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases, graders=(
        f'[[graders]]\ntype = "llm_judge"\nrubric = "r"\n{grader_extra}[graders.judge]\ntype = "anthropic"\n'
        f'base_url = "{api_url}"\napi_key_env = "FAKE_KEY_ENV"\nretries = 1\n{judge_extra}'))
    f.write_text(f.read_text() + run_extra)
    return f


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("FAKE_KEY_ENV", "sk-test-key")
    CAPTURED.clear()


# ---- usage and cost ----

def test_a_priced_judge_reports_cost_that_reaches_the_summary_and_the_budget(tmp_path, capsys):
    api = _FakeAPI([_usage_ok(GOOD)] * 40)
    try:
        f = _judge_cfg(tmp_path, api.url, n=4, judge_extra="price_in_per_mtok = 3\nprice_out_per_mtok = 15\n")
        results, summary, _ = run(load_config(f))
        per_call = 1000 * 3 / 1e6 + 500 * 15 / 1e6
        assert abs(results[0].scores[0].cost_usd - per_call) < 1e-12 and abs(summary["judge_cost_usd"] - 4 * per_call) < 1e-12
        assert abs(summary["cost_usd_spent"] - 4 * per_call) < 1e-12            # the run's spend includes the judge
        sub = tmp_path / "budget"
        sub.mkdir()
        g = _judge_cfg(sub, api.url, n=6, judge_extra="price_in_per_mtok = 3\nprice_out_per_mtok = 15\n",
                       run_extra="max_cost_usd = 0.02\nconcurrency = 1\n")
        _, s2, _ = run(load_config(g))
        assert s2["incomplete"] == 4 and s2["budget_exhausted"]                  # two judged cases reach $0.02, the rest are skipped
        capsys.readouterr()
        main(["run", str(f)])
        assert "judge cost: $" in capsys.readouterr().out
    finally:
        api.close()


def test_an_unpriced_judge_reports_zero_cost_but_still_counts_tokens(tmp_path):
    from eval_uate_me.judges import AnthropicJudge
    api = _FakeAPI([_usage_ok(GOOD, 123, 45)])
    try:
        reply = AnthropicJudge(api_key_env="FAKE_KEY_ENV", base_url=api.url).complete_with_usage("x")
        assert (reply.input_tokens, reply.output_tokens, reply.cost_usd, reply.cached) == (123, 45, 0.0, False)
    finally:
        api.close()


# ---- the cache ----

def test_cached_judge_replies_make_a_second_run_free_and_identical(tmp_path):
    api = _FakeAPI([_usage_ok(GOOD)] * 40)
    try:
        f = _judge_cfg(tmp_path, api.url, run_extra="judge_cache = true\n", judge_extra="price_in_per_mtok = 3\nprice_out_per_mtok = 15\n")
        first, s1, _ = run(load_config(f))
        calls = len(api.requests)
        assert calls == 4 and s1["judge_cost_usd"] > 0
        second, s2, _ = run(load_config(f))
        assert len(api.requests) == calls                                          # no new API calls
        assert [r.scores[0].value for r in second] == [r.scores[0].value for r in first] and all(r.passed for r in second)
        assert s2["judge_cost_usd"] == 0.0                                         # a cache hit costs nothing now
        for p in (tmp_path / "runs" / ".judge_cache").iterdir():
            assert "sk-test-key" not in p.read_text()                              # the key is never cached
    finally:
        api.close()


def test_changing_the_prompt_the_model_or_the_prompt_version_never_reuses_a_reply(tmp_path, monkeypatch):
    api = _FakeAPI([_usage_ok(GOOD)] * 100)
    try:
        f = _judge_cfg(tmp_path, api.url, n=2, run_extra="judge_cache = true\n")
        run(load_config(f))
        assert len(api.requests) == 2
        run(load_config(f))
        assert len(api.requests) == 2                                              # same everything: cached
        f.write_text(f.read_text().replace('rubric = "r"', 'rubric = "a different rubric"'))
        run(load_config(f))
        assert len(api.requests) == 4                                              # a new rubric is a new prompt
        f.write_text(f.read_text().replace('api_key_env = "FAKE_KEY_ENV"', 'api_key_env = "FAKE_KEY_ENV"\nmodel = "another-model"'))
        run(load_config(f))
        assert len(api.requests) == 6                                              # a new model is a different judge
        monkeypatch.setattr(graders_mod, "JUDGE_PROMPT_VERSION", "999")
        run(load_config(f))
        assert len(api.requests) == 8                                              # a new prompt version invalidates the cache
    finally:
        api.close()


def test_the_cache_is_off_by_default_and_a_corrupt_entry_is_a_miss(tmp_path):
    api = _FakeAPI([_usage_ok(GOOD)] * 40)
    try:
        f = _judge_cfg(tmp_path, api.url, n=2)
        run(load_config(f))
        run(load_config(f))
        assert len(api.requests) == 4 and not (tmp_path / "runs" / ".judge_cache").exists()
        g = _judge_cfg(tmp_path / "c" if (tmp_path / "c").mkdir() is None else tmp_path, api.url, n=1, run_extra="judge_cache = true\n")
        run(load_config(g))
        entry = next((tmp_path / "runs" / ".judge_cache").iterdir()) if (tmp_path / "runs" / ".judge_cache").exists() else next((tmp_path / "c" / "runs" / ".judge_cache").iterdir())
        entry.write_text("{ not json")
        before = len(api.requests)
        run(load_config(g))
        assert len(api.requests) == before + 1
    finally:
        api.close()


def test_judge_cache_cannot_be_combined_with_scores_only(tmp_path, capsys):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    f.write_text(f.read_text() + 'judge_cache = true\n[privacy]\nstore = "scores_only"\n')
    assert main(["check", str(f)]) == 2 and "cannot be combined" in capsys.readouterr().err


def test_caching_judge_wrapper_unit(tmp_path):
    class Counting(Judge):
        network = False

        def __init__(self, tag):
            self.tag, self.n = tag, 0

        def complete(self, prompt):
            self.n += 1
            return f"{self.tag}:{prompt}"

        def cache_id(self):
            return self.tag

    cache = JudgeCache(tmp_path / "jc")
    a, b = Counting("A"), Counting("B")
    ca, cb = CachingJudge(a, cache, "1"), CachingJudge(b, cache, "1")
    assert ca.complete("p") == "A:p" and ca.complete("p") == "A:p" and a.n == 1
    assert cb.complete("p") == "B:p" and b.n == 1                                   # another judge, another entry
    assert CachingJudge(a, cache, "2").complete("p") == "A:p" and a.n == 2          # another prompt version
    assert ca.complete_with_usage("p").cached is True and ca.network is False


def test_the_manifest_records_the_judge_prompt_versions(tmp_path):
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}])
    _, _, d = run(load_config(f))
    assert json.loads((d / "manifest.json").read_text())["judge_prompt_versions"] == {
        "llm_judge": graders_mod.JUDGE_PROMPT_VERSION, "pairwise": "1"}


# ---- dimensions and context ----

def _dim_cfg(tmp_path, dims_toml, judge='[graders.judge]\ntype = "test_scripted"', n=3, extra=""):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"a{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases, target='type = "oracle"', graders=f'[[graders]]\ntype = "llm_judge"\nrubric = "r"\n{dims_toml}\n{judge}\n')
    f.write_text(f.read_text() + extra)
    return f


def test_dimensions_are_scored_separately_and_summarised(tmp_path, capsys):
    f = _dim_cfg(tmp_path, 'dimensions = ["faithfulness", "correctness"]')
    results, summary, _ = run(load_config(f))
    s = results[0].scores[0]
    assert s.passed and s.detail["scores"] == {"faithfulness": 5, "correctness": 5} and s.detail["dimensions"]["correctness"] == 1.0
    assert s.reason == "faithfulness 5/5, correctness 5/5"
    assert summary["dimension_means"] == {"llm_judge": {"faithfulness": 1.0, "correctness": 1.0}}
    capsys.readouterr()
    main(["run", str(f)])
    assert "llm_judge dimensions: faithfulness 1.00, correctness 1.00" in capsys.readouterr().out


def test_a_judge_that_scores_one_dimension_low_fails_under_all_but_can_pass_under_mean(tmp_path):
    reply = json.dumps({"faithfulness": {"score": 5, "reason": "grounded"}, "correctness": {"score": 2, "reason": "wrong figure"}})
    judge = f"[graders.judge]\ntype = \"test_scripted\"\nreply = '{reply}'"
    f = _dim_cfg(tmp_path, 'dimensions = ["faithfulness", "correctness"]', judge, n=1)
    s = run(load_config(f))[0][0].scores[0]
    assert not s.passed and "correctness: wrong figure" in s.reason and abs(s.value - 0.625) < 1e-9
    g = _dim_cfg(tmp_path / "m" if (tmp_path / "m").mkdir() is None else tmp_path,
                 'dimensions = ["faithfulness", "correctness"]\ndimension_rule = "mean"\npass_threshold = 0.6', judge, n=1)
    assert run(load_config(g))[0][0].scores[0].passed                        # mean 0.625 >= 0.6 although one dimension is weak


def test_custom_dimensions_a_panel_and_bad_replies(tmp_path):
    f = _dim_cfg(tmp_path, 'dimensions = [{name = "tone", description = "Is it calm and professional?"}]\naggregate = "majority"',
                 '[[graders.judges]]\ntype = "test_scripted"\n[[graders.judges]]\ntype = "test_scripted"\n[[graders.judges]]\ntype = "test_scripted"', n=1)
    s = run(load_config(f))[0][0].scores[0]
    assert s.passed and s.detail["judges"] == {"test_scripted1": {"tone": 5}, "test_scripted2": {"tone": 5}, "test_scripted3": {"tone": 5}}
    bad = _dim_cfg(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, 'dimensions = ["faithfulness"]',
                   "[graders.judge]\ntype = \"test_scripted\"\nreply = '{\"relevance\": {\"score\": 5}}'", n=1)
    r = run(load_config(bad))[0][0]
    assert "grader error" in r.scores[0].reason and "missing dimension 'faithfulness'" in r.scores[0].reason


def test_dimension_config_errors(tmp_path):
    from eval_uate_me import ConfigError
    from eval_uate_me.graders import LLMJudge
    for kwargs, message in (({"dimensions": []}, "is empty"), ({"dimensions": ["a", "a"]}, "unique, non-empty"),
                            ({"dimensions": [{"description": "x"}]}, "unique, non-empty"), ({"dimensions": ["a"], "dimension_rule": "some"}, "dimension_rule")):
        with pytest.raises(ConfigError, match=message):
            LLMJudge(rubric="r", **kwargs)


def test_case_context_is_shown_to_the_judge_so_faithfulness_can_check_grounding():
    from eval_uate_me.graders import LLMJudge
    g = LLMJudge(rubric="r", judge={"type": "capture_judge"})
    g.grade(Case("a", "q", "ref", {"context": ["fact one", "fact two"]}), TargetOutput(output="x"))
    g.grade(Case("b", "q", "ref", {"context": "one passage"}), TargetOutput(output="x"))
    g.grade(Case("c", "q", "ref"), TargetOutput(output="x"))
    assert "<context>\n- fact one\n- fact two\n</context>" in CAPTURED[0]
    assert "<context>\none passage\n</context>" in CAPTURED[1] and "<context>\n(none)\n</context>" in CAPTURED[2]


def test_privacy_mode_keeps_judge_cost_but_drops_per_dimension_detail(tmp_path):
    f = _dim_cfg(tmp_path, 'dimensions = ["faithfulness"]', extra='[privacy]\nstore = "scores_only"\n')
    results, _, d = run(load_config(f))
    assert results[0].scores[0].detail == {} and results[0].scores[0].cost_usd == 0.0
    assert "detail" in (d / "results.jsonl").read_text() and "faithfulness 5/5" not in (d / "results.jsonl").read_text()
