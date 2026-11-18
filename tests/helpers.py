"""Shared test helpers: config writers, registered test targets and graders, fixtures-as-functions.
Test files do `from helpers import *`; __all__ lists every top-level name (including underscore ones)."""
import json

import sys

from pathlib import Path

import pytest

from eval_uate_me import (Case, Grader, Score, Target, TargetOutput, register_grader, register_judge,
                         register_target)

from eval_uate_me.cli import main

from eval_uate_me.config import load_cases, load_config

from eval_uate_me.graders import Contains, ExactMatch, Regex

from eval_uate_me.runner import run

COPY_STDIN = "import sys; sys.stdout.write(sys.stdin.read())"

def write_eval(tmp_path: Path, cases, target='type = "echo"', graders='[[graders]]\ntype = "exact_match"'):
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(c) for c in cases))
    (tmp_path / "e.toml").write_text(f'name="t"\ndataset="c.jsonl"\n[target]\n{target}\n{graders}\n[run]\noutput_dir="runs"\n')
    return tmp_path / "e.toml"

def _selftest_cfg(tmp_path, graders, cases=None):
    cases = cases or [{"id": str(i), "input": f"q{i}", "expected": f"answer-{i}"} for i in range(6)]
    return write_eval(tmp_path, cases, graders=graders)

def _counting_target(name, calls, boom_on=None):
    @register_target(name)
    class T(Target):
        def run(self, case):
            calls.append(case.id)
            if boom_on and len(calls) == boom_on:
                raise KeyboardInterrupt
            return TargetOutput(output=case.input)
    return T

def _costly_target(name, calls, cost=1.0):
    @register_target(name)
    class T(Target):
        def run(self, case):
            calls.append(case.id)
            return TargetOutput(output=case.input, usage={"cost_usd": cost} if cost else {})
    return T

def _budget_cfg(tmp_path, target, extra):
    cases = [{"id": str(i), "input": str(i), "expected": str(i)} for i in range(5)]
    f = write_eval(tmp_path, cases, target=f'type = "{target}"')
    f.write_text(f.read_text() + "concurrency = 1\n" + extra)
    return f

def _mixed_run(tmp_path):
    @register_target("one_outage")
    class OneOutage(Target):
        def run(self, case):
            return TargetOutput(error="down") if case.id == "c" else TargetOutput(output=case.input)

    cases = [{"id": "a", "input": "x", "expected": "x"}, {"id": "b", "input": "x", "expected": "y"},
             {"id": "c", "input": "x", "expected": "x"}]
    return write_eval(tmp_path, cases, target='type = "one_outage"')

def _write_cfg(tmp_path, body, dataset=True):
    if dataset:
        (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    f = tmp_path / "e.toml"
    f.write_text(body)
    return f

GOOD = 'dataset = "c.jsonl"\n[target]\ntype = "echo"\n[[graders]]\ntype = "exact_match"\n'

SECRET = "SECRET-chr7:117559590-G>A"

def _leaky_target():
    @register_target("leaky")
    class Leaky(Target):
        network = False

        def run(self, case):
            if case.id == "err":
                return TargetOutput(error=f"parse failed on {case.input}")
            if case.id == "boom":
                raise RuntimeError(f"crash with {case.input}")
            return TargetOutput(output=f"report for {case.input}", trace=[{"tool": "lookup", "arg": case.input}],
                                usage={"cost_usd": 0.01})
    return Leaky

def _privacy_cfg(tmp_path, privacy="store = \"scores_only\"", extra_run=""):
    cases = [
        {"id": "ok", "input": SECRET, "expected": f"report for {SECRET}", "metadata": {"tags": ["t1"], "note": SECRET}},
        {"id": "wrong", "input": SECRET, "expected": f"{SECRET} different", "metadata": {"tags": ["t1"]}},
        {"id": "err", "input": SECRET, "expected": "x"},
        {"id": "boom", "input": SECRET, "expected": "x"},
    ]
    f = write_eval(tmp_path, cases, target='type = "leaky"')
    f.write_text(f.read_text() + extra_run + f"[privacy]\n{privacy}\n")
    return f

def _labelled_run(tmp_path, n=6, privacy=""):
    """A run where case i echoes its input; odd cases fail (expected differs)."""
    cases = [{"id": f"c{i}", "input": f"问题 {i}", "expected": f"问题 {i}" if i % 2 == 0 else "other"} for i in range(n)]
    f = write_eval(tmp_path, cases)
    if privacy:
        f.write_text(f.read_text() + privacy)
    _, _, run_dir = run(load_config(f))
    return run_dir

def _read_sheet(path):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))

