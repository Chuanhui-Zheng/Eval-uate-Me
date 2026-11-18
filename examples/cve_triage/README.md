# cve_triage: public-data agent evaluation example

This example evaluates a structured CVE triage agent against a frozen snapshot of 100 public CVEs selected from the CISA
Known Exploited Vulnerabilities catalog and enriched with NVD 2.0 records. The target is deterministic so the harness can be
tested offline; an LLM-backed target or judge can be substituted through the existing OpenAI-compatible backend.

The cases cover known exploited vulnerabilities, severity/CVSS and CWE extraction, product identity, authoritative references,
unknown identifiers, and prompt injection planted inside vulnerability descriptions. Deliberate target flaws are available for
`meta-eval`: omitted fields, wrong severity, fabricated products/references, unsupported exploitation claims, missing citations,
and instruction injection.

```bash
export PYTHONPATH=examples/cve_triage
.venv/bin/python examples/cve_triage/data/build_dataset.py
.venv/bin/python -m eval_uate_me check examples/cve_triage/eval.toml
.venv/bin/python -m eval_uate_me lint examples/cve_triage/eval.toml
.venv/bin/python -m eval_uate_me selftest examples/cve_triage/eval.toml
.venv/bin/python -m eval_uate_me run examples/cve_triage/eval.toml
.venv/bin/python -m eval_uate_me meta-eval examples/cve_triage/eval.toml --auto
```

The committed dataset has 420 cases: 100 factual cases, 300 prompt-injection variants, and 20 unknown identifiers. Cases are
split by CVE group, so variants of one vulnerability cannot leak across development and held-out results. The snapshot is for
research and evaluation only. It is not a vulnerability scanner or a replacement for vendor advisories.

## Run an actual LLM agent

The offline config tests the harness with the deterministic reference target. `eval.llm.toml` sends each case to an
OpenAI-compatible model through OpenRouter. The model starts with the CVE ID and description, then must call the local
`lookup_cve` retrieval tool before producing its report. The tool returns the frozen NVD/CISA record, so the test measures
tool use, evidence grounding, prompt-injection resistance, and structured output without putting the answer in the initial
prompt:

```bash
source ~/.zshrc
export PYTHONPATH=examples/cve_triage
.venv/bin/python -m eval_uate_me check examples/cve_triage/eval.llm.toml
.venv/bin/python -m eval_uate_me run examples/cve_triage/eval.llm.toml --split dev
```

This requires `OPENROUTER_API_KEY` and an account with model credits. It is intentionally separate from the offline baseline:
the LLM run is a real agent measurement, while the deterministic run validates the evaluator itself. The expanded dataset has
the held-out run must be completed with a funded API account before reporting a generalization score. The retrieval tool is
local and deterministic for reproducibility; replacing it with a live NVD/CISA adapter is a follow-up integration.

`eval.llm.evidence.toml` is a separate control configuration that supplies the complete frozen record without a tool call. Its
perfect score is useful as a plumbing control, but it is not the result to quote on a resume. The retrieval benchmark has not
yet been run after implementation because the configured OpenRouter account needs more credits.
