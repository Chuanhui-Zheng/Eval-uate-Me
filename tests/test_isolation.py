"""Tests: isolation."""
from helpers import *  # noqa: F401,F403


# ---- isolation: hard timeouts, limits, scrubbed environment ----


def test_process_isolation_gives_the_same_result_as_running_in_process(tmp_path, monkeypatch):
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_echo"', n=3)
    plain, _, _ = run(load_config(f))
    f.write_text(f.read_text() + 'isolation = "process"\n')
    iso, summary, d = run(load_config(f))
    assert [r.result.output for r in iso] == [r.result.output for r in plain] == ["q0", "q1", "q2"]
    assert all(r.passed for r in iso) and iso[0].result.trace == [{"tool": "echo"}] and iso[0].result.usage == {"cost_usd": 0.25}
    assert json.loads((d / "manifest.json").read_text())["target"] == {"type": "iso_echo"}


def test_hard_timeout_kills_a_hanging_target_and_the_run_continues(tmp_path, monkeypatch):
    import time
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_sleep"', run_extra='isolation = "process"\ntimeout_s = 1\nconcurrency = 2\n', n=2)
    t0 = time.perf_counter()
    results, summary, _ = run(load_config(f))
    assert time.perf_counter() - t0 < 10                              # nowhere near the 30 s the target wanted
    assert all("timeout after 1" in r.result.error and "killed" in r.result.error for r in results)
    assert summary["errors"] == 2 and summary["pass_rate"] == 0.0


def test_timeout_kills_the_targets_own_child_processes_too(tmp_path, monkeypatch):
    import time
    marker = tmp_path / "grandchild_ran"
    f = _iso_cfg(tmp_path, monkeypatch, f'type = "iso_spawn"\nmarker = "{marker.as_posix()}"', run_extra='isolation = "process"\ntimeout_s = 1\n')
    results, _, _ = run(load_config(f))
    assert "timeout" in results[0].result.error
    time.sleep(3.5)                                                   # longer than the grandchild's delay
    assert not marker.exists()                                        # it died with the process group


def test_environment_is_scrubbed_unless_passed_through(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_SECRET_TOKEN", "hunter2")
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_env"\nname = "EVAL_SECRET_TOKEN"', run_extra='isolation = "process"\n')
    assert run(load_config(f))[0][0].result.output is None            # the worker never saw it
    f.write_text(f.read_text() + 'env_passthrough = ["EVAL_SECRET_TOKEN"]\n')
    assert run(load_config(f))[0][0].result.output == "hunter2"       # explicitly allowed
    monkeypatch.setenv("EVAL_SECRET_TOKEN", "x")
    plain = _iso_cfg(tmp_path / "p" if (tmp_path / "p").mkdir() is None else tmp_path, monkeypatch,
                     'type = "iso_env"\nname = "EVAL_SECRET_TOKEN"')
    assert run(load_config(plain))[0][0].result.output == "x"         # in-process, nothing is hidden


def test_worker_failures_become_errors_not_crashes(tmp_path, monkeypatch):
    for target, expected in (('type = "iso_exit"', "exited with code 3 and no result"), ('type = "iso_raise"', "ValueError: boom")):
        sub = tmp_path / target.split('"')[1]
        sub.mkdir()
        r = run(load_config(_iso_cfg(sub, monkeypatch, target, run_extra='isolation = "process"\n')))[0][0]
        assert expected in r.result.error and not r.passed
    sub = tmp_path / "noisy"
    sub.mkdir()
    noisy = run(load_config(_iso_cfg(sub, monkeypatch, 'type = "iso_noisy"', run_extra='isolation = "process"\n',
                                     graders='[[graders]]\ntype = "contains"')))[0][0]
    assert noisy.result.output == "clean" and noisy.result.error is None    # chatter went to stderr


@pytest.mark.skipif(sys.platform == "win32", reason="CPU limits (setrlimit) do not exist on Windows")
def test_cpu_limit_stops_a_busy_loop(tmp_path, monkeypatch):
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_cpu"', run_extra='isolation = "process"\ncpu_limit_s = 1\n')
    r = run(load_config(f))[0][0]
    assert r.result.error and "exited with code" in r.result.error and "no result" in r.result.error


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="memory limits are enforced on Linux only")
def test_memory_limit_stops_a_memory_hog(tmp_path, monkeypatch):
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_mem"', run_extra='isolation = "process"\nmemory_limit_mb = 512\n')
    r = run(load_config(f))[0][0]
    assert r.result.error and ("MemoryError" in r.result.error or "no result" in r.result.error)


def test_soft_timeout_without_isolation_abandons_the_call(tmp_path, monkeypatch):
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_sleep"\nseconds = 3', run_extra="timeout_s = 0.5\n")
    r = run(load_config(f))[0][0]
    assert "timeout after 0.5s (in-process: the call was abandoned, not killed" in r.result.error


def test_isolation_config_validation_and_local_only_still_sees_the_real_target(tmp_path, monkeypatch, capsys):
    f = _iso_cfg(tmp_path, monkeypatch, 'type = "iso_echo"', run_extra='isolation = "vm"\ntimeout_s = 0\n')
    assert main(["check", str(f)]) == 2
    err = capsys.readouterr().err
    assert 'isolation must be "none", "process" or "docker"' in err and "timeout_s must be a number of seconds > 0" in err
    f.write_text(f.read_text().replace('isolation = "vm"', "memory_limit_mb = 64").replace("timeout_s = 0", ""))
    assert main(["check", str(f)]) == 2 and "need isolation" in capsys.readouterr().err
    net = _iso_cfg(tmp_path / "n" if (tmp_path / "n").mkdir() is None else tmp_path, monkeypatch, 'type = "iso_net"',
                   run_extra='isolation = "process"\n')
    net.write_text(net.read_text() + "[privacy]\nlocal_only = true\n")
    assert main(["run", str(net)]) == 2 and "sends data off this machine" in capsys.readouterr().err


def test_meta_eval_honours_isolation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PYTHONPATH", TESTS_DIR)
    f = _meta_cfg(tmp_path, '[[graders]]\ntype = "exact_match"', [("nothing", "null")], n=8)
    f.write_text(f.read_text() + 'isolation = "process"\ntimeout_s = 20\n')
    assert main(["meta-eval", str(f)]) == 0 and "mutation score: 100%" in capsys.readouterr().out


def test_plugin_options_may_be_called_name_or_kind(tmp_path):
    """Regression: registry helpers took a parameter called `name`, so a plugin option of that name collided."""
    f = write_eval(tmp_path, [{"id": "1", "input": "a", "expected": "a"}], graders=(
        '[[graders]]\ntype = "llm_judge"\nname = "my_judge"\nrubric = "r"\n[graders.judge]\ntype = "test_scripted"'))
    results, _, _ = run(load_config(f))
    assert results[0].scores[0].grader == "my_judge"
