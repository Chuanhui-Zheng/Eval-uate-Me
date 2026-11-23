# eval_uate_me

**Run an evaluation, gate regressions, and test whether your evaluation catches a broken agent.**

A small, plugin-based harness for repeatable LLM-agent evaluations. Zero runtime dependencies (Python ≥ 3.11).

```
cases.jsonl ──► Runner ──► Target ──► output ──► Graders ──► results + summary + gate
```

**Status:** v1.0.8 is the current stable release. Includes multi-turn tool-loop retrieval, session memory, process/Docker sandbox isolation, typed traces, interactive trace reports, and worked examples for CVE triage, classification, open-ended support replies, and a LangGraph customer-support agent. Zero runtime dependencies; deterministic examples run offline. Not published to PyPI; install from a clone or a release wheel.

## The main path in three commands

### 1. Run an evaluation

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/eval_uate_me init my-eval && cd my-eval
../.venv/bin/eval_uate_me check eval.toml
../.venv/bin/eval_uate_me run eval.toml
```

`init` creates a runnable starter project (config, cases, provenance file). Point the `[target]` at your agent: use the built-in `http` or `python` type for a service or a function, or write a plugin class for anything stateful. `check` validates config and data before anything runs.

### 2. Gate regressions in CI

```bash
eval_uate_me run eval.toml
eval_uate_me baseline promote --config eval.toml   # writes eval.baseline.json — commit it
eval_uate_me gate eval.toml                        # exit 0 pass, 1 regression, 2 cannot decide
```

The gate compares the latest run with the baseline. Add rules to the config once you have a baseline:

```toml
[gate]
significant_only = true      # fail only when the drop is statistically significant
[gate.min]
pass_rate = 0.90
[gate.max_drop]
pass_rate = 0.05
```

A metric the rules name but the run lacks is a failure (a typo must not silently pass). A different dataset or split is refused rather than compared. GitHub Actions gets `::error::` annotations automatically.

### 3. Test whether the evaluation catches a broken agent (`meta-eval`)

```toml
[[mutants]]
name = "drops-the-answer"
[mutants.target]
type = "my_agent"
flaw = "omit"
```

```bash
eval_uate_me meta-eval eval.toml           # killed / survived / no-op per mutant
eval_uate_me meta-eval eval.toml --auto    # damage every field of the real outputs; name blind spots
```

**killed** = the evaluation scored this mutant significantly lower. **survived** = the evaluation cannot tell it from the real agent — a blind spot to fix with a better grader or more cases. `--auto` finds the blind spots you did not think to write.

`examples/cve_triage/` is the primary worked example: a retrieval-loop agent over 100 public CISA KEV vulnerabilities,
420 grouped cases, **11 graders** (schema, identity, CVSS, CWE, KEV flag, affected product, references, fabrication,
tool-call assertion, prompt-injection resistance, safety/disclaimer), and deliberate mutants for each failure mode.
Multi-model benchmark on the **dev split** (25 cases each): deepseek-v4.1-flash 96.7%, gpt-4o-mini 91.6%, claude-haiku-5.5 91.6% (v1.0.5 run). Held-out multi-model results not yet published.

`examples/ticket_triage/` is a second worked example: 50 customer-support tickets across 5 categories and 3 urgency
levels, **3 graders** (schema, category, urgency), and an LLM target (`eval.llm.toml`) for benchmarking real models
alongside the deterministic oracle. Demonstrates the harness on a pure-classification task with no tool use.

`examples/support_reply/` is a third worked example: 30 customer-support tickets where the agent must **draft a reply**
rather than classify. No single correct answer exists — quality is judged by an LLM judge on three dimensions
(addresses issue, actionable, appropriate tone). Demonstrates the harness on open-ended generation, the third evaluation
paradigm alongside factual lookup and classification.

`examples/customer_triage_eval/` evaluates a public LangGraph customer-support agent with 100 synthetic cases, a
deterministic contract grader, an LLM judge and graph-node traces. Its README explains setup, running the evaluation and
the limits of the sample results.

## Platforms

CI runs on **Linux** (Python 3.11 and 3.12), **Windows** (3.11 and 3.12) and **macOS** (3.12). Docker sandbox tests run on Linux. On Windows, `cpu_limit_s` and `memory_limit_mb` are not enforced in `process` isolation; use `docker` for hard limits.

## Documentation

| File | Contents |
|---|---|
| [docs/TUTORIAL.md](docs/TUTORIAL.md) | step-by-step walkthrough; every command is run by the tests |
| [docs/REFERENCE.md](docs/REFERENCE.md) | every command, option and config key |
| [docs/API.md](docs/API.md) | writing targets, graders and judge backends (plugin API) |
| [docs/VERSIONING.md](docs/VERSIONING.md) | what is stable from 1.0 and what is not |
| [docs/DESIGN.md](docs/DESIGN.md) | trade-offs and known limits |
| [docs/ROADMAP.md](docs/ROADMAP.md) | what shipped, what is pending |
| [docs/RELEASING.md](docs/RELEASING.md) | how to cut a release |

Licensed under the [MIT licence](LICENSE).
