# Design notes

## Goal
A small harness where the thing under test is a *replaceable plugin*, not the harness itself.
Core knows nothing about any domain; domain logic lives in plugin packages.

## Shape
```
cases.jsonl ─► Runner ─► ExecPolicy ─► Target (plugin) ─► TargetOutput ─► Graders (plugins) ─► results/summary/report
                          retries · rate limit · cache
```
- **Case / TargetOutput / Score** are plain dataclasses with JSON-able payloads. Input, expected and
  output are opaque to the core.
- **Target** (`run(case) -> TargetOutput`) and **Grader** (`grade(case, out) -> Score`) are the only two
  extension points a plugin must know; **Judge** is a third, used by the `llm_judge` grader.
- Plugins register by name via decorators; they are found through config (`plugins = [...]`) or Python
  entry points (`evalharness.targets|graders|judges`).

## Decisions and trade-offs
| Decision | Why | Cost |
|---|---|---|
| Zero runtime dependencies | Easy to install anywhere; nothing to audit | HTTP judge uses `urllib`; no async |
| Threads, not asyncio | Targets may be blocking subprocess/SDK calls; simple mental model | Not ideal for thousands of concurrent network calls |
| `command` target (JSON over stdin/stdout) | Evaluate agents in any language without writing Python | Process-start overhead per case |
| A failing target/grader fails one case, never the run | One bad case must not hide the other 99 | Needs `failure_reasons` to avoid silently swallowing real bugs |
| Pass-rate CI by bootstrapping *cases* | Repeated attempts of a case are correlated; treating them as independent overstates confidence | Wide CIs on small datasets (which is the honest answer) |
| Paired bootstrap in `compare` | Same cases in both runs, so pair them; says whether a delta is distinguishable from noise | Needs enough shared cases |
| Cache keyed by target spec + input + attempt, errors never cached | Re-grading is free; repeats stay distinct samples | Stale if the target's behaviour changes without its config changing (e.g. an unpinned remote model) |
| Manifest with dataset and config hashes | A result is only meaningful if you know what produced it | Does not capture remote model drift |

| Baseline targets (oracle, null, shuffled) and `selftest` | Evaluate the evaluator: prove each grader accepts a correct answer and rejects wrong ones before trusting any score | Only catches gross errors; says nothing about subtle bias |
| Dataset `lint` as a separate command | Leakage, duplicates and tiny datasets silently distort scores; cheap to detect up front | Heuristics (e.g. verbatim-answer leakage), so findings are warnings, not errors |

| Append each result as it finishes; rewrite atomically at the end | An interrupted multi-hour run keeps its work; final files are always complete and in job order | Brief duplication on resume (later line wins) until the final rewrite |
| Resume refuses a changed config/dataset | Mixing results from two different evals produces a number that means nothing | Raising the budget must use `--max-cost`, not a config edit |
| Budget stops *new* jobs, marks the run incomplete, exits 3 | A truncated pass rate must not be mistaken for a full one | Overshoots by up to `concurrency - 1` in-flight jobs |

| Redact each result at the moment it is produced | Console, files and reports are all downstream of one choke point, so none can leak | The target and graders still process real data; ids and tags are kept |
| `local_only` checks declared `network` flags, and Docker `--network none` is the hard guarantee | A harness cannot see what arbitrary plugin code does | Declarations can be wrong; opaque components (`command`) only produce a warning |
| Errors counted as failures, plus a separate answered-only rate | Conservative headline, but outages stay visible as outages | Two numbers to explain |
| Required vs advisory graders instead of weights | Simple to reason about; weights invite arbitrary tuning | No partial credit across graders |
| Config errors collected and worded for non-programmers, with did-you-mean | Researchers who cannot read a traceback must still fix their own config | Plugin-specific option checks run in a second stage (after plugins load) |

| Labels in an append-only `labels.jsonl` beside the results, not in the dataset | A label judges one output of one run; mixing it into the dataset would apply it to future, different outputs | Labels do not carry over to a new run, even for identical outputs |
| Hash of the labelled output stored with each label | Stale labels are detected instead of silently mis-applied | A harmless re-run that changes whitespace invalidates labels |
| Blind sheets by default | Showing the automatic verdict anchors reviewers and inflates agreement | Reviewers cannot see which cases the grader found hard |
| Whole-sheet validation before import | A half-imported sheet is hard to notice and harder to undo | One typo blocks the import until fixed |

