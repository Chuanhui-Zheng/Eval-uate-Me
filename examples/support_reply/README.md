# Support reply example

This example compares a template-based support reply target with an optional OpenRouter-backed reply-generation target.

## Evaluation type

The default target is a **reference-scenario / rubric eval** for open-ended replies. `eval.toml` uses two LLM-as-a-judge
graders because there is no single exact wording for a good support reply: one judges overall quality and the other scores
whether the answer addresses the issue, gives actions, and uses an appropriate tone. The target is deterministic in this
baseline; only grading calls the LLM. `eval.llm.toml` additionally uses an LLM to write replies, so it evaluates both
generation and semantic quality and requires OpenRouter credits.

The 100 rows expand 30 authored scenarios with request references. They provide at least 100 executions but share the
original scenario intents; treat the score as a demonstration/regression check, not 100 independent situations.

From the repository root:

```bash
python3 examples/support_reply/build_cases.py
PYTHONPATH=examples/support_reply .venv/bin/python -m eval_uate_me check examples/support_reply/eval.toml
PYTHONPATH=examples/support_reply .venv/bin/python -m eval_uate_me lint examples/support_reply/eval.toml
PYTHONPATH=examples/support_reply .venv/bin/python -m eval_uate_me run examples/support_reply/eval.toml
```

Set `OPENROUTER_API_KEY` before running because the configured graders call `openai/gpt-4o-mini` through OpenRouter. To test
the LLM reply target too, run `eval.llm.toml`; that makes additional paid model calls.

Latest full-data run (2026-11-23): **23/100 passed**. The two OpenRouter judges completed without grader errors. They flagged
77 overall-quality scores and 74 dimensional scores; the main weakness is the canned baseline often gives generic replies
that miss scenario-specific facts and next steps (for example, export instructions or account deletion). Tone was the
strongest dimension (mean 0.76); issue coverage and actionability averaged 0.43 and 0.46. This measures the template target
against the rubric, not the optional LLM reply target. The run manifest does not report OpenRouter token usage or cost.
Report: [`HTML report`](reports/support-reply-2026-11-23.html) · [`summary`](reports/support-reply-2026-11-23-summary.json).