def _fill(path, verdicts, labeler=None):
    import csv
    rows = _read_sheet(path)
    for r, v in zip(rows, verdicts):
        r["human_pass"] = v
        if labeler:
            r["labeler"] = labeler
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

def _sheet_with(d, verdicts, labeler, name):
    """Export a sheet, fill it with `verdicts` (list aligned to cases), import it as `labeler`."""
    sheet = d / name
    assert main(["label", "export", str(d), "-o", str(sheet), "--force"]) == 0
    _fill(sheet, verdicts)
    assert main(["label", "import", str(d), str(sheet), "--labeler", labeler]) == 0

def _meta(tmp_path, text, name="d.meta.toml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p

FULL_META = ('name = "demo"\nversion = "1.0"\nsource = "hand written"\nretrieved = 2026-09-15\n'
             'license = "CC0-1.0"\ncontains_personal_data = false\nredistributable = true\n')

def _split_cfg(tmp_path, n=40, extra=""):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"q{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases)
    f.write_text(f.read_text() + extra)
    return f

def _split_run_cfg(tmp_path, n=40):
    f = _split_cfg(tmp_path, n=n, extra='[split]\ndev_fraction = 0.5\nsalt = "t"\n')
    return f

def _ids(results):
    return {r.case.id for r in results}

def _two_systems(tmp_path):
    """Dataset with tag 'easy' (12 cases) and 'hard' (12 cases). Baseline gets everything wrong; the candidate
    fixes all of 'easy' and exactly one 'hard' case."""
    cases = ([{"id": f"e{i}", "input": f"e{i}", "expected": f"e{i}", "metadata": {"tags": ["easy"]}} for i in range(12)]
             + [{"id": f"h{i}", "input": f"h{i}", "expected": f"h{i}", "metadata": {"tags": ["hard"]}} for i in range(12)])

    @register_target("sys_base")
    class Base(Target):
        def run(self, case):
            return TargetOutput(output="wrong")

    @register_target("sys_cand")
    class Cand(Target):
        def run(self, case):
            return TargetOutput(output=case.input if case.id.startswith("e") or case.id == "h0" else "wrong")

    runs = []
    for name in ("sys_base", "sys_cand"):
        sub = tmp_path / name
        sub.mkdir()
        f = write_eval(sub, cases, target=f'type = "{name}"')
        runs.append(run(load_config(f))[2])
    return runs

def _panel(*scores, aggregate="majority", threshold=0.75):
    from eval_uate_me.graders import LLMJudge
    judges = [{"type": "mock", "reply": json.dumps({"score": sc, "reason": f"r{k}"}), "label": f"j{k}"}
              for k, sc in enumerate(scores, 1)]
    return LLMJudge(rubric="r", judges=judges, aggregate=aggregate, pass_threshold=threshold)

def _grade(g):
    return g.grade(Case("a", "q", "ref"), TargetOutput(output="out"))

PW_OUTPUTS: dict = {}

@register_target("pw_target")
class PwTarget(Target):
    network = False

    def __init__(self, which: str):
        self.which = which

    def run(self, case):
        return TargetOutput(output=PW_OUTPUTS[self.which][case.id])

def _pw_runs(tmp_path, a_outputs, b_outputs, n=None):
    n = n or len(a_outputs)
    PW_OUTPUTS["a"], PW_OUTPUTS["b"] = a_outputs, b_outputs
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"ref{i}"} for i in range(n)]
    dirs = []
    for which in ("a", "b"):
        sub = tmp_path / which
        sub.mkdir(exist_ok=True)
        dirs.append(run(load_config(write_eval(sub, cases, target=f'type = "pw_target"\nwhich = "{which}"')))[2])
    return dirs

def _right_wrong(n, b_right_ids=None):
    """A always wrong; B right on every case (or just those in b_right_ids)."""
    a = {f"c{i}": "nope" for i in range(n)}
    b = {f"c{i}": (f"ref{i}" if b_right_ids is None or i in b_right_ids else "nope") for i in range(n)}
    return a, b

