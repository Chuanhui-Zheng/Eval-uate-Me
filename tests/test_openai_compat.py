"""Tests: the OpenAI-compatible judge backend (against a local fake server; no real API is contacted)."""
from helpers import *  # noqa: F401,F403

from evalharness import registry
from evalharness.graders import LLMJudge
from evalharness.judges import OpenAICompatJudge


def _chat(text, pt=200, ct=40):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": pt, "completion_tokens": ct}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OAI_KEY", "sk-oai-123")


def test_it_is_registered_and_sends_the_chat_completions_request(monkeypatch):
    assert "openai_compat" in registry.available()["judges"]
    api = _FakeAPI([_chat('{"score": 4, "reason": "ok"}')])
    try:
        j = OpenAICompatJudge(model="some-model", base_url=api.url + "/v1/", api_key_env="OAI_KEY", max_tokens=77,
                              price_in_per_mtok=1.0, price_out_per_mtok=2.0)
        reply = j.complete_with_usage("hello")
        assert reply.text == '{"score": 4, "reason": "ok"}' and (reply.input_tokens, reply.output_tokens) == (200, 40)
        assert abs(reply.cost_usd - (200 * 1.0 + 40 * 2.0) / 1e6) < 1e-12
        req = api.requests[0]
        assert req["path"] == "/v1/chat/completions" and req["headers"]["authorization"] == "Bearer sk-oai-123"
        assert req["json"] == {"model": "some-model", "temperature": 0.0, "max_tokens": 77, "messages": [{"role": "user", "content": "hello"}]}
    finally:
        api.close()


def test_json_mode_keyless_local_servers_and_custom_headers(monkeypatch):
    monkeypatch.setenv("EXTRA_HDR", "abc")
    api = _FakeAPI([_chat("{}")])
    try:
        j = OpenAICompatJudge(model="m", base_url=api.url, api_key_env="", json_mode=True, headers={"x-team": "${ENV:EXTRA_HDR}"})
        j.complete("x")
        req = api.requests[0]
        assert "authorization" not in req["headers"] and req["headers"]["x-team"] == "abc"
        assert req["json"]["response_format"] == {"type": "json_object"}
    finally:
        api.close()


def test_localhost_means_the_data_stays_here_and_anything_else_does_not():
    assert OpenAICompatJudge(model="m", base_url="http://localhost:11434/v1").network is False       # e.g. Ollama
    assert OpenAICompatJudge(model="m", base_url="http://127.0.0.1:8000/v1").network is False
    assert OpenAICompatJudge(model="m", base_url="https://api.groq.com/openai/v1").network is True
    assert LLMJudge(rubric="r", judge={"type": "openai_compat", "model": "m", "base_url": "http://localhost:1/v1"}).network is False
    assert LLMJudge(rubric="r", judge={"type": "openai_compat", "model": "m"}).network is True


def test_local_only_allows_a_local_model_and_refuses_a_hosted_one(tmp_path, capsys):
    def cfg(sub, base):
        sub.mkdir()
        f = write_eval(sub, [{"id": "1", "input": "a", "expected": "a"}], graders=(
            f'[[graders]]\ntype = "llm_judge"\nrubric = "r"\n[graders.judge]\ntype = "openai_compat"\nmodel = "m"\nbase_url = "{base}"\napi_key_env = ""'))
        f.write_text(f.read_text() + '[privacy]\nlocal_only = true\n')
        return f
    assert main(["check", str(cfg(tmp_path / "local", "http://localhost:11434/v1"))]) == 0
    assert main(["check", str(cfg(tmp_path / "hosted", "https://api.groq.com/openai/v1"))]) == 2           # check refuses...
    assert "sends data off this machine" in capsys.readouterr().err
    assert main(["run", str(cfg(tmp_path / "hosted2", "https://api.groq.com/openai/v1"))]) == 2             # ...and so does run
    assert "sends data off this machine" in capsys.readouterr().err


