"""`evalharness init` and `init-plugin`: generate a working starting point that passes `check`."""
from __future__ import annotations

import re
from pathlib import Path

from .config import ConfigError

PROJECT_FILES = {
    "eval.toml": '''name = "my-eval"
dataset = "cases.jsonl"
# plugins = ["my_plugin"]          # modules that register your own targets/graders

[target]
type = "echo"                      # replace with your system under test (see `evalharness list`)

[[graders]]
type = "exact_match"

[run]
repeats = 1                        # raise to 3+ if the target is non-deterministic
# max_cost_usd = 5                 # stop starting new jobs at this much reported usage.cost_usd

# Evaluating sensitive data? Keep only scores, and refuse anything that sends data off this machine.
# [privacy]
# store = "scores_only"
# local_only = true
''',
    "cases.jsonl": '''{"id": "greeting", "input": "hello", "expected": "hello", "metadata": {"tags": ["basic"]}}
{"id": "number", "input": 42, "expected": 42, "metadata": {"tags": ["basic"]}}
{"id": "known-failure", "input": "a", "expected": "b", "metadata": {"tags": ["edge"]}}
''',
    "cases.meta.toml": '''# Where this dataset came from and what it may be used for. `evalharness lint` checks it.
name = "my-dataset"
version = "1.0"                       # in quotes
description = "Three sample cases"
source = "written by hand"            # e.g. "NVD, CISA KEV" for public vulnerability data
retrieved = 2026-01-01                # date of the snapshot (YYYY-MM-DD)
license = "CC0-1.0"                   # the licence the data is under
contains_personal_data = false        # say explicitly; true means use [privacy] store = "scores_only"
redistributable = true                # false = must never be committed to a public repository
''',
    "README.md": '''# My eval

```bash
evalharness check eval.toml      # validate config, dataset and plugins
evalharness lint eval.toml       # is the dataset sound?
evalharness selftest eval.toml   # do the graders tell good from bad?
evalharness run eval.toml        # run it; results go in runs/
```

Each case in `cases.jsonl` is one JSON object: `id`, `input`, `expected`, and optional `metadata` (`tags`).
The sample target just echoes its input, so `known-failure` fails on purpose. Replace the target and cases.
'''
}

PLUGIN_INIT = '''"""{name}: an evalharness plugin. Replace the stubs with your system under test and your scoring."""
from evalharness import Grader, Score, Target, TargetOutput, register_grader, register_target


@register_target("{name}")
class {cls}Target(Target):
    evalharness_api = 1   # the evalharness plugin API this was written for (see `evalharness list`)
    network = False   # True if this sends case data off the machine; privacy.local_only checks it

    def __init__(self, shout: bool = False):
        self.shout = shout

    def run(self, case):
        # Call your agent / model / pipeline here. Report tool calls in `trace` and cost in `usage`
        # so max_steps, tool_use and max_cost graders (and --max-cost) work on it.
        answer = str(case.input)
        return TargetOutput(output=answer.upper() if self.shout else answer,
                            trace=[{{"step": "respond"}}], usage={{"cost_usd": 0.0}})


@register_grader("{name}_same_text")
class {cls}SameText(Grader):
    evalharness_api = 1
    name = "{name}_same_text"

    def grade(self, case, out):
        ok = str(out.output).lower() == str(case.expected).lower()
        return Score(self.name, 1.0 if ok else 0.0, ok, "" if ok else f"expected {{case.expected!r}}, got {{out.output!r}}")
'''

PLUGIN_PYPROJECT = '''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "evalharness-{dash}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["evalharness"]

# Installing this package makes the plugin visible to evalharness with no config change.
[project.entry-points."evalharness.targets"]
{name} = "{name}:{cls}Target"

[project.entry-points."evalharness.graders"]
{name}_same_text = "{name}:{cls}SameText"

[tool.setuptools]
packages = ["{name}"]
'''

PLUGIN_TOML = '''name = "{name}-eval"
dataset = "cases.jsonl"
plugins = ["{name}"]            # not needed once the package is pip-installed

[target]
type = "{name}"

[[graders]]
type = "{name}_same_text"
'''

PLUGIN_TEST = '''from evalharness import Case
from {name} import {cls}SameText, {cls}Target


def test_target_returns_the_input():
    assert {cls}Target().run(Case("a", "Hi")).output == "Hi"
    assert {cls}Target(shout=True).run(Case("a", "Hi")).output == "HI"


def test_grader_ignores_case():
    out = {cls}Target().run(Case("a", "Hi"))
    assert {cls}SameText().grade(Case("a", "Hi", "hi"), out).passed
    assert not {cls}SameText().grade(Case("a", "Hi", "bye"), out).passed
'''


def _write_all(root: Path, files: dict[str, str]) -> list[Path]:
    existing = [str(root / rel) for rel in files if (root / rel).exists()]
    if existing:
        raise ConfigError([f"refusing to overwrite existing file: {p}" for p in existing])
    written = []
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written


def init_project(directory: str | Path) -> list[Path]:
    return _write_all(Path(directory), PROJECT_FILES)


def init_plugin(name: str, directory: str | Path = ".") -> tuple[Path, list[Path]]:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in ("evalharness", "test"):
        raise ConfigError(f"plugin name '{name}' must be lowercase letters, digits and underscores, starting "
                          "with a letter (it becomes a Python package name)")
    fmt = {"name": name, "cls": "".join(w.capitalize() for w in name.split("_")), "dash": name.replace("_", "-")}
    root = Path(directory) / f"evalharness-{fmt['dash']}"
    files = {
        "pyproject.toml": PLUGIN_PYPROJECT.format(**fmt),
        f"{name}/__init__.py": PLUGIN_INIT.format(**fmt),
        "eval.toml": PLUGIN_TOML.format(**fmt),
        "cases.jsonl": PROJECT_FILES["cases.jsonl"],
        "cases.meta.toml": PROJECT_FILES["cases.meta.toml"],
        "tests/test_plugin.py": PLUGIN_TEST.format(**fmt),
    }
    return root, _write_all(root, files)
