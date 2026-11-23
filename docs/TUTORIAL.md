# Tutorial: from zero to a trustworthy eval

Every command below is run by `tests/test_tutorial.py`, so this page cannot drift from what the tool does. In the commands,
`RUN` stands for the run directory printed after `results:` (the test substitutes the latest one).

## 1. Install and start a project
```bash
pip install -e .               # from the repository root; the package is not yet published to PyPI
```

```bash tutorial
eval_uate_me init my-eval
cd my-eval
eval_uate_me check eval.toml     # expect: ok: 3 cases
```
`init` wrote a config (`eval.toml`), three sample cases (`cases.jsonl`: `id`, `input`, `expected`, optional `metadata`), a provenance
file (`cases.meta.toml`) and a README. `check` validates all of it without running anything and explains mistakes in plain words.

## 2. Check the data and the graders before trusting a score
```bash tutorial
eval_uate_me lint eval.toml      # expect: lint: 3 cases
eval_uate_me selftest eval.toml  # expect: RESULT: ok
```
`lint` flags problems that make a score meaningless (duplicates, the answer leaking into the input, too few cases for a useful
confidence interval, missing provenance). `selftest` runs three baselines with known answers against your graders: the reference
answer must pass, empty and wrong answers must fail.

## 3. Run it
```bash tutorial
eval_uate_me run eval.toml       # expect: 2/3 passed
```
The sample target just echoes its input, so `known-failure` fails on purpose. Results are in `runs/<name>-<time>/`:
`results.jsonl` (every attempt), `summary.json`, `manifest.json` (what produced them: versions, config and dataset hashes, git
commit) and `report.html` (failures first, with traces).

## 4. Choose deterministic graders or an LLM judge

The framework does not guess whether a task has one correct answer. Define the task contract first:

- Use a deterministic grader for machine-checkable constraints: schema, fields, labels, IDs, regexes, tool names,
  tool arguments, maximum steps, latency and cost.
- Use `llm_judge` only for semantic qualities with multiple acceptable answers: helpfulness, tone, clarity, faithfulness
  or overall quality.
- In most real evaluations, combine both: rules enforce hard requirements and an LLM judge evaluates the remaining soft dimensions.

An `llm_judge` must name a real or local backend; there is no production `mock` judge. For an OpenAI-compatible provider:

```toml
[[graders]]
type = "llm_judge"
name = "reply_quality"
dimensions = ["correctness", "helpfulness", "safety"]
rubric = "Score each dimension from 1 to 5 and explain the decision."

[graders.judge]
type = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"
```

Set the secret outside the file; the command does not prompt interactively:

```bash
export OPENAI_API_KEY="..."
eval_uate_me check eval.toml
eval_uate_me run eval.toml
```

Gemini can use the same backend by changing the endpoint, model and environment variable:

```toml
[graders.judge]
type = "openai_compat"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
model = "gemini-2.5-flash"
api_key_env = "GEMINI_API_KEY"
```

```bash
export GEMINI_API_KEY="..."
eval_uate_me run eval.toml
```

Run `judge-check` before trusting a live judge; it probes repeatability, length bias, prompt-injection sensitivity and
position bias. `selftest` remains useful for deterministic graders.

## 5. Repeat runs, advisory checks, a seed
A non-deterministic system needs repeated runs; a minor check should not decide pass/fail. Edit the config:

```toml file=eval.toml
name = "my-eval"
dataset = "cases.jsonl"

[target]
type = "echo"

[[graders]]
type = "exact_match"

[[graders]]
type = "max_latency"
seconds = 5
role = "advisory"      # reported, but does not decide pass/fail

[run]
repeats = 3
seed = 1
```

```bash tutorial
eval_uate_me check eval.toml     # expect: (advisory)
eval_uate_me run eval.toml       # expect: pass@3
```
With repeats the summary reports pass@1, pass@k, pass^k and the cases that flipped between attempts, and the pass rate comes with a
95% confidence interval computed over cases.

## 6. Is a change a real improvement?
```bash tutorial
eval_uate_me run eval.toml       # expect: results:
eval_uate_me history runs        # expect: no significant change
```
`history` groups runs into series (same eval, split and dataset version) and tests the latest against the previous one.
`eval_uate_me compare runs/<a> runs/<b>` does the same for any two runs, with a per-tag table whose p-values are corrected for
looking at many slices. `eval_uate_me power --baseline 0.7 --delta 0.05` tells you how many cases you need to see a given change.

## 7. Block a regression in CI
Remember a good run as the baseline and add rules to the config; later `gate` fails (exit 1) when a run is worse:

```toml file=eval.toml
name = "my-eval"
dataset = "cases.jsonl"

[target]
type = "echo"

[[graders]]
type = "exact_match"

[[graders]]
type = "max_latency"
seconds = 5
role = "advisory"

[run]
repeats = 3
seed = 1

[gate]
significant_only = true
[gate.min]
pass_rate = 0.5
[gate.max_drop]
pass_rate = 0.1
```

```bash tutorial
eval_uate_me run eval.toml                       # expect: results:
eval_uate_me baseline promote --config eval.toml # expect: promoted
eval_uate_me gate eval.toml                      # expect: GATE PASSED
```
Commit `eval.baseline.json`; in CI run `eval_uate_me run eval.toml && eval_uate_me gate eval.toml`. A metric the rules name but the run
lacks fails the gate (a typo must not pass), and a different dataset or split is refused rather than compared. After a deliberate
change of the dataset, promote a new baseline.

## 8. Collect human judgements
```bash tutorial
eval_uate_me label export RUN --sample 3 -o sheet.csv   # expect: wrote 3 of 9 attempts
```
The run has 9 attempts (3 cases x 3 repeats); `--sample 3` asks reviewers to label just 3 of them. Give `sheet.csv` to reviewers (blind: automatic verdicts hidden). They fill `human_pass` with yes/no. Then:
`eval_uate_me label import RUN sheet.csv --labeler ana`, `eval_uate_me calibrate RUN --grader overall` (agreement, kappa, confidence
intervals) and `eval_uate_me label disagreements RUN` (where humans and graders differ).

## 9. Sensitive data
Add this to the config to keep only scores, never inputs or outputs, and to refuse anything that sends data off the machine:
```toml
[privacy]
store = "scores_only"
local_only = true
```
Run unknown code in a sandbox with `[run] isolation = "docker"` (see the [reference](REFERENCE.md) for what each isolation level does and does not give you).

## 10. Your own system
```bash tutorial
eval_uate_me init-plugin my_agent --dir .     # expect: created 6 files
```
This writes an installable package with a target and a grader stub, an eval config, a provenance file and tests. Edit `run()` to call your system,
`pip install -e eval_uate_me-my-agent`, and `eval_uate_me run eval_uate_me-my-agent/eval.toml`. The plugin API is in `docs/API.md`.

## 11. Does your evaluation catch bad systems?
List deliberately broken variants of your target under `[[mutants]]` and run `eval_uate_me meta-eval eval.toml`: a mutant the
evaluation cannot tell from the real thing is a blind spot. You do not have to guess the defects: `eval_uate_me meta-eval eval.toml --auto`
damages every field of the real outputs in turn and names the fields nothing checks. `examples/cve_triage` is a complete, worked example.