| Dataset provenance as a `.meta.toml` beside the data, checked by `lint` | The facts a later reader needs (source, date, licence, personal data) live with the file and travel into every run's manifest | Records claims; cannot verify them or judge licence compatibility |
| Split by hash of the case id (explicit `metadata.split` wins) | Reproducible, and adding cases never moves existing ones, so a held-out set stays held out | Not stratified: small datasets can be unbalanced |
| Default to dev when splits exist; count and warn on held-out looks | Makes the disciplined path the easy one and the undisciplined one visible | Only an honesty aid: the log can be deleted and a dataset edit resets it |

| Holm adjustment across tags in `compare`; permutation test for the overall delta | Slice-by-slice comparison otherwise produces false positives; the sign-flip test needs no distributional assumption | Holm is conservative when slices overlap (cases carry several tags) |
| `power` uses a normal approximation | Fast planning estimate with no dependencies | Rough for very small n or rates near 0 or 1 |
| A judge panel with a vote; a tie fails | Different judges have different biases; failing ties keeps the grader conservative | N times the cost; one broken judge errors the case |
| Pairwise in both orders, flips become ties | Position bias is the best-known pairwise failure and cheap to expose | Doubles the calls (`--single-order` halves it) |
| `judge-check` builds probes from your own references | Tests the judge on your rubric and domain, not a generic benchmark | Covers only these biases, on a small sample; says nothing about subtler ones |
| Carry labels only on an identical output hash | A label is a judgement of specific text; reuse must not stretch it to different text | Any change, even whitespace, means relabelling |

| `meta-eval`: mutation testing for evaluations | A high score on the real system proves little unless the evaluation would fail a broken one; surviving mutants are concrete blind spots | Mutants are hand-written, crude defects; catching them says nothing about subtler ones |
| `[selftest.oracle]` and `selftest = "guardrail"` | For structured tasks the reference is a spec, not an output; pure "must not contain" graders pass empty output legitimately | A real target as oracle is circular: it checks the graders accept a correct answer, nothing about the target |
| `${CONFIG_DIR}` in plugin options | A config must work from any directory | A new bit of config syntax to learn |

| Three isolation levels (none / process / docker) | Most targets are trusted and need no overhead; a hang needs a hard kill; untrusted code needs a real sandbox | Process isolation is not a security boundary and says so; docker costs about a second per attempt |
| A fresh worker per attempt | A crash, leak or hang cannot affect the next case; the environment is scrubbed every time | Start-up cost, and the target is rebuilt each time |
| Plugin API as one integer, checked at registration | A breaking change fails loudly with both versions named instead of misbehaving | Coarse: no per-feature negotiation |
| An async executor beside the thread pool | Network-bound targets need hundreds of calls in flight; the coroutine can really be cancelled | Two code paths to keep in step |
| `history` series keyed on name + split + dataset | A score on different data is not a point on the same line | A renamed eval starts a new series |

## Known limitations / next steps
- Judge calibration needs human labels; the harness measures agreement but does not collect labels.
- `selftest` has only been run on the toy examples; no real task has been validated with it yet.
- The labelling workflow is tested end to end on synthetic runs only; no real reviewers have used it.
- The cve_triage example is a deterministic reference agent over a frozen public NVD/CISA snapshot. Its fact-extraction score is still a reference baseline, not evidence that an LLM agent is production-ready; the example demonstrates selftests, mutation testing, provenance and injection checks.
- Process isolation is not a security sandbox. Docker isolation is; it needs a local Docker and the image. Memory limits are not enforced on macOS. An async target interrupted with Ctrl-C may log an asyncio "Task exception was never retrieved" line.
- Results are held in memory for the summary, so datasets of hundreds of thousands of attempts are not yet supported. The pull-request workflow in `docs/ci/` is a template that has not been run on a real PR.
- `judge-check`, `pairwise` and judge panels are tested with deterministic mock judges and deliberately biased test judges; the `anthropic` backend has still never been run against the live API, so how real models score on these probes is unknown.
- Dataset metadata and splits are tested on the frozen public CVE snapshot; no human calibration labels exist yet.
- Labels are not reused across runs (even when an output is identical), and there is no web UI: reviewers work in a CSV.
- No timeout for in-process Python targets (threads cannot be killed); use the `command` target for hard timeouts.
- The budget only sees cost the target reports: judge calls are not counted, and usage from failed retry attempts is lost.
- No licence file has been chosen yet; until one is added, others have no explicit permission to reuse the code.
- Not published to PyPI (the wheel builds and installs, publishing is a manual decision).
- On Ctrl-C, jobs already running (or queued on a free worker) may still finish and be saved; the interrupted job is not.
- Judge prompts defend against injection by delimiting and instruction, which reduces but does not eliminate risk.
- Per-case secrets/PII handling is the plugin's responsibility; the harness only redacts secret-looking option names in manifests.