def test_errors_are_specific(monkeypatch):
    j = OpenAICompatJudge(model="m", base_url="http://127.0.0.1:1", api_key_env="NO_SUCH_KEY", retries=1)
    with pytest.raises(RuntimeError, match="NO_SUCH_KEY is not set"):
        j.complete("x")
    api = _FakeAPI([(200, {"nothing": 1}), (200, {"choices": [{"message": {"content": ["a"]}}]}), (400, {"error": "bad request"})])
    try:
        k = OpenAICompatJudge(model="m", base_url=api.url, api_key_env="OAI_KEY", retries=3)
        with pytest.raises(RuntimeError, match="no choices"):
            k.complete("x")
        with pytest.raises(RuntimeError, match="not text"):
            k.complete("x")
        with pytest.raises(RuntimeError, match="judge HTTP 400"):
            k.complete("x")
        assert len(api.requests) == 3                                         # the 400 was not retried
    finally:
        api.close()
    from evalharness import ConfigError
    with pytest.raises(ConfigError, match="http:// or https://"):
        OpenAICompatJudge(model="m", base_url="file:///x")
    monkeypatch.delenv("EXTRA_HDR", raising=False)
    with pytest.raises(ConfigError, match="environment variable EXTRA_HDR is not set"):
        OpenAICompatJudge(model="m", headers={"x": "${ENV:EXTRA_HDR}"})


def test_transient_failures_are_retried(monkeypatch):
    from evalharness import judges
    monkeypatch.setattr(judges.time, "sleep", lambda s: None)
    api = _FakeAPI([(429, {}), (503, {}), _chat("done")])
    try:
        assert OpenAICompatJudge(model="m", base_url=api.url, api_key_env="OAI_KEY").complete("x") == "done" and len(api.requests) == 3
    finally:
        api.close()


def test_an_llm_judge_run_with_dimensions_and_the_cache_end_to_end(tmp_path):
    reply = json.dumps({"faithfulness": {"score": 5, "reason": "grounded"}, "correctness": {"score": 4, "reason": "close"}})
    api = _FakeAPI([_chat(reply)] * 10)
    try:
        f = write_eval(tmp_path, [{"id": f"c{i}", "input": f"q{i}", "expected": f"a{i}"} for i in range(3)], graders=(
            f'[[graders]]\ntype = "llm_judge"\nrubric = "r"\ndimensions = ["faithfulness", "correctness"]\n[graders.judge]\n'
            f'type = "openai_compat"\nmodel = "m"\nbase_url = "{api.url}"\napi_key_env = "OAI_KEY"\nprice_in_per_mtok = 1\nprice_out_per_mtok = 1'))
        f.write_text(f.read_text() + "judge_cache = true\n")
        results, summary, _ = run(load_config(f))
        assert all(r.passed for r in results) and len(api.requests) == 3 and summary["judge_cost_usd"] > 0
        assert "<dimension name=\"faithfulness\">" in api.requests[0]["json"]["messages"][0]["content"]
        _, s2, _ = run(load_config(f))
        assert len(api.requests) == 3 and s2["judge_cost_usd"] == 0.0           # served from the cache
    finally:
        api.close()


def test_pairwise_and_judge_check_can_use_this_backend_and_a_cache(tmp_path, capsys):
    a, b = _pw_runs(tmp_path, *_right_wrong(4))
    api = _FakeAPI([_chat('{"winner": "B", "reason": "r"}'), _chat('{"winner": "A", "reason": "r"}')] * 20)
    try:
        argv = ["pairwise", str(a), str(b), "--rubric", "better", "--judge", "openai_compat", "--judge-opt", "model=m",
                "--judge-opt", f"base_url={api.url}", "--judge-opt", "api_key_env=OAI_KEY", "--cache", str(tmp_path / "jc")]
        assert main(argv) == 0
        out = capsys.readouterr().out
        assert "4 pairs compared (8 judge calls)" in out
        first = len(api.requests)
        assert first == 8 and main(argv) == 0                                    # the second run is served entirely from the cache
        assert len(api.requests) == first
    finally:
        api.close()
