# Data Sources

## cases.jsonl

20 synthetic customer-support ticket cases created for this example.

- **Source**: Handcrafted for evalharness demonstration purposes
- **Personal data**: None — all tickets are fictional
- **Licence**: MIT (same as this repository)
- **Redistribution**: Permitted

## Schema

Each case has:
- `input.subject`: ticket subject line
- `input.body`: ticket body text
- `expected.category`: one of `account_access`, `billing`, `bug`, `feature_request`, `how_to`
- `expected.urgency`: one of `low`, `medium`, `high`
- `expected.summary`: one-line human description of the issue (not graded, informational only)

## Purpose

Demonstrates the harness on a pure classification task with no tool use, contrasting
with the retrieval-loop agent in `examples/cve_triage/`.
