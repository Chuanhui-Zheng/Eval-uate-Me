"""A snapshot of the public surface promised in docs/VERSIONING.md. If this fails you are about to make a breaking change:
either revert it, or make it deliberately (a major release, updating this file and the docs together).
Additive changes (a new command, a new optional field) only require extending the expected values."""
import dataclasses
import inspect
import re

import eval_uate_me
from eval_uate_me import cli, config, graders, judges, models, registry, targets


def test_python_api_names_and_signatures():
    assert sorted(eval_uate_me.__all__) == [
        "API_VERSION", "Case", "CaseResult", "ConfigError", "EvalResult", "Grader", "Judge", "PluginError", "Score",
        "Target", "TargetOutput", "TraceStep", "evaluate", "register_grader", "register_judge", "register_target", "run_eval"]
    assert eval_uate_me.API_VERSION == 1
    sig = lambda f: str(inspect.signature(f))  # noqa: E731
    assert sig(targets.Target.run) == "(self, case: 'Case') -> 'TargetOutput'"
    assert sig(graders.Grader.grade) == "(self, case: 'Case', out: 'TargetOutput') -> 'Score'"
    assert sig(judges.Judge.complete) == "(self, prompt: 'str') -> 'str'"
    for f in (registry.register_target, registry.register_grader, registry.register_judge):
        assert sig(f) == "(name: 'str')"


def test_dataclass_fields_only_grow():
    fields = lambda c: [f.name for f in dataclasses.fields(c)]  # noqa: E731
    assert fields(models.Case) == ["id", "input", "expected", "metadata"]
    assert fields(models.TargetOutput) == ["output", "trace", "error", "latency_s", "usage", "retries", "cached"]
    assert fields(models.Score) == ["grader", "value", "passed", "reason", "role", "cost_usd", "detail"]
    assert fields(models.CaseResult) == ["case", "result", "scores", "attempt"]


def test_config_keys_only_grow():
    assert sorted(config.TOP_KEYS) == ["dataset", "dataset_meta", "gate", "graders", "mutants", "name", "plugins", "privacy",
                                       "run", "selftest", "split", "target"]
    assert sorted(config.RUN_KEYS) == [
        "cache", "concurrency", "cpu_limit_s", "docker_image", "docker_mounts", "docker_network", "env_passthrough", "isolation",
        "judge_cache", "max_cost_usd", "max_per_second", "memory_limit_mb", "output_dir", "repeats", "retries", "retry_delay_s", "seed", "timeout_s"]


def test_cli_commands_and_builtins_only_grow():
    cmds = set(re.findall(r'sub\.add_parser\("([a-z-]+)"', inspect.getsource(cli.main)))
    assert cmds >= {"baseline", "gate", "calibrate", "check", "compare", "history", "init", "init-plugin", "judge-check", "label", "lint", "list",
                    "meta-eval", "pairwise", "power", "report", "run", "selftest", "show", "split"}
    avail = registry.available()
    assert set(avail["targets"]) >= {"command", "echo", "http", "null", "oracle", "python"}
    assert set(avail["graders"]) >= {"contains", "exact_match", "llm_judge", "max_cost", "max_latency", "max_steps", "regex", "tool_use"}
    assert set(avail["judges"]) >= {"anthropic", "openai_compat"}


def test_on_disk_formats_keep_their_keys(tmp_path):
    import json
    from eval_uate_me.runner import run
    from eval_uate_me.config import load_config
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a","metadata":{"tags":["t"]}}')
    (tmp_path / "e.toml").write_text('dataset = "c.jsonl"\n[target]\ntype = "echo"\n[[graders]]\ntype = "exact_match"\n')
    _, _, d = run(load_config(tmp_path / "e.toml"))
    row = json.loads((d / "results.jsonl").read_text().splitlines()[0])
    assert set(row) >= {"case", "result", "scores", "attempt", "passed", "format_version"}
    assert set(row["case"]) >= {"id", "input", "expected", "metadata"}
    assert set(row["result"]) >= {"output", "trace", "error", "latency_s", "usage", "retries", "cached"}
    assert set(row["scores"][0]) >= {"grader", "value", "passed", "reason", "role"}
    summary = json.loads((d / "summary.json").read_text())
    assert set(summary) >= {"format_version", "name", "cases", "repeats", "total", "passed", "failed", "errors", "pass_rate", "pass_rate_ci95",
                            "error_rate", "pass_rate_answered", "mean_score_by_grader", "by_tag", "failure_reasons",
                            "latency_p50_s", "planned", "incomplete", "cost_usd_spent", "privacy_store", "split"}
    manifest = json.loads((d / "manifest.json").read_text())
    assert set(manifest) >= {"format_version", "harness_version", "name", "status", "started_at", "finished_at", "dataset_sha256", "config_sha256",
                             "n_cases", "repeats", "seed", "target", "graders", "plugins", "git", "privacy", "split", "resumes"}
