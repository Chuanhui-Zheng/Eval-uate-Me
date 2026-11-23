# Echo example

This small example checks that `eval-uate-me` can run a target, apply graders, and report per-case results.

## Evaluation type

This is a **closed-answer golden-label eval** with deterministic `exact_match` grading. The input is the complete answer key:
the echo target must return it unchanged. `max_latency` is a deterministic performance threshold, not an answer-quality
judgment. No reasoning or LLM is required. One case (`should-fail`) intentionally has an incorrect expected value to show
that exact-match grading catches a regression.

The dataset has 100 cases across strings, numbers, floats, and small JSON objects. Regenerate it and run the eval from the
repository root:

```bash
python3 examples/echo/build_cases.py
.venv/bin/python -m eval_uate_me check examples/echo/eval.toml
.venv/bin/python -m eval_uate_me lint examples/echo/eval.toml
.venv/bin/python -m eval_uate_me run examples/echo/eval.toml
```

Expected outcome: 99/100 exact matches; the sole failure is the deliberately incorrect `should-fail` gold label.

Latest run (2026-11-23): **99/100 passed**, 0 target errors. The expected `should-fail` mismatch is the single failure.
Report: [`HTML report`](reports/echo-2026-11-23.html) · [`summary`](reports/echo-2026-11-23-summary.json).
