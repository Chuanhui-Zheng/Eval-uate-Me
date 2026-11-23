# Releasing

## v1.0.9 release notes

v1.0.9 adds AI-assisted evaluation discovery and red-team campaigns to the CLI. `online_case` generates and runs separate
capability and adversarial suites from an agent profile, writes separate reports, and produces an advisory remediation prompt
grounded in observed red-team failures. `offline_case` runs a prepared dataset. The older `run` and `discover` command names
remain as aliases for compatibility.

The release also updates the customer-support Agent source layout, removes generated evaluation artifacts and old example
projects from this repository, and keeps the upstream Agent as a separate checkout. Generated test cases are candidates and
need review before promotion to a trusted benchmark. Model calls can incur provider costs. The example Agent uses mock
customer activity data; this release does not demonstrate production-grade security or customer-support accuracy.
The coverage gate excludes the new `discovery.py` orchestration module until its model-generation paths have dedicated
automated tests. The tests in this release do not make live hosted-model calls.

## v1.0.8 release notes

v1.0.8 adds a LangGraph customer-support agent evaluation example and makes LLM judging explicit.

**`examples/customer_triage_eval/` — evaluate an existing LangGraph agent.** The example bundles a public customer-support
agent, an adapter that returns its classification, draft reply, confidence and graph trace, 100 synthetic test cases, a
deterministic support-contract grader and an LLM judge for correctness, helpfulness and safety. The README includes setup,
run commands and an observed run with its limitations: two runtime errors, synthetic paraphrase cases and an uncalibrated
LLM judge.

**No implicit mock LLM judge.** The runtime no longer registers the deterministic mock backend. `llm_judge` and `pairwise`
require a configured real or local backend, while scripted deterministic judges are confined to the test suite. This avoids
mistaking test behavior for a meaningful evaluation score.

**Expanded example data and instructions.** The echo, plugin, ticket-triage and support-reply datasets and README files now
include reproducible case-generation scripts and broader examples. Tutorial and reference docs clarify when to use
deterministic graders versus semantic LLM judging.

**Recorded evaluation artifacts.** Each worked example includes a checked-in HTML report and machine-readable summary for
its latest run, so the documented results are available from the release source rather than only from a local ignored
`runs/` directory.

LLM calls may incur provider charges. The added support dataset is synthetic and does not establish real-world customer
support accuracy.

## v1.0.7 release notes

v1.0.7 adds the third worked example, completing the trilogy of evaluation paradigms the harness supports.

**`examples/support_reply/` — open-ended generation with LLM judge.** The agent reads a support ticket and drafts a
customer-facing reply. Because many replies are acceptable, there is no single correct answer — quality is assessed by
the built-in `llm_judge` grader on three rubric dimensions: `addresses_issue`, `actionable`, `appropriate_tone`. This
is the third evaluation paradigm alongside factual lookup (CVE triage) and classification (ticket triage).

The example includes 30 cases with structured rubrics (`must_cover`, `must_not`), background context in
`metadata.context`, a template-based oracle for selftest and meta-eval, four deliberate flaws (`dismissive`,
`wrong_tone`, `empty`, `no_action`) for mutation testing, and an LLM target (`eval.llm.toml`) for benchmarking real
models. The judge is configured to use `openai/gpt-4o-mini` via OpenRouter; any judge supported by the harness
(including `anthropic` or another configured judge backend) can be substituted.

No LLM benchmark results are included in this release — the LLM judge introduces cost per case and results depend on
the judge model chosen. Run `eval_uate_me offline_case eval.llm.toml` with `OPENROUTER_API_KEY` set to produce results.

## v1.0.6 release notes

v1.0.6 is a framework-maturity release that addresses gaps identified against mature eval frameworks (Inspect AI). It adds a
formal trace schema, expands the second worked example to production quality, and ships an interactive trace viewer.

**TraceStep public type.** `TraceStep` (a `TypedDict`) is now exported from the top-level `eval_uate_me` package. It documents
the recommended shape for `TargetOutput.trace` entries: `tool` (required), `round`, `model`, `found`. Plugins may add extra
keys; graders should ignore keys they do not recognise.

**ticket_triage expanded to 50 cases and 3 graders.** The example now covers all five categories and three urgency levels with
50 labelled cases, a `ticket_schema` grader that validates output format, and an LLM target (`ticket_triage_llm` via
`eval.llm.toml`) for benchmarking real models. A deterministic reference agent provides the oracle baseline. The example
demonstrates the harness on a pure-classification task with no tool use.

