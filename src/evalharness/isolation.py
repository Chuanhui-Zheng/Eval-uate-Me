"""Run a target somewhere it cannot hang or hog the harness.

  isolation = "none"     the target runs in this process. `timeout_s` is then only a soft limit: the harness stops waiting and
                         records an error, but the abandoned call keeps running in its thread (Python cannot kill a thread).
  isolation = "docker"   every attempt runs in a throwaway container: no network (`docker_network = "none"`), read-only root
                         filesystem, a small tmpfs /tmp, non-root user, all capabilities dropped, process/memory/CPU limits, and
                         only the folders in `docker_mounts` visible (read-only). A real sandbox, at the cost of ~1 s start-up per
                         attempt and a local Docker with the evalharness image built (`docker build -t evalharness .`).
  isolation = "process"  every attempt runs in a fresh worker process in its own process group: a HARD timeout that kills the
                         whole group, CPU and memory limits (where the OS supports them), and an environment scrubbed down to
                         what the target needs. This is NOT a security sandbox: the code can still read and write your files and
                         use the network.
"""
from __future__ import annotations

import json
import math
import os
import signal
import uuid
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path

from .execution import is_async
from .models import Case, TargetOutput
from .targets import Target
from .worker import SENTINEL

MAX_OUTPUT_BYTES = 20 * 1024 * 1024
_WARNED_LIMITS: list[bool] = []


def parse_worker_output(stdout: str, stderr: str, returncode: int | None) -> TargetOutput:
    for line in reversed(stdout.splitlines()):
        if line.startswith(SENTINEL):
            try:
                return TargetOutput(**json.loads(line[len(SENTINEL):]))
            except (ValueError, TypeError) as e:
                return TargetOutput(error=f"worker returned an unreadable result: {e}")
    tail = " ".join(stderr.strip().splitlines()[-3:])[:300]
    return TargetOutput(error=f"worker exited with code {returncode} and no result" + (f": {tail}" if tail else ""))


def _limits(cpu_s: float | None, memory_mb: int | None):
    """preexec function applying resource limits in the child (POSIX only)."""
    def apply() -> None:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if cpu_s:
            resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_s) + 1, int(cpu_s) + 1))
        if memory_mb and sys.platform == "linux":  # not enforced by macOS, so only set where it works
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    return apply


