"""Runs the commands in docs/TUTORIAL.md so the tutorial cannot drift from the tool.

Blocks tagged `bash tutorial` are executed line by line; `# expect: TEXT` asserts the command's output contains TEXT, and the word
RUN is replaced by the latest run directory. Blocks tagged `file=PATH` are written to disk before the next commands.
"""
import re
import subprocess
import sys
from pathlib import Path

DOC = Path(__file__).parent.parent / "docs" / "TUTORIAL.md"
BLOCK = re.compile(r"```(\w+)\s+([^\n]*)\n(.*?)```", re.S)


def latest_run(cwd: Path) -> str:
    runs = sorted((cwd / "runs").iterdir(), key=lambda p: p.stat().st_mtime)
    return str(runs[-1]) if runs else "RUN"


def test_tutorial_commands_work_as_documented(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("PYTHONUTF8", "1")
    cwd, ran = tmp_path, 0
    for lang, info, body in BLOCK.findall(DOC.read_text(encoding="utf-8")):
        if info.startswith("file="):
            (cwd / info[5:]).write_text(body, encoding="utf-8")
        elif info.strip() == "tutorial":
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                code, _, expect = line.partition("# expect:")
                parts = code.split()
                if parts[0] == "cd":
                    cwd = cwd / parts[1]
                    continue
                assert parts[0] == "evalharness", line
                args = [latest_run(cwd) if a == "RUN" else a for a in parts[1:]]
                r = subprocess.run([sys.executable, "-m", "evalharness", *args], cwd=cwd, capture_output=True, text=True,
                                   env={**os.environ, "PYTHONUTF8": "1"})
                assert r.returncode == 0, f"`{line}` exited {r.returncode}\n{r.stdout}\n{r.stderr}"
                if expect.strip():
                    assert expect.strip() in r.stdout + r.stderr, f"`{line}`: expected {expect.strip()!r} in\n{r.stdout}{r.stderr}"
                ran += 1
    assert ran >= 10                                   # the tutorial really was executed, not skipped