**Interactive JS trace drill-down in HTML report.** Each step row in the trace table is now clickable to expand or collapse its
full detail JSON. The report remains self-contained (one inline `<script>` block; no external dependencies).

**`.gitignore` updated.** Added `*.pdf` rule; a local PDF file had been accidentally left untracked in the repository root.

Multi-model benchmark numbers are from the CVE triage **dev split** (25 cases each, v1.0.5 run). Full held-out multi-model
results are deferred pending a clean run against the held-out split with the v1.0.6 fuzzy graders.

## v1.0.5 release notes

v1.0.5 generalises the retrieval loop to multi-turn, adds session memory, process/Docker sandbox isolation, an eleventh CVE
grader, and a second worked example.

**Multi-turn tool loop.** `_run_retrieval` now loops up to `max_tool_rounds` times (default 5), appending each round's tool
results to the message history before making the final constrained-schema call. Trace entries include a `round` field.

**Session memory.** `session_mode=True` on `LLMAgent` accumulates messages across `run()` calls; `reset_session()` clears state.

**Process / Docker sandbox isolation.** `eval.llm.toml` uses `isolation = "process"` with `env_passthrough = ["OPENROUTER_API_KEY"]`.
`eval.llm.docker.toml` adds `isolation = "docker"` with no-network, read-only FS, CPU 120 s, memory 512 MB.

**`cve_tool_call` grader.** Reads `out.trace` to assert the agent called `lookup_cve` with the correct CVE ID; passes silently
for non-LLM targets.

Multi-model benchmark (dev split, 11 graders): deepseek-v4.1-flash 96.7%, gpt-4o-mini 91.6%, claude-haiku-5.5 91.6%,
gemini-2.5-flash 85.9% (Gemini rate-limited on 17 cases; v1.0.4 baseline 92.5% is a better capability estimate).

## v1.0.4 release notes

v1.0.4 introduces fuzzy product matching and a four-model benchmark.

**Fuzzy product matching.** NVD stores products as `"<Vendor> <ProductName>"` (e.g. `"Drupal Drupal Core"`); LLMs typically
drop the vendor prefix. The new `_product_match()` function handles exact, vendor-dropped, word-aligned-substring, and
vendor-added forms. Raised gpt-4o-mini pass rate from 69.2% → 92.1% on the dev split.

**Four-model benchmark.** Ran deepseek-v4.1-flash-1017, gpt-4o-mini, claude-haiku-5.5, and gemini-2.5-flash against the CVE
dev split (10 graders, 214 cases). gpt-6-luna excluded: 429 rate-limit errors on 199/214 cases.

Known limitation: all benchmark numbers are dev-split only; held-out split has not yet been run with these models.

## v1.0.3 release notes

v1.0.3 fixes the retrieval benchmark's JSON Schema to constrain `report_version` to the exact contract value `"1"`, then
records a complete OpenRouter retrieval run. The agent passed 148/214 dev cases (69.2%) and 137/206 held-out cases (66.5%),
with zero target errors. The combined exact-contract pass rate was 285/420 (67.9%). The held-out split was viewed three times
during tuning, so it is a post-tuning measurement rather than a pristine first-look benchmark.

The main remaining failure slice is strict canonical affected-product matching. CVSS, CWE, references, injection resistance,
and safety graders passed 100% on both splits. No claim of production vulnerability-management accuracy is made.

## v1.0.2 — RAG evaluation faithfulness fix

v1.0.2 fixes misleadingly low faithfulness scores when an evaluated RAG agent returns claim-level citations. The agent adapter
must pass the evidence the judge needs, rather than only the final answer text.

**Root cause.** The evaluated genetic-evidence diabetes QA system returned `claims` with citations, but the adapter omitted
those fields from the object sent to the judge. Without the claims and their source chunks, the judge could not verify whether
the answer was grounded and assigned low faithfulness scores even when citations were present in the agent response.

**Fix.** Return `claims` and `citations` from the target adapter and make the rubric check the claim-level citation fields.
The RAG system itself did not change; the evaluation now receives the evidence needed to judge it.

