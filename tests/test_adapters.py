"""Tests: the built-in http and python targets."""
from helpers import *  # noqa: F401,F403


def _http_cfg(tmp_path, url, extra_target="", run_extra="", n=1, graders='[[graders]]\ntype = "exact_match"'):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"a{i}", "metadata": {"context": ["ctx"]}} for i in range(n)]
    f = write_eval(tmp_path, cases, target=f'type = "http"\nurl = "{url}"\n{extra_target}', graders=graders)
    f.write_text(f.read_text() + run_extra)
    return f


def _echo_a(text):
    return _FakeAPI([(200, {"output": text})] * 5)


def test_http_target_posts_the_case_and_reads_the_output(tmp_path):
    api = _FakeAPI([(200, {"output": "a0"})])
    try:
        results, summary, _ = run(load_config(_http_cfg(tmp_path, api.url + "/answer")))
        assert results[0].passed and summary["errors"] == 0
        req = api.requests[0]
        assert req["path"] == "/answer" and req["json"] == {"id": "c0", "input": "q0", "metadata": {"context": ["ctx"]}}
        assert req["headers"]["content-type"] == "application/json"
    finally:
        api.close()


def test_http_target_maps_optional_fields_into_the_result(tmp_path):
    api = _FakeAPI([(200, {"result": {"text": "a0"}, "tool_calls": ["search", "calc"], "trace": [{"step": "plan"}],
                           "usage": {"input_tokens": 10, "output_tokens": 4}, "cost_usd": 0.02})])
    try:
        f = _http_cfg(tmp_path, api.url, 'output_field = "result.text"\nsend_metadata = false')
        r = run(load_config(f))[0][0]
        assert r.result.output == "a0" and r.result.trace == [{"step": "plan"}, {"tool": "search"}, {"tool": "calc"}]
        assert r.result.usage == {"input_tokens": 10.0, "output_tokens": 4.0, "cost_usd": 0.02}
        assert "metadata" not in api.requests[0]["json"]
    finally:
        api.close()


@pytest.mark.parametrize("reply, expected_error", [
    ((500, {"detail": "boom"}), "HTTP 500"), ((200, ["not", "an", "object"]), "must be an object"),
    ((200, {"nothing": 1}), "no 'output' field"), ((200, {"error": "model overloaded"}), "model overloaded")])
def test_http_failures_become_error_results_not_crashes(tmp_path, reply, expected_error):
    api = _FakeAPI([reply])
    try:
        r = run(load_config(_http_cfg(tmp_path, api.url)))[0][0]
        assert expected_error in r.result.error and not r.passed
    finally:
        api.close()


def test_http_unreachable_and_invalid_json(tmp_path):
    r = run(load_config(_http_cfg(tmp_path, "http://127.0.0.1:1/x", "timeout_s = 2")))[0][0]
    assert r.result.error.startswith("http error:")
    import http.server
    import threading

    class Bad(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))      # read the request first, or the close resets the connection
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>oops</html>")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Bad)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sub = tmp_path / "bad"
        sub.mkdir()
        r = run(load_config(_http_cfg(sub, f"http://127.0.0.1:{server.server_port}/")))[0][0]
        assert "invalid JSON response" in r.result.error
    finally:
        server.shutdown()


def test_http_retries_use_the_runs_retry_policy(tmp_path):
    api = _FakeAPI([(500, {}), (200, {"output": "a0"})])
    try:
        r = run(load_config(_http_cfg(tmp_path, api.url, run_extra="retries = 2\nretry_delay_s = 0\n")))[0][0]
        assert r.passed and r.result.retries == 1 and len(api.requests) == 2
    finally:
        api.close()


def test_http_secrets_come_from_the_environment_and_are_not_recorded(tmp_path, monkeypatch, capsys):
    api = _FakeAPI([(200, {"output": "a0"})])
    monkeypatch.setenv("MY_APP_TOKEN", "s3cret-value")
    try:
        f = _http_cfg(tmp_path, api.url, 'headers = {Authorization = "Bearer ${ENV:MY_APP_TOKEN}"}')
        results, _, d = run(load_config(f))
        assert api.requests[0]["headers"]["authorization"] == "Bearer s3cret-value"
        for p in d.rglob("*"):
            if p.is_file():
                assert "s3cret-value" not in p.read_text(errors="ignore"), p.name        # never written anywhere
        assert "${ENV:MY_APP_TOKEN}" in (d / "manifest.json").read_text()
        monkeypatch.delenv("MY_APP_TOKEN")
        assert main(["check", str(f)]) == 2
        assert "environment variable MY_APP_TOKEN is not set" in capsys.readouterr().err
    finally:
        api.close()


