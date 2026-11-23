# Roadmap

Goal: a harness that outside researchers can run on their own (possibly sensitive) data and send feedback on,
not a demo. Items are ordered by what blocks real use first.

Status: `done` / `next` / `later`.

The v1.0.1 patch release expanded the CVE benchmark and added an evidence-withholding diagnostic. v1.0.2 added a local
retrieval-tool loop; v1.0.3 records its first complete live measurement with the held-out-look caveat documented in the results.
v1.0.4 introduced fuzzy product matching and a four-model comparison. v1.0.5 generalised the retrieval loop to multi-turn,
added session memory, process/Docker sandbox isolation with env_passthrough, an eleventh grader (cve_tool_call), and a second
worked example (ticket_triage). v1.0.6 added the TraceStep public type, formalised the trace schema, and shipped an interactive
JS trace viewer in the HTML report. v1.0.7 added a third worked example (support_reply) covering open-ended generation with
LLM judge grading. v1.0.8 adds a LangGraph customer-support evaluation example, removes the implicit mock judge, and expands
example datasets and instructions. The next planned work is AI-generated evaluation and red-team campaigns with separate reports.

## v0.4: usable by someone else
| Item | Why | Status |
|---|---|---|
| Separate target errors from wrong answers in metrics | An outage must not read as a capability failure | done |
| Grader roles: `required` vs `advisory` | One minor check should not sink the overall result | done |
| Config validation and friendly errors, `check` command | Researchers cannot read Python tracebacks | done |
| Privacy mode: `scores_only` storage, `local_only` guard | Sensitive inputs must not be written to results, reports or the cache | done |
| `init` scaffolds for a project and a plugin | A five-minute start | done |
| Dockerfile and a buildable wheel | Runs anywhere; PyPI publishing stays a manual decision | done |

## v0.5: collecting feedback (released as v0.5.0)
| Item | Why | Status |
|---|---|---|
| Human labelling workflow: export a sheet, import labels, list disagreements | Feedback should become data that calibrates graders | done |

## v0.6: knowing where the data came from, and not fooling yourself (released as v0.6.0)
| Item | Why | Status |
|---|---|---|
| Dataset provenance file (source, licence, date, personal-data and redistribution flags) checked by `lint` | Public sources have terms; restricted data must not reach a public repository | done |
| Dev / held-out splits, `split` command, `run --split`, held-out look counter | Tuning on the test set ruins it | done |

## v0.7: trusting the scores (released as v0.7.0)
| Item | Why | Status |
|---|---|---|
| Sample-size planning (`power`), permutation p-values, Holm-corrected per-tag comparison | Say how many cases are needed and do not mistake luck for a real slice effect | done |
| Judge panels with a vote | Several different judges reduce any one judge's bias | done |
| Position-debiased pairwise comparison | Head-to-head judging without letting position decide | done |
| `judge-check`: length, injection, position and repeatability probes | An unchecked LLM judge is an unverified metric | done |
| Carry labels across runs when the output is identical | Reviewers should not label the same text twice | done |

## v0.8: real-world validation (released as v0.8.0, partly: judge calibration needs your input)
| Item | Why | Status |
|---|---|---|
| CVE triage example plugin as a separate package | A public-data security target | done in v1.0.0 (deterministic reference agent, NVD/CISA snapshot) |
| Public data sources list with licences | A real dataset, legally usable | done for NVD/CISA (`examples/cve_triage/data/SOURCES.md`) |
| Dataset built from public data with provenance and splits | The data the evaluation runs on | done (100 CISA KEV CVEs, 420 grouped factual/adversarial cases) |
| Deliberately flawed agent variants and `meta-eval` | Proof the harness catches bad agents | done in the CVE example (six mutants) |
| Results write-up with real numbers | The evidence everything else exists to produce | done (retrieval dev 69.2%, held-out 66.5%; post-tuning caveat) |
| Live LLM agent/judge run and calibration against human labels | A deterministic baseline is not an LLM benchmark | retrieval run done; human calibration next |

