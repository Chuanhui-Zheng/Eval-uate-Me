# Plugin API (version 1)

Everything a plugin author needs. The stable surface is defined in [VERSIONING.md](VERSIONING.md).

```python
from evalharness import (Case, TargetOutput, Score, Target, Grader, Judge,
                         register_target, register_grader, register_judge, API_VERSION)
```

## Running evals from Python
```python
from evalharness import evaluate, run_eval

result = evaluate(my_function, cases=[{"input": "2+2", "expected": "4"}, ("3+3", "6")],
                  graders=["exact_match", lambda case, out: len(out.output) < 50])
result.pass_rate; result.failures(); result.to_rows()      # EvalResult; to_rows() is flat, ready for a DataFrame

result = run_eval("eval.toml")                              # exactly what `evalharness run` does; result.run_dir is the run
```
`evaluate` works in memory (nothing is written). The target may be a function (sync or async), a `Target`, or `"module:function"`;
cases may be `Case` objects, dicts or `(input, expected)` tuples; graders may be `Grader` objects, registered names, `(name, options)`
tuples or `function(case, output) -> bool`. These three names are part of the stable API.

## Data
- `Case(id, input, expected=None, metadata={})`: one test case. `input`, `expected` and `metadata` are any JSON values; the core never
  looks inside. `metadata.tags` / `category` drive per-slice results, `metadata.split` the dev/held-out split, `metadata.human_pass` a
  legacy human label.
- `TargetOutput(output=None, trace=[], error=None, latency_s=0.0, usage={}, retries=0, cached=False)`: what a target returns. Put tool
  calls in `trace` as dicts (`{"tool": "search", ...}`) so `tool_use` / `max_steps` and the report's step table work; put
  `{"input_tokens", "output_tokens", "cost_usd"}` in `usage` for cost accounting and `--max-cost`. Set `error` to report a failure
  without raising.
- `Score(grader, value, passed, reason="", role="required")`: one grader's verdict. `value` is 0 to 1.

## A target
You often need no class at all: `[target] type = "http"` (POST to a URL) or `type = "python"` with `callable = "pkg.mod:fn"`
covers an HTTP service or a function (see the README). Write a class when you need options, state, or tracing:
```python
@register_target("my_agent")
class MyAgent(Target):
    evalharness_api = 1          # the plugin API version this was written for
    network = False              # True: sends case data off the machine (privacy.local_only refuses it); None: unknown

    def __init__(self, model: str, snapshot: str): ...       # options come from the [target] table

    def run(self, case: Case) -> TargetOutput: ...
    # or, for network-bound targets, instead of run():
    async def arun(self, case: Case) -> TargetOutput: ...    # the harness keeps run.concurrency calls in flight
```

## A grader
```python
@register_grader("my_grader")
class MyGrader(Grader):
    evalharness_api = 1
    name = "my_grader"
    semantic = True              # False: checks behaviour (latency, steps...), skipped by selftest
    selftest = None              # "guardrail": only the oracle is checked by selftest (see the README)
    network = False

    def grade(self, case: Case, out: TargetOutput) -> Score: ...
```
A grader that raises fails only that case. `role = "advisory"` in the config makes it report-only.

## A judge backend
`Judge.complete(prompt: str) -> str` returns the model's text. Register with `@register_judge("name")`; set `network` honestly.

## Loading
Either list the module in the config (`plugins = ["my_pkg.plugin"]`) or declare entry points in your package's `pyproject.toml`
(`evalharness.targets`, `evalharness.graders`, `evalharness.judges`); `evalharness init-plugin NAME` generates a working package.
`${CONFIG_DIR}` in any string option expands to the config file's folder.

## Compatibility
A plugin that declares `evalharness_api` different from `API_VERSION` is refused with both numbers named. Undeclared plugins work but
are flagged by `evalharness list` and `check`.