class IsolatedTarget(Target):
    """Wraps a target spec; each run() starts a worker, sends it the case and reads back the result."""

    def __init__(self, spec: dict, plugins: list[str], mode: str = "process", timeout_s: float | None = None,
                 cpu_limit_s: float | None = None, memory_limit_mb: int | None = None,
                 env_passthrough: list[str] | None = None, network: bool | None = None, **docker):
        self.spec, self.plugins, self.mode = spec, plugins, mode
        self.timeout_s, self.cpu_limit_s, self.memory_limit_mb = timeout_s, cpu_limit_s, memory_limit_mb
        self.env_passthrough = env_passthrough or []
        self.network = network
        self.docker = docker

    def _request(self, case: Case) -> str:
        return json.dumps({"plugins": self.plugins, "target": self.spec, "case": asdict(case)}, ensure_ascii=False, default=str)

    def run(self, case: Case) -> TargetOutput:
        with tempfile.TemporaryDirectory(prefix="evalharness-", ignore_cleanup_errors=True) as home:
            cmd, env, popen_kwargs = self._command(home)
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace", env=env, **popen_kwargs)
            except OSError as e:
                return TargetOutput(error=f"could not start the worker: {e}")
            try:
                stdout, stderr = proc.communicate(self._request(case), timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                self._kill(proc)
                proc.communicate()
                return TargetOutput(error=f"timeout after {self.timeout_s}s: the worker was killed")
            if len(stdout) + len(stderr) > MAX_OUTPUT_BYTES:
                return TargetOutput(error=f"worker produced more than {MAX_OUTPUT_BYTES // 1024 // 1024} MB of output")
            return parse_worker_output(stdout, stderr, proc.returncode)

    # -- process mode ------------------------------------------------------------------------------------------
    def _command(self, home: str):
        if self.mode == "docker":
            return self._docker_command()
        env = {"PATH": os.environ.get("PATH", ""), "HOME": home, "TMPDIR": home, "LANG": "C.UTF-8",
               "PYTHONPATH": os.environ.get("PYTHONPATH", ""), "PYTHONIOENCODING": "utf-8"}
        env.update({k: os.environ[k] for k in self.env_passthrough if k in os.environ})
        kwargs: dict = {}
        if sys.platform == "win32":
            # Python on Windows needs a few system variables to start; a new process group lets us kill the whole tree
            env.update({k: os.environ[k] for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT") if k in os.environ})
            env["TEMP"] = env["TMP"] = home
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            if (self.cpu_limit_s or self.memory_limit_mb) and not _WARNED_LIMITS:
                _WARNED_LIMITS.append(True)
                print("warning: cpu_limit_s and memory_limit_mb are not enforced on Windows in process mode; "
                      "only timeout_s is (use isolation = \"docker\" for limits)", file=sys.stderr)
        else:
            kwargs["start_new_session"] = True
            kwargs["preexec_fn"] = _limits(self.cpu_limit_s, self.memory_limit_mb)
        return [sys.executable, "-m", "evalharness.worker"], env, kwargs

    # -- docker mode -------------------------------------------------------------------------------------------
    def _docker_command(self):
        d = self.docker
        self._container = f"evalharness-{uuid.uuid4().hex[:12]}"
        cmd = ["docker", "run", "--rm", "-i", "--init", "--name", self._container, "--network", d.get("net", "none"),
               "--read-only", "--tmpfs", "/tmp:rw,size=64m", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", "256", "-w", "/tmp"]
        if self.memory_limit_mb:
            cmd += ["--memory", f"{self.memory_limit_mb}m", "--memory-swap", f"{self.memory_limit_mb}m"]
        if self.cpu_limit_s:
            cmd += ["--ulimit", f"cpu={math.ceil(self.cpu_limit_s)}"]
        mounts = [str(Path(m).resolve()) for m in d.get("mounts", [])]
        for m in mounts:
            cmd += ["-v", f"{m}:{m}:ro"]  # same path inside, so options that point at host paths keep working
        if mounts:
            cmd += ["-e", "PYTHONPATH=" + os.pathsep.join(mounts)]
        for name in self.env_passthrough:
            if name in os.environ:
                cmd += ["-e", name]  # the value is taken from the docker client's environment, never put on the command line
        cmd += [d.get("image", "evalharness:latest"), "worker"]
        return cmd, dict(os.environ), ({"start_new_session": True} if sys.platform != "win32" else {})

    def _kill(self, proc: subprocess.Popen) -> None:
        if self.mode == "docker" and getattr(self, "_container", None):
            subprocess.run(["docker", "kill", self._container], capture_output=True, timeout=20)  # killing the client alone leaves the container
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)  # the whole tree
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the whole group: the target's own children die too
        except (ProcessLookupError, PermissionError, AttributeError):
            proc.kill()


class SoftTimeoutTarget(Target):
    """isolation = "none" with timeout_s: stop waiting after the limit. The call is abandoned, not killed."""

    def __init__(self, inner: Target, timeout_s: float):
        self.inner, self.timeout_s = inner, timeout_s
        self.network = getattr(inner, "network", None)

    def run(self, case: Case) -> TargetOutput:
        box: list[TargetOutput] = []

        def call() -> None:
            try:
                box.append(self.inner.run(case))
            except Exception as e:  # noqa: BLE001
                box.append(TargetOutput(error=f"{type(e).__name__}: {e}"))

        t = threading.Thread(target=call, daemon=True)
        t.start()
        t.join(self.timeout_s)
        if t.is_alive():
            return TargetOutput(error=f"timeout after {self.timeout_s}s (in-process: the call was abandoned, not killed; "
                                      "use isolation = \"process\" for a hard limit)")
        return box[0]


def check_docker(image: str) -> None:
    """Fail early, with the fix, if Docker or the image is missing."""
    from .config import ConfigError
    try:
        r = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConfigError(f"isolation = \"docker\" needs a working Docker CLI ({e})") from e
    if r.returncode != 0:
        raise ConfigError(f"Docker image '{image}' not found: build it with `docker build -t {image} .` in the "
                          "evalharness repository (or set run.docker_image)")


def wrap_target(cfg, real: Target, spec: dict) -> Target:
    """Apply the config's isolation and timeout to a target built from `spec`."""
    if cfg.isolation == "none":
        if is_async(real):
            return real  # the async executor enforces timeout_s by cancelling the coroutine
        return SoftTimeoutTarget(real, cfg.timeout_s) if cfg.timeout_s else real
    docker = {}
    if cfg.isolation == "docker":
        check_docker(cfg.docker_image)
        docker = {"image": cfg.docker_image, "mounts": cfg.docker_mounts, "net": cfg.docker_network}
    return IsolatedTarget(spec, cfg.plugins, cfg.isolation, cfg.timeout_s, cfg.cpu_limit_s, cfg.memory_limit_mb,
                          cfg.env_passthrough, getattr(real, "network", None), **docker)
