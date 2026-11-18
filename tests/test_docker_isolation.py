"""Docker isolation tests. Opt-in: they build the eval_uate_me image and start containers.

    EVALHARNESS_DOCKER_TESTS=1 pytest tests/test_docker_isolation.py
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from eval_uate_me.cli import main
from eval_uate_me.config import load_config
from eval_uate_me.runner import run

ROOT = Path(__file__).parent.parent
TESTS_DIR = str(Path(__file__).parent)
IMAGE = "eval_uate_me:test"

pytestmark = pytest.mark.skipif(os.environ.get("EVALHARNESS_DOCKER_TESTS") != "1",
                                reason="set EVALHARNESS_DOCKER_TESTS=1 to run the Docker tests")


@pytest.fixture(scope="module", autouse=True)
def image():
    r = subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(ROOT)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"could not build the image: {r.stderr[-300:]}")


def cfg(tmp_path, target, extra="", n=1):
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"id": str(i), "input": f"q{i}", "expected": f"q{i}"}) for i in range(n)))
    f = tmp_path / "e.toml"
    f.write_text(f'plugins = ["iso_targets"]\ndataset = "c.jsonl"\n[target]\n{target}\n[[graders]]\ntype = "exact_match"\n[run]\n'
                 f'output_dir = "runs"\nisolation = "docker"\ndocker_image = "{IMAGE}"\ndocker_mounts = ["{TESTS_DIR}"]\n{extra}')
    return f


def first(tmp_path, target, extra=""):
    return run(load_config(cfg(tmp_path, target, extra)))[0][0]


def test_docker_gives_the_same_result_as_running_in_process(tmp_path):
    r = first(tmp_path, 'type = "iso_echo"')
    assert r.passed and r.result.output == "q0" and r.result.trace == [{"tool": "echo"}] and r.result.usage == {"cost_usd": 0.25}


def test_container_has_no_network(tmp_path):
    out = first(tmp_path, 'type = "iso_connect"').result.output
    assert out.startswith("blocked")


def test_root_filesystem_is_read_only_and_tmp_is_writable(tmp_path):
    assert first(tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path, 'type = "iso_write"\npath = "/etc/eval_uate_me_probe"').result.output.startswith("refused")
    assert first(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, 'type = "iso_write"\npath = "/tmp/probe"').result.output == "wrote"
    mounted = Path(TESTS_DIR) / "must_not_be_written"
    assert first(tmp_path / "c" if (tmp_path / "c").mkdir() is None else tmp_path, f'type = "iso_write"\npath = "{mounted}"').result.output.startswith("refused")
    assert not mounted.exists()                                                       # mounted read-only


def test_container_runs_as_a_non_root_user(tmp_path):
    assert first(tmp_path, 'type = "iso_uid"').result.output == 10001


def test_host_files_and_secrets_are_not_visible(tmp_path, monkeypatch):
    secret = tmp_path / "host_secret.txt"
    secret.write_text("top secret")
    d1 = tmp_path / "d1"
    d1.mkdir()
    assert first(d1, f'type = "iso_readfile"\npath = "{secret}"').result.output.startswith("unreadable")   # not mounted
    monkeypatch.setenv("EVAL_SECRET_TOKEN", "hunter2")
    d2, d3 = tmp_path / "d2", tmp_path / "d3"
    d2.mkdir()
    d3.mkdir()
    assert first(d2, 'type = "iso_env"\nname = "EVAL_SECRET_TOKEN"').result.output is None
    assert first(d3, 'type = "iso_env"\nname = "EVAL_SECRET_TOKEN"', 'env_passthrough = ["EVAL_SECRET_TOKEN"]').result.output == "hunter2"


def test_memory_limit_and_timeout_kill_the_container(tmp_path):
    d1, d2 = tmp_path / "m", tmp_path / "t"
    d1.mkdir()
    d2.mkdir()
    r = first(d1, 'type = "iso_mem"', "memory_limit_mb = 256\n")
    assert r.result.error and not r.passed
    t0 = time.perf_counter()
    r = first(d2, 'type = "iso_sleep"', "timeout_s = 3\n")
    assert "timeout after 3" in r.result.error and time.perf_counter() - t0 < 25
    time.sleep(2)
    left = subprocess.run(["docker", "ps", "-q", "--filter", "name=eval_uate_me-"], capture_output=True, text=True).stdout.strip()
    assert left == ""                                                                  # the container was killed, not leaked


def test_missing_image_and_option_validation(tmp_path, capsys):
    f = cfg(tmp_path, 'type = "iso_echo"')
    f.write_text(f.read_text().replace(IMAGE, "eval_uate_me:does-not-exist"))
    assert main(["run", str(f)]) == 2
    assert "Docker image 'eval_uate_me:does-not-exist' not found: build it with" in capsys.readouterr().err
    f.write_text(f.read_text().replace('isolation = "docker"', 'isolation = "process"'))
    assert main(["check", str(f)]) == 2 and "only apply with isolation = \"docker\"" in capsys.readouterr().err