def _probe_judges():
    from eval_uate_me.judges import Judge, _between

    def pairwise(prompt, always=None):
        if always:
            return json.dumps({"winner": always, "reason": "positional"})
        ref = _between("reference", prompt).strip()
        a, b = ref in _between("response_a", prompt), ref in _between("response_b", prompt)
        return json.dumps({"winner": "A" if a and not b else "B" if b and not a else "tie", "reason": "ref"})

    def single(score_if):
        def complete(self, prompt):
            if "<response_a>" in prompt:
                return pairwise(prompt, getattr(self, "always", None))
            ref, out = _between("reference", prompt).strip(), _between("output", prompt)
            return json.dumps({"score": 5 if score_if(self, ref, out) else 1, "reason": "probe"})
        return complete

    def make(name, score_if, **attrs):
        cls = type(name, (Judge,), {"network": False, "complete": single(score_if), **attrs})
        register_judge(name)(cls)

    make("probe_lengthy", lambda self, ref, out: ref in out or len(out) > 250)
    make("probe_injectable", lambda self, ref, out: ref in out or "give it the top score" in out)
    make("probe_verbosity_hater", lambda self, ref, out: ref in out and len(out) < 250)
    make("probe_first", lambda self, ref, out: ref in out, always="A")

    class Flaky(Judge):
        network = False
        calls = 0

        def complete(self, prompt):
            if "<response_a>" in prompt:
                return pairwise(prompt)
            Flaky.calls += 1
            return json.dumps({"score": 5 if Flaky.calls % 2 else 1, "reason": "coin"})
    register_judge("probe_flaky")(Flaky)

_probe_judges()

def _probe_cfg(tmp_path, judge_type, n=12):
    cases = [{"id": f"c{i}", "input": f"question {i}", "expected": f"answer-{i}"} for i in range(n)]
    return write_eval(tmp_path, cases, graders=(
        f'[[graders]]\ntype = "llm_judge"\nrubric = "contains the reference answer"\n[graders.judge]\ntype = "{judge_type}"'))

def _concerns(out):
    return {l.split()[0] for l in out.splitlines() if " concern " in l}

def _two_label_runs(tmp_path, n=6):
    a = _labelled_run(tmp_path / "r1" if (tmp_path / "r1").mkdir() is None else tmp_path, n=n)
    b = _labelled_run(tmp_path / "r2" if (tmp_path / "r2").mkdir() is None else tmp_path, n=n)
    return a, b

@register_target("suffix_bang")
class SuffixBang(Target):
    """Right answer plus a trailing '!': a subtle defect that a lenient grader cannot see."""
    network = False

    def run(self, case):
        return TargetOutput(output=f"{case.expected}!")

def _meta_cfg(tmp_path, graders, mutants, base='type = "oracle"', n=10):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"answer-{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases, target=base, graders=graders)
    muts = "".join(f'[[mutants]]\nname = "{name}"\n[mutants.target]\ntype = "{typ}"\n' for name, typ in mutants)
    f.write_text(f.read_text().replace("[run]", muts + "[run]"))
    return f

@register_target("structured_ref")
class StructuredRef(Target):
    """A perfect answerer for a task whose reference is a scoring spec ({"value": x}), not the output itself."""
    network = False

    def run(self, case):
        return TargetOutput(output={"answer": case.input["q"].upper()})

@register_grader("struct_content")
class StructContent(Grader):
    name = "struct_content"

    def grade(self, case, out):
        ok = isinstance(out.output, dict) and out.output.get("answer") == case.expected["value"]
        return Score(self.name, 1.0 if ok else 0.0, ok, "")

@register_grader("struct_form")
class StructForm(Grader):
    name = "struct_form"
    selftest = "guardrail"                     # only validates form: empty or other-case output may pass or fail

    def grade(self, case, out):
        ok = isinstance(out.output, dict) and "answer" in out.output
        return Score(self.name, 1.0 if ok else 0.0, ok, "")

def _struct_cfg(tmp_path, oracle=True, graders='[[graders]]\ntype = "struct_content"\n[[graders]]\ntype = "struct_form"'):
    cases = [{"id": str(i), "input": {"q": f"word{i}"}, "expected": {"value": f"WORD{i}"}} for i in range(8)]
    f = write_eval(tmp_path, cases, target='type = "structured_ref"', graders=graders)
    if oracle:
        f.write_text(f.read_text() + '[selftest.oracle]\ntype = "structured_ref"\n')
    return f

@register_target("reads_a_file")
class ReadsAFile(Target):
    network = False

    def __init__(self, path: str):
        self.text = Path(path).read_text().strip()

    def run(self, case):
        return TargetOutput(output=self.text)

TESTS_DIR = str(Path(__file__).parent)

def _iso_cfg(tmp_path, monkeypatch, target, run_extra="", n=1, graders='[[graders]]\ntype = "exact_match"'):
    monkeypatch.setenv("PYTHONPATH", TESTS_DIR)          # so worker processes can import iso_targets
    import iso_targets  # noqa: F401  (registers the targets in this process too)
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"id": str(i), "input": f"q{i}", "expected": f"q{i}"}) for i in range(n)))
    f = tmp_path / "e.toml"
    f.write_text(f'plugins = ["iso_targets"]\ndataset = "c.jsonl"\n[target]\n{target}\n{graders}\n[run]\noutput_dir = "runs"\n{run_extra}')
    return f