def test_http_url_scheme_is_restricted_and_local_only_refuses_it(tmp_path, capsys):
    f = _http_cfg(tmp_path, "file:///etc/passwd")
    assert main(["check", str(f)]) == 2 and "must start with http:// or https://" in capsys.readouterr().err
    g = _http_cfg(tmp_path / "lo" if (tmp_path / "lo").mkdir() is None else tmp_path, "http://127.0.0.1:1/",
                  run_extra="[privacy]\nlocal_only = true\n")
    assert main(["run", str(g)]) == 2 and "sends data off this machine" in capsys.readouterr().err


# ---- the python target ----

def _py_cfg(tmp_path, module_src, target_extra="", run_extra="", n=3, callable_name="answer", graders='[[graders]]\ntype = "exact_match"'):
    mod = f"pytarget_{abs(hash(module_src)) % 10**8}"
    (tmp_path / f"{mod}.py").write_text(module_src, encoding="utf-8")
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"Q{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases, target=f'type = "python"\ncallable = "{mod}:{callable_name}"\npaths = ["${{CONFIG_DIR}}"]\n{target_extra}',
                   graders=graders)
    f.write_text(f.read_text() + run_extra)
    return f


def test_python_target_calls_a_plain_function(tmp_path):
    f = _py_cfg(tmp_path, "def answer(text):\n    return text.upper()\n")
    results, summary, d = run(load_config(f))
    assert all(r.passed for r in results) and [r.result.output for r in results] == ["Q0", "Q1", "Q2"]
    assert json.loads((d / "manifest.json").read_text())["target"]["paths"] == ["${CONFIG_DIR}"]


def test_python_target_accepts_structured_outputs_and_target_output(tmp_path):
    src = ("from eval_uate_me import TargetOutput\n"
           "def answer(text):\n    return TargetOutput(output=text.upper(), trace=[{'tool': 'upper'}], usage={'cost_usd': 0.5})\n")
    r = run(load_config(_py_cfg(tmp_path, src)))[0][0]
    assert r.passed and r.result.trace == [{"tool": "upper"}] and r.result.usage == {"cost_usd": 0.5}
    sub = tmp_path / "d"
    sub.mkdir()
    d = run(load_config(_py_cfg(sub, "def answer(text):\n    return {'report': text.upper()}\n", graders='[[graders]]\ntype = "contains"')))[0][0]
    assert d.result.output == {"report": "Q0"} and d.passed                                   # a dict is just the output


def test_python_target_can_receive_the_whole_case(tmp_path):
    f = _py_cfg(tmp_path, "def answer(case):\n    return case.expected\n", "with_case = true")
    assert all(r.passed for r in run(load_config(f))[0])


def test_async_python_functions_run_concurrently(tmp_path):
    import time
    src = "import asyncio\nasync def answer(text):\n    await asyncio.sleep(0.2)\n    return text.upper()\n"
    f = _py_cfg(tmp_path, src, run_extra="concurrency = 30\n", n=30)
    t0 = time.perf_counter()
    results = run(load_config(f))[0]
    assert all(r.passed for r in results) and time.perf_counter() - t0 < 3     # 30 x 0.2 s would be 6 s serially


def test_python_target_exceptions_and_bad_specs_are_readable(tmp_path, capsys):
    r = run(load_config(_py_cfg(tmp_path, "def answer(text):\n    raise ValueError('nope')\n")))[0][0]
    assert r.result.error == "ValueError: nope"
    for spec, message in (("module_that_does_not_exist:fn", "cannot load"), ("pytarget_x:missing", "cannot load"), ("nocolon", "must look like"),
                          ("os:sep", "is not callable")):
        sub = tmp_path / spec.replace(":", "_")
        sub.mkdir()
        (sub / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
        (sub / "e.toml").write_text(f'dataset = "c.jsonl"\n[target]\ntype = "python"\ncallable = "{spec}"\n[[graders]]\ntype = "exact_match"\n')
        assert main(["check", str(sub / "e.toml")]) == 2, spec
        assert message in capsys.readouterr().err, spec


def test_python_target_works_under_process_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    f = _py_cfg(tmp_path, "def answer(text):\n    return text.upper()\n", run_extra='isolation = "process"\n', n=2)
    assert all(r.passed for r in run(load_config(f))[0])