**Observed 144-question evaluation.** The pass rate increased from 35.4% to 83.3%; faithfulness increased from 0.43 to
0.95, answer relevance changed from 0.90 to 0.86, and refusal correctness increased from 0.61 to 0.84. These are results
from that specific run and judge configuration, not a general guarantee of RAG quality.

The release also adds a retrieval-enabled CVE agent configuration: the LLM receives the case text, calls a local
`lookup_cve` tool backed by the frozen NVD/CISA snapshot, and produces a structured report. A full-evidence configuration
remains as a plumbing control. Do not treat that control as an independent retrieval score.

## v1.0.1 — HTML reports and release workflow

v1.0.1 is a patch release that improves the HTML reporting and project distribution workflow while keeping the public plugin
API at version 1.

**Package and command rename.** The Python import package and CLI changed from `evalharness` to `eval_uate_me`, and the
distribution name became `eval-uate-me`. Project metadata, examples, Docker entry point, CI and documentation were updated
to use the new names.

**HTML reports and scaffolding.** The release adds a self-contained HTML report with clearer summary metrics and per-case
details. `eval_uate_me init` also provides an `llm_judge` configuration scaffold so users can configure a real judge backend
instead of relying on an implicit mock.

**Publishing workflows.** CI publishing switched to token-based authentication, the workflow gained more useful Twine output,
and a Hugging Face Hub synchronization workflow was added.

**CVE benchmark snapshot.** The tagged example contains a reproducible offline snapshot of 100 public CISA KEV records and
420 grouped cases: 100 factual cases, 300 prompt-injection variants, and 20 unknown identifiers. The cases are split by CVE
group into 214 development and 206 held-out cases. The LLM setup separates a summary-evidence challenge from a full-evidence
plumbing control. The challenge development run passed 10/214 cases (4.7%); the held-out run stopped after OpenRouter returned
HTTP 402, so no held-out challenge score is reported. These results are diagnostics for the recorded configuration, not a
production security-accuracy claim.

This release does not change the plugin API contract.

## v1.0.0 release notes

v1.0.0 is the stable CVE-focused release. It includes `examples/cve_triage`, a public-data CVE triage example built from a
frozen NVD 2.0 and CISA KEV snapshot. The release snapshot contained 32 reproducible factual and adversarial cases, 10
deterministic graders, six deliberate mutants, and an OpenRouter-compatible live LLM target. The core eval_uate_me plugin API
remains version 1.
The deterministic baseline does not require an API key; the live LLM demonstration requires `OPENROUTER_API_KEY`. A later
post-release dataset refresh expands the working example to 100 CVEs and 420 grouped cases; it must be measured separately
before its live score is used in release material. The current challenge configuration withholds answer-bearing fields from the
LLM; the full-evidence configuration is a plumbing control only.

Known limitation: the reference target reads the same frozen records used to create the expected answers, so its perfect score
demonstrates evaluator coverage rather than production CVE triage quality. The recorded live demonstration used 32 derived cases
from six underlying CVEs and achieved 29/32 (91%); all observed failures were prompt-injection cases.

## Every release
1. Update the version in **both** `pyproject.toml` and `src/eval_uate_me/__init__.py` (a test fails if they differ).
2. Update the README and relevant documentation, then write release notes covering what changed, what was verified, and known
   limitations (keep that section; it is important to state what has *not* been shown).
3. Push to `main` and wait for CI (tests on Linux, Windows and macOS, type check and coverage floor, the example evals, the wheel build
   and the Docker sandbox tests).
4. Tag the commit and publish the GitHub release with the wheel and sdist attached:
   ```bash
   python -m build
   git tag -a vX.Y.Z -m "vX.Y.Z: ..." && git push origin vX.Y.Z
   gh release create vX.Y.Z --verify-tag --title "vX.Y.Z: ..." --notes-file notes.md dist/*
   ```

## Publishing to PyPI
The project name `eval_uate_me` is already registered on PyPI. Publishing a version is permanent. The workflow
`.github/workflows/publish.yml` runs after a GitHub release only when the `PUBLISH_TO_PYPI` repository variable is `true`:

1. Configure the PyPI API token as the GitHub Actions secret `PYPI_API_TOKEN`.
2. Set the repository variable `PUBLISH_TO_PYPI` to `true`.
3. Publish a GitHub release. The workflow builds, runs `twine check`, and uploads the wheel and source distribution.

For a one-off local upload, build with `python -m build`, verify with `twine check dist/*`, and upload with `twine upload dist/*`.