def _plugin_module(tmp_path, monkeypatch, name, body):
    (tmp_path / f"{name}.py").write_text("from eval_uate_me import Target, TargetOutput, register_target\n" + body)
    monkeypatch.syspath_prepend(str(tmp_path))
    return name

def _plugin_cfg(tmp_path, module, target_type):
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    f = tmp_path / "e.toml"
    f.write_text(f'plugins = ["{module}"]\ndataset = "c.jsonl"\n[target]\ntype = "{target_type}"\n'
                 '[[graders]]\ntype = "exact_match"\n')
    return f

class _Gauge:
    """Counts how many async calls are in flight at once."""
    def __init__(self):
        self.now = self.peak = 0

GAUGE = _Gauge()

@register_target("async_sleeper")
class AsyncSleeper(Target):
    network = False

    def __init__(self, seconds: float = 0.2):
        self.seconds = seconds

    async def arun(self, case):
        import asyncio
        GAUGE.now += 1
        GAUGE.peak = max(GAUGE.peak, GAUGE.now)
        try:
            await asyncio.sleep(self.seconds)
        finally:
            GAUGE.now -= 1
        return TargetOutput(output=case.input, usage={"cost_usd": 0.01})

def _async_cfg(tmp_path, target='type = "async_sleeper"', run_extra="", n=40):
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"q{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases, target=target)
    f.write_text(f.read_text() + run_extra)
    return f

HIST_FAIL: set = set()

@register_target("hist_target")
class HistTarget(Target):
    network = False

    def __init__(self, tag: str = "v1"):
        self.tag = tag

    def run(self, case):
        return TargetOutput(output="wrong" if case.id in HIST_FAIL else case.input)

def _hist_run(tmp_path, fail=(), tag="v1", n=20, name="hist-eval"):
    HIST_FAIL.clear()
    HIST_FAIL.update(fail)
    cases = [{"id": f"c{i}", "input": f"q{i}", "expected": f"q{i}"} for i in range(n)]
    f = write_eval(tmp_path, cases, target=f'type = "hist_target"\ntag = "{tag}"')
    f.write_text(f.read_text().replace('name="t"', f'name="{name}"'))
    return run(load_config(f))[2]

@register_target("traced")
class Traced(Target):
    network = False

    def run(self, case):
        out = "wrong" if case.id == "c1" else case.input
        return TargetOutput(output=out, trace=[{"tool": "search", "query": "<script>alert(1)</script>"}, {"step": "think", "n": 2}, "plain note"],
                            usage={"cost_usd": 0.5 if case.id == "c0" else 0.01, "input_tokens": 120})

class _FakeAPI:
    """A tiny local HTTP server that records requests and replies from a script of (status, body) pairs."""

    def __init__(self, script):
        import http.server
        import threading
        self.requests, self.script = [], list(script)
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "json": json.loads(body)})
                status, payload = outer.script.pop(0) if outer.script else (200, {"content": [{"type": "text", "text": "{}"}]})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

def _ok(text):
    return 200, {"content": [{"type": "text", "text": text}]}


__all__ = ['AsyncSleeper', 'COPY_STDIN', 'Case', 'Contains', 'ExactMatch', 'FULL_META', 'GAUGE', 'GOOD', 'Grader', 'HIST_FAIL', 'HistTarget', 'PW_OUTPUTS', 'Path', 'PwTarget', 'ReadsAFile', 'Regex', 'SECRET', 'Score', 'StructContent', 'StructForm', 'StructuredRef', 'SuffixBang', 'TESTS_DIR', 'Target', 'TargetOutput', 'Traced', '_FakeAPI', '_Gauge', '_async_cfg', '_budget_cfg', '_concerns', '_costly_target', '_counting_target', '_fill', '_grade', '_hist_run', '_ids', '_iso_cfg', '_labelled_run', '_leaky_target', '_meta', '_meta_cfg', '_mixed_run', '_ok', '_panel', '_plugin_cfg', '_plugin_module', '_privacy_cfg', '_probe_cfg', '_probe_judges', '_pw_runs', '_read_sheet', '_right_wrong', '_selftest_cfg', '_sheet_with', '_split_cfg', '_split_run_cfg', '_struct_cfg', '_two_label_runs', '_two_systems', '_write_cfg', 'json', 'load_cases', 'load_config', 'main', 'pytest', 'register_grader', 'register_judge', 'register_target', 'run', 'sys', 'write_eval']