## v0.9: operating it (released as v0.9.0)
| Item | Why | Status |
|---|---|---|
| Hard timeouts, process isolation, docker sandbox | Safe and robust to evaluate code you did not write | done (process is not a security boundary; docker is) |
| Run history and trends with a regression check | Spot regressions over time | done |
| Markdown comparison for PR comments and a workflow template | Regressions visible in review | done (the template has not been run on a real PR) |
| Plugin API version check | Plugins fail loudly on a breaking upgrade | done |
| Async execution, bounded submission | Network-bound targets, larger datasets | done (results still held in memory) |
| Trace drill-down in the report | See what a target actually did | done (static HTML, no JS) |

## v1.0: stable (released as v1.0.0, with one condition not met)
| Item | Status |
|---|---|
| API freeze with a versioning policy (`docs/VERSIONING.md`, `docs/API.md`, snapshot test) | done |
| A licence | done (MIT) |
| Tutorial whose commands are executed by the tests | done |
| Type checking and a coverage floor | done (mypy clean; 95% coverage, floor 93%) |
| Windows support | done (tested in CI on Windows; CPU/memory limits are not enforced there) |
| PyPI publishing | **workflow ready, not published**: needs your PyPI account (`docs/RELEASING.md`) |
| Criterion: an outside researcher has used it and their feedback was addressed | **not met**: no outside user has run it |

## v1.0.4 – v1.0.6: agent evaluation depth (released)
| Item | Status |
|---|---|
| Fuzzy product matching (vendor-prefix-aware NVD normalisation) | done in v1.0.4 |
| Four-model benchmark (deepseek, gpt-4o-mini, haiku, gemini) — dev split only | done in v1.0.4 |
| Multi-turn tool loop (`max_tool_rounds`), session memory (`session_mode`) | done in v1.0.5 |
| Process / Docker sandbox isolation with `env_passthrough` | done in v1.0.5 |
| `cve_tool_call` grader: asserts tool-call correctness from trace | done in v1.0.5 |
| Second worked example: `examples/ticket_triage/` (classification, no tool use) | done in v1.0.6 |
| Interactive JS trace viewer in HTML report | done in v1.0.6 |
| `TraceStep` TypedDict in public API; formalised trace schema | done in v1.0.6 |
| Third example: `examples/support_reply/` (open-ended generation, LLM judge) | done in v1.0.7 |

## v1.0.8: more practical evaluation examples (current)
| Item | Status |
|---|---|
| Add a LangGraph customer-support agent with synthetic cases, deterministic contract checks and LLM judging | done |
| Require an explicit real or local backend for LLM judging | done |
| Expand example datasets and include case-generation scripts | done |

## Later
| Item | Why |
|---|---|
| AI-generated evaluation cases and separate red-team campaigns, with evidence-based remediation guidance | Reduce manual case authoring while keeping ordinary evaluation separate from adversarial testing |
| PyPI publishing | needs maintainer PyPI account (`docs/RELEASING.md` has the workflow) |
| Outside researcher validation | criterion for full v1.0 sign-off; first external user feedback |
| Human calibration labels for CVE graders | close the remaining gap between deterministic graders and human judgment |
| Multi-model benchmark on held-out CVE split | dev-split numbers are not unbiased; held-out run with v1.0.6 fuzzy graders needed |
| Multi-tool or long-horizon agent example | show harness generalises to complex agentic tasks beyond single-tool retrieval |
| Cross-run trace query and comparison | currently each run's report is a standalone HTML file; querying across runs requires manual diffing |

## Not yet validated (applies to every release)
No human calibration labels, external-user validation, or production benchmark are bundled with v1.0.0. The current CVE
plugin has a 100-CVE public-data benchmark, but its deterministic target remains a reference benchmark and security-test
example, not a claim of production vulnerability-management accuracy.
