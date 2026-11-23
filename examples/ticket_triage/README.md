# Ticket triage example

This example classifies support tickets by category and urgency, returning a structured result checked by custom graders.

## Evaluation type

The default configuration is a **closed-answer golden-label classification eval**. Category and urgency have explicit
expected labels; `ticket_schema`, `ticket_category`, and `ticket_urgency` apply deterministic checks. The keyword target is
not an LLM and does not perform open-ended reasoning. `eval.llm.toml` swaps in an LLM target while keeping the same
reference labels and deterministic graders, so that path tests whether an LLM can infer the labels from ticket text and
requires OpenRouter credits.

The dataset contains 100 executions, expanded from 50 authored ticket scenarios with unique tracking references. Related
variants are not independent intents, so use the score as an example regression check rather than a broad production
accuracy claim.

From the repository root:

```bash
python3 examples/ticket_triage/build_cases.py
PYTHONPATH=examples/ticket_triage .venv/bin/python -m eval_uate_me check examples/ticket_triage/eval.toml
PYTHONPATH=examples/ticket_triage .venv/bin/python -m eval_uate_me lint examples/ticket_triage/eval.toml
PYTHONPATH=examples/ticket_triage .venv/bin/python -m eval_uate_me run examples/ticket_triage/eval.toml
```

To test the LLM classifier instead, set `OPENROUTER_API_KEY` and run `eval.llm.toml`; that run makes model calls for each
case.

Latest full-data run (2026-11-23): **64/100 passed** using the deterministic keyword baseline. Schema checks passed; category
was wrong in 10 cases and urgency in 28 (some cases failed both). Most of the weakness is urgency inference: the simple
keyword rules miss urgency cues or over-trigger on words such as “today”, “outage”, and “locked out”. Report:
[`HTML report`](reports/ticket-triage-2026-11-23.html) · [`summary`](reports/ticket-triage-2026-11-23-summary.json).
