"""`eval_uate_me init` and `init-plugin`: generate a working starting point that passes `check`."""
from __future__ import annotations

import re
from pathlib import Path

from .config import ConfigError

PROJECT_FILES = {
    "eval.toml": '''name = "my-eval"
dataset = "cases.jsonl"
# plugins = ["my_plugin"]          # modules that register your own targets/graders

[target]
type = "echo"                      # replace with your system under test (see `eval_uate_me list`)

[[graders]]
type = "exact_match"

# ── LLM-as-judge (remove the lines above and uncomment this block to use it) ──
# [[graders]]
# type = "llm_judge"
# pass_threshold = 0.6             # 0–1 average across all dimensions; cases below this fail
# dimensions = ["correctness", "helpfulness", "safety"]
# rubric = """
# You are evaluating an AI assistant's response.
# Question: {{ case.input }}
# Response: {{ output }}
# Score each dimension 1–5. correctness: factually accurate? helpfulness: useful answer?
# safety: no harmful content?
# """
#
# [graders.judge]                  # the LLM used to score
# type = "openai_compat"
# base_url = "https://openrouter.ai/api/v1"
# model = "openai/gpt-4o-mini"
# api_key_env = "OPENROUTER_API_KEY"   # name of the environment variable holding your API key

# ── Evaluating a RAG system? ────────────────────────────────────────────────
# Your agent.py should return a JSON string that includes the retrieved evidence
# so the judge can verify faithfulness. Without it the judge cannot tell whether
# the answer is grounded in sources and will score faithfulness very low.
#
# Minimal example agent.py:
#
#   import json, urllib.request
#
#   def ask(input: str) -> str:
#       # call your RAG system here
#       resp = call_rag(input)
#       return json.dumps({
#           "answer":   resp["answer"],
#           "status":   resp["status"],       # e.g. "answer" / "no_evidence"
#           "claims":   resp["claims"],        # ← list of {"text":"...", "citations":["id",...]}
#           "citations": resp["citations"],    # ← source chunk IDs
#       })
#
# Then reference {{ output }} in your rubric and tell the judge:
#   - Use "claims[N].citations" to verify faithfulness (has citations = grounded)
#   - "status" == "answer" or "qualified" means the system gave a substantive response
#
# Skipping "claims"/"citations" is the most common cause of artificially low
# faithfulness scores when evaluating RAG pipelines with llm_judge.

[run]
repeats = 1                        # raise to 3+ if the target is non-deterministic
# max_cost_usd = 5                 # stop starting new jobs at this much reported usage.cost_usd

# [split]
# dev_fraction = 0.7               # hold out 30% as a blind test set; run uses the dev portion

# Evaluating sensitive data? Keep only scores, and refuse anything that sends data off this machine.
# [privacy]
# store = "scores_only"
# local_only = true
''',
    "cases.jsonl": '''{"id": "greeting", "input": "hello", "expected": "hello", "metadata": {"tags": ["basic"]}}
{"id": "number", "input": 42, "expected": 42, "metadata": {"tags": ["basic"]}}
{"id": "known-failure", "input": "a", "expected": "b", "metadata": {"tags": ["edge"]}}
''',
    "cases.meta.toml": '''# Where this dataset came from and what it may be used for. `eval_uate_me lint` checks it.
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
eval_uate_me check eval.toml      # validate config, dataset and plugins
eval_uate_me lint eval.toml       # is the dataset sound?
eval_uate_me selftest eval.toml   # do the graders tell good from bad?
eval_uate_me run eval.toml        # run it; results go in runs/
```

Each case in `cases.jsonl` is one JSON object: `id`, `input`, `expected`, and optional `metadata` (`tags`).
The sample target just echoes its input, so `known-failure` fails on purpose. Replace the target and cases.
'''
}

PLUGIN_INIT = '''"""{name}: an eval_uate_me plugin. Replace the stubs with your system under test and your scoring."""
from eval_uate_me import Grader, Score, Target, TargetOutput, register_grader, register_target


@register_target("{name}")
class {cls}Target(Target):
    eval_uate_me_api = 1   # the eval_uate_me plugin API this was written for (see `eval_uate_me list`)
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
    eval_uate_me_api = 1
    name = "{name}_same_text"

    def grade(self, case, out):
        ok = str(out.output).lower() == str(case.expected).lower()
        return Score(self.name, 1.0 if ok else 0.0, ok, "" if ok else f"expected {{case.expected!r}}, got {{out.output!r}}")
'''

PLUGIN_PYPROJECT = '''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "eval_uate_me-{dash}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["eval_uate_me"]

# Installing this package makes the plugin visible to eval_uate_me with no config change.
[project.entry-points."eval_uate_me.targets"]
{name} = "{name}:{cls}Target"

[project.entry-points."eval_uate_me.graders"]
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

PLUGIN_TEST = '''from eval_uate_me import Case
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
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in ("eval_uate_me", "test"):
        raise ConfigError(f"plugin name '{name}' must be lowercase letters, digits and underscores, starting "
                          "with a letter (it becomes a Python package name)")
    fmt = {"name": name, "cls": "".join(w.capitalize() for w in name.split("_")), "dash": name.replace("_", "-")}
    root = Path(directory) / f"eval_uate_me-{fmt['dash']}"
    files = {
        "pyproject.toml": PLUGIN_PYPROJECT.format(**fmt),
        f"{name}/__init__.py": PLUGIN_INIT.format(**fmt),
        "eval.toml": PLUGIN_TOML.format(**fmt),
        "cases.jsonl": PROJECT_FILES["cases.jsonl"],
        "cases.meta.toml": PROJECT_FILES["cases.meta.toml"],
        "tests/test_plugin.py": PLUGIN_TEST.format(**fmt),
    }
    return root, _write_all(root, files)
