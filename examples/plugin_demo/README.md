# Calculator plugin example

This example shows an installable eval plugin with a calculator target, a custom numeric grader, and trace-based tool-use
checks.

## Evaluation type

This is a **closed-answer golden-label / deterministic reasoning eval**. Each expression has a known numeric result; the
`numeric_close` grader checks it with a tolerance. `tool_use` checks that the target recorded a `calc` tool call, and
`max_steps` checks the trace length. It does not need an LLM. Division by zero is a labeled edge case; the malformed
`unparseable` case intentionally exercises target-error reporting.

The dataset has 100 arithmetic and edge cases. Regenerate and run:

```bash
python3 examples/plugin_demo/build_cases.py
PYTHONPATH=examples/plugin_demo .venv/bin/python -m eval_uate_me check examples/plugin_demo/eval.toml
PYTHONPATH=examples/plugin_demo .venv/bin/python -m eval_uate_me lint examples/plugin_demo/eval.toml
PYTHONPATH=examples/plugin_demo .venv/bin/python -m eval_uate_me run examples/plugin_demo/eval.toml
```

This demo deliberately includes one malformed input expected to produce a target error, so the run should expose that
failure rather than silently treating an error as a correct answer.

Latest run (2026-11-23): **198/200 attempts passed** across 100 cases with `repeats = 2` (99%); the malformed case errored
on both repeats as expected. The other numeric, trace/tool-use, and step-count checks passed. Report:
[`HTML report`](reports/calculator-plugin-2026-11-23.html) · [`summary`](reports/calculator-plugin-2026-11-23-summary.json).
