# Data Sources

## cases.jsonl

30 synthetic customer-support scenarios created for this example.

- **Source**: Handcrafted for evalharness demonstration purposes
- **Personal data**: None — all tickets and replies are fictional
- **Licence**: MIT (same as this repository)
- **Redistribution**: Permitted

## Schema

Each case has:
- `input.subject`, `input.body`: the incoming ticket
- `input.category`, `input.urgency`: pre-classified (from the ticket_triage example)
- `expected.must_cover`: rubric items the reply should address
- `expected.must_not`: things the reply must not do
- `metadata.context`: background knowledge the agent may use when drafting the reply

## Purpose

Demonstrates open-ended evaluation with an LLM judge. Unlike `cve_triage` and
`ticket_triage` (where answers are structured / enumerable), a support reply has
no single correct form — quality must be assessed on a rubric.  This is the
third type of evaluation task: open-ended generation that cannot be graded by
exact match.
