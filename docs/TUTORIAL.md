# Tutorial: from zero to a trustworthy eval

Every command below is run by `tests/test_tutorial.py`, so this page cannot drift from what the tool does. In the commands,
`RUN` stands for the run directory printed after `results:` (the test substitutes the latest one).

## 1. Install and start a project
```bash
pip install -e .               # from the repository root; the package is not yet published to PyPI
```

```bash tutorial
evalharness init my-eval
cd my-eval
evalharness check eval.toml     # expect: ok: 3 cases
```
`init` wrote a config (`eval.toml`), three sample cases (`cases.jsonl`: `id`, `input`, `expected`, optional `metadata`), a provenance
file (`cases.meta.toml`) and a README. `check` validates all of it without running anything and explains mistakes in plain words.

## 2. Check the data and the graders before trusting a score
```bash tutorial
evalharness lint eval.toml      # expect: lint: 3 cases
evalharness selftest eval.toml  # expect: RESULT: ok
```
`lint` flags problems that make a score meaningless (duplicates, the answer leaking into the input, too few cases for a useful
confidence interval, missing provenance). `selftest` runs three baselines with known answers against your graders: the reference
answer must pass, empty and wrong answers must fail.

## 3. Run it
```bash tutorial
evalharness run eval.toml       # expect: 2/3 passed
```
The sample target just echoes its input, so `known-failure` fails on purpose. Results are in `runs/<name>-<time>/`:
`results.jsonl` (every attempt), `summary.json`, `manifest.json` (what produced them: versions, config and dataset hashes, git
commit) and `report.html` (failures first, with traces).

## 4. Repeat runs, advisory checks, a seed
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
evalharness check eval.toml     # expect: (advisory)
evalharness run eval.toml       # expect: pass@3
```
With repeats the summary reports pass@1, pass@k, pass^k and the cases that flipped between attempts, and the pass rate comes with a
95% confidence interval computed over cases.

## 5. Is a change a real improvement?
```bash tutorial
evalharness run eval.toml       # expect: results:
evalharness history runs        # expect: no significant change
```
`history` groups runs into series (same eval, split and dataset version) and tests the latest against the previous one.
`evalharness compare runs/<a> runs/<b>` does the same for any two runs, with a per-tag table whose p-values are corrected for
looking at many slices. `evalharness power --baseline 0.7 --delta 0.05` tells you how many cases you need to see a given change.

## 6. Block a regression in CI
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
evalharness run eval.toml                       # expect: results:
evalharness baseline promote --config eval.toml # expect: promoted
evalharness gate eval.toml                      # expect: GATE PASSED
```
Commit `eval.baseline.json`; in CI run `evalharness run eval.toml && evalharness gate eval.toml`. A metric the rules name but the run
lacks fails the gate (a typo must not pass), and a different dataset or split is refused rather than compared. After a deliberate
change of the dataset, promote a new baseline.

## 7. Collect human judgements
```bash tutorial
evalharness label export RUN --sample 3 -o sheet.csv   # expect: wrote 3 of 9 attempts
```
The run has 9 attempts (3 cases x 3 repeats); `--sample 3` asks reviewers to label just 3 of them. Give `sheet.csv` to reviewers (blind: automatic verdicts hidden). They fill `human_pass` with yes/no. Then:
`evalharness label import RUN sheet.csv --labeler ana`, `evalharness calibrate RUN --grader overall` (agreement, kappa, confidence
intervals) and `evalharness label disagreements RUN` (where humans and graders differ).

## 8. Sensitive data
Add this to the config to keep only scores, never inputs or outputs, and to refuse anything that sends data off the machine:
```toml
[privacy]
store = "scores_only"
local_only = true
```
Run unknown code in a sandbox with `[run] isolation = "docker"` (see the [reference](REFERENCE.md) for what each isolation level does and does not give you).

## 9. Your own system
```bash tutorial
evalharness init-plugin my_agent --dir .     # expect: created 6 files
```
This writes an installable package with a target and a grader stub, an eval config, a provenance file and tests. Edit `run()` to call your system,
`pip install -e evalharness-my-agent`, and `evalharness run evalharness-my-agent/eval.toml`. The plugin API is in `docs/API.md`.

## 10. Does your evaluation catch bad systems?
List deliberately broken variants of your target under `[[mutants]]` and run `evalharness meta-eval eval.toml`: a mutant the
evaluation cannot tell from the real thing is a blind spot. You do not have to guess the defects: `evalharness meta-eval eval.toml --auto`
damages every field of the real outputs in turn and names the fields nothing checks. `examples/cve_triage` is a complete, worked example.
