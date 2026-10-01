"""Targets used by the isolation tests. Importable by worker processes through PYTHONPATH."""
import os
import subprocess
import sys
import time
from pathlib import Path

from evalharness import Target, TargetOutput, register_target


@register_target("iso_echo")
class IsoEcho(Target):
    network = False

    def run(self, case):
        return TargetOutput(output=case.input, trace=[{"tool": "echo"}], usage={"cost_usd": 0.25})


@register_target("iso_sleep")
class IsoSleep(Target):
    network = False

    def __init__(self, seconds: float = 30):
        self.seconds = seconds

    def run(self, case):
        time.sleep(self.seconds)
        return TargetOutput(output="late")


@register_target("iso_spawn")
class IsoSpawn(Target):
    """Starts a grandchild that would write a marker file later, then hangs."""
    network = False

    def __init__(self, marker: str):
        self.marker = marker

    def run(self, case):
        code = "import sys,time,pathlib; time.sleep(2.5); pathlib.Path(sys.argv[1]).write_text('alive')"
        subprocess.Popen([sys.executable, "-c", code, self.marker])
        time.sleep(30)


@register_target("iso_env")
class IsoEnv(Target):
    network = False

    def __init__(self, name: str):
        self.name = name

    def run(self, case):
        return TargetOutput(output=os.environ.get(self.name))


@register_target("iso_exit")
class IsoExit(Target):
    network = False

    def run(self, case):
        os._exit(3)


@register_target("iso_noisy")
class IsoNoisy(Target):
    network = False

    def run(self, case):
        print("chatty plugin output that must not corrupt the result")
        return TargetOutput(output="clean")


@register_target("iso_cpu")
class IsoCpu(Target):
    network = False

    def run(self, case):
        while True:
            pass


@register_target("iso_mem")
class IsoMem(Target):
    network = False

    def run(self, case):
        blob = bytearray(3 * 1024 * 1024 * 1024)
        return TargetOutput(output=len(blob))


@register_target("iso_raise")
class IsoRaise(Target):
    network = False

    def run(self, case):
        raise ValueError("boom")


@register_target("iso_net")
class IsoNet(Target):
    network = True

    def run(self, case):
        return TargetOutput(output="x")


@register_target("iso_connect")
class IsoConnect(Target):
    network = False  # (declares nothing about it: the point is to see whether the sandbox blocks it)

    def run(self, case):
        import socket
        try:
            socket.create_connection(("1.1.1.1", 80), timeout=3).close()
            return TargetOutput(output="connected")
        except OSError as e:
            return TargetOutput(output=f"blocked: {type(e).__name__}")


@register_target("iso_write")
class IsoWrite(Target):
    network = False

    def __init__(self, path: str):
        self.path = path

    def run(self, case):
        try:
            Path(self.path).write_text("x")
            return TargetOutput(output="wrote")
        except OSError as e:
            return TargetOutput(output=f"refused: {type(e).__name__}")


@register_target("iso_uid")
class IsoUid(Target):
    network = False

    def run(self, case):
        return TargetOutput(output=os.getuid())


@register_target("iso_readfile")
class IsoReadFile(Target):
    network = False

    def __init__(self, path: str):
        self.path = path

    def run(self, case):
        try:
            return TargetOutput(output=Path(self.path).read_text())
        except OSError as e:
            return TargetOutput(output=f"unreadable: {type(e).__name__}")


@register_target("iso_async_only")
class IsoAsyncOnly(Target):
    """Defines only arun: must still work wherever a sync run() is needed (workers, threads)."""
    network = False

    async def arun(self, case):
        import asyncio
        await asyncio.sleep(0.01)
        return TargetOutput(output=case.input)
