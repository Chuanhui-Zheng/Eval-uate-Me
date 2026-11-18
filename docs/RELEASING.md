# Releasing

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
(including `anthropic` or a mock) can be substituted.

No LLM benchmark results are included in this release — the LLM judge introduces cost per case and results depend on
the judge model chosen. Run `eval_uate_me run eval.llm.toml` with `OPENROUTER_API_KEY` set to produce results.

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

## v1.0.2 release notes

v1.0.2 adds the retrieval-enabled CVE agent path. The LLM starts with the case text, calls a local `lookup_cve` tool backed
by the frozen NVD/CISA snapshot, and then produces its structured report. This tests tool use and evidence grounding without
placing the complete answer in the initial prompt.

The full-evidence configuration remains as a plumbing control. No live retrieval score is claimed in this release because the
OpenRouter account used for the previous experiment exhausted its credits; a funded run should be recorded in
`examples/cve_triage/RESULTS.md` before quoting a model result.

## v1.0.1 release notes

v1.0.1 is a benchmark-quality patch release after v1.0.0. It expands the CVE example to 100 public CISA KEV vulnerabilities
and 420 grouped cases, adds reproducible snapshot-build documentation, and separates two LLM configurations: a summary-evidence
challenge that withholds CVSS/CWE/references, and a full-evidence plumbing control. The challenge dev run achieved 10/214
(4.7%); the held-out run was interrupted by OpenRouter HTTP 402 credit errors and is not reported as a score.

The release also fixes grader assumptions exposed by the larger public dataset, records the automatic mutation blind spots, and
expands every historical GitHub release description with what shipped, verification, and known limitations. The API remains
version 1; this is a package and benchmark patch release, not a plugin API change.

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
2. Update `docs/ROADMAP.md` and write the release notes: what changed, what was verified, and the known limitations (keep that
   section; it is the project's habit of saying what has *not* been shown).
3. Push to `main` and wait for CI (tests on Linux, Windows and macOS, type check and coverage floor, the example evals, the wheel build
   and the Docker sandbox tests).
4. Tag the commit and publish the GitHub release with the wheel and sdist attached:
   ```bash
   python -m build
   git tag -a vX.Y.Z -m "vX.Y.Z: ..." && git push origin vX.Y.Z
   gh release create vX.Y.Z --verify-tag --title "vX.Y.Z: ..." --notes-file notes.md dist/*
   ```

## Publishing to PyPI (not done yet)
The package has **not** been published to PyPI: that needs your PyPI account, and publishing a name is permanent. The workflow
`.github/workflows/publish.yml` is ready and does nothing until you opt in:

1. Create the project on [PyPI](https://pypi.org) (and first try [TestPyPI](https://test.pypi.org)). Check that the name `eval_uate_me`
   is free; if it is taken, change `name` in `pyproject.toml` (the command stays `eval_uate_me`).
2. In the PyPI project, add a **trusted publisher**: owner `Chuanhui-Zheng`, repository `Eval-uate-Me`, workflow `publish.yml`,
   environment `pypi`. No API token is stored anywhere.
3. In the GitHub repository, create an environment named `pypi` and set the repository variable `PUBLISH_TO_PYPI` to `true`.
4. Publish a GitHub release; the workflow builds, runs `twine check` and uploads.

Until then, install from a clone (`pip install -e .`) or from a release's wheel.
