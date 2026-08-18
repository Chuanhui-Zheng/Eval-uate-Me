from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, judges, registry, report, report_html  # noqa: F401  (judges: registers built-ins)
from .calibration import calibrate, disagreements, format_calibration, format_disagreements
import json

from .config import ConfigError, load_cases, load_config
from .scaffold import init_plugin, init_project
from .stats import detectable_effect_paired, detectable_effect_unpaired, sample_size_paired, sample_size_unpaired
from .splits import SPLITS, export as export_splits, split_cases
from .runner import _make, ResumeMismatch, RunInterrupted, build_graders, build_target, load_plugins, run
from .dataset_meta import resolve_meta
from .labels import carry_labels, export_sheet, import_sheet
from .metaeval import DEFAULT_RATES, format_meta_eval, run_meta_eval
from .gate import baseline_path, evaluate_gate, format_for_ci, latest_run, load_baseline, promote
from .history import analyse, format_history, render_html, scan
from .judgecheck import find_judge_grader, format_checks, run_checks
from .pairwise import compare_runs, format_pairwise
from .privacy import enforce_local_only
from .lint import format_findings, lint, to_dicts
from .selftest import format_report, selftest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evalharness", description="Plugin-based eval harness")
    p.add_argument("--version", action="version", version=f"evalharness {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run an eval from a TOML config")
    r.add_argument("config")
    r.add_argument("--resume", metavar="RUN_DIR", default=None,
                   help="continue an interrupted run, executing only the jobs that are missing")
    r.add_argument("--retry-errors", action="store_true", help="with --resume, also re-run jobs whose target errored")
    r.add_argument("--force", action="store_true", help="with --resume, ignore a changed config/dataset")
    r.add_argument("--split", choices=("all", "dev", "heldout"), default=None,
                   help="which part of the dataset to run (default: dev if the dataset has splits, else all)")
    r.add_argument("--max-error-rate", type=float, default=None,
                   help="exit 1 if more than this fraction of attempts errored (0-1)")
    r.add_argument("--max-cost", type=float, default=None, metavar="USD",
                   help="stop starting new jobs once this much usage.cost_usd is spent (overrides run.max_cost_usd)")
    r.add_argument("--fail-under", type=float, default=None, help="exit 1 if pass rate is below this (0-1)")

    i = sub.add_parser("init", help="create a starter eval project (config, sample cases, README)")
    i.add_argument("directory")

    ip = sub.add_parser("init-plugin", help="create an installable plugin package with a target, a grader and tests")
    ip.add_argument("name", help="lowercase package name, e.g. cve_triage")
    ip.add_argument("--dir", default=".", help="where to create it (default: current directory)")

    sp = sub.add_parser("split", help="show how the dataset divides into dev and held-out, optionally export the parts")
    sp.add_argument("config")
    sp.add_argument("--export", metavar="DIR", default=None, help="write dev.jsonl and heldout.jsonl into DIR")
    sp.add_argument("--only", choices=SPLITS, default=None, help="with --export, write just one part")
    sp.add_argument("--force", action="store_true", help="with --export, overwrite existing files")

    pw = sub.add_parser("power", help="how many cases do you need to see a difference (or what can you see with n)?")
    pw.add_argument("--baseline", type=float, required=True, help="expected pass rate of the baseline system (0-1)")
    pw.add_argument("--delta", type=float, default=None, help="the improvement you want to detect, e.g. 0.05")
    pw.add_argument("--n", type=int, default=None, help="instead: the cases you have; report the smallest detectable delta")
    pw.add_argument("--config", default=None, help="take n from this config's dataset")
    pw.add_argument("--paired", action="store_true", help="both systems run on the same cases (needs --discordant)")
    pw.add_argument("--discordant", type=float, default=None,
                    help="with --paired: fraction of cases where the two systems' outcomes differ (e.g. 0.2)")
    pw.add_argument("--alpha", type=float, default=0.05)
    pw.add_argument("--power", type=float, default=0.8)

    ck = sub.add_parser("check", help="validate a config, dataset and plugins without running anything")
    ck.add_argument("config")

    c = sub.add_parser("compare", help="compare two run directories (baseline, candidate)")
    c.add_argument("baseline")
    c.add_argument("candidate")
    c.add_argument("--markdown", action="store_true", help="print a GitHub-flavoured Markdown summary (for a PR comment)")
    c.add_argument("--title", default="Eval comparison", help="heading for --markdown")

    n = sub.add_parser("lint", help="check a dataset for problems that make scores meaningless")
    n.add_argument("target", help="a config .toml or a cases .jsonl file")
    n.add_argument("--min-cases", type=int, default=30)
    n.add_argument("--strict", action="store_true", help="exit 1 if there are any warnings")
    n.add_argument("--json", dest="json_out", default=None)

    t = sub.add_parser("selftest", help="check graders against oracle/null/shuffled baselines")
    t.add_argument("config")
    t.add_argument("--min-oracle", type=float, default=0.95, help="min pass rate the oracle must reach")
    t.add_argument("--max-bad", type=float, default=0.05, help="max pass rate allowed for null/shuffled")
    t.add_argument("--json", dest="json_out", default=None, help="also write the report as JSON")

    h = sub.add_parser("report", help="(re)generate report.html for a run directory")
    h.add_argument("run_dir")

    w = sub.add_parser("show", help="print a run's manifest and headline numbers")
    w.add_argument("run_dir")

    me = sub.add_parser("meta-eval", help="does the evaluation catch deliberately broken variants ([[mutants]])? ")
    me.add_argument("config")
    me.add_argument("--min-drop", type=float, default=0.10, help="a mutant must score at least this much lower (default 0.10)")
    me.add_argument("--alpha", type=float, default=0.05)
    me.add_argument("--repeats", type=int, default=None, help="attempts per case (default: the config's run.repeats)")
    me.add_argument("--split", choices=("all", "dev", "heldout"), default=None)
    me.add_argument("--auto", action="store_true", help="also generate operator mutants for every field of the real outputs")
    me.add_argument("--sensitivity", action="store_true",
                    help="run operator mutants at several damage rates to find the smallest rate the evaluation notices")
    me.add_argument("--rates", default=None, help="with --sensitivity: comma-separated rates (default 0.05,0.1,0.25,0.5,1)")
    me.add_argument("--max-mutants", type=int, default=150, help="with --auto: cap the number of generated mutants (default 150)")
    me.add_argument("--max-survivors", type=int, default=None,
                    help="with --auto: exit 1 if more than this many generated mutants survive (default: informational only)")
    me.add_argument("--seed", type=int, default=0)
    me.add_argument("--allow-network", action="store_true",
                    help="allow --auto/--sensitivity even though a grader calls a hosted model (it can mean many paid calls)")
    me.add_argument("--json", dest="json_out", default=None)

    bl = sub.add_parser("baseline", help="remember a good run as the baseline that `gate` compares against")
    bls = bl.add_subparsers(dest="baseline_cmd", required=True)
    bp = bls.add_parser("promote", help="write a run's metrics and per-case results as the baseline file")
    bp.add_argument("run_dir", nargs="?", default=None, help="the run to promote (default: the latest run of the config)")
    bp.add_argument("--config", default="eval.toml")
    bp.add_argument("--out", default=None, help="baseline file (default: [gate] baseline, or <config>.baseline.json)")

    gt = sub.add_parser("gate", help="CI check: fail (exit 1) if the latest run regressed against the baseline")
    gt.add_argument("config", nargs="?", default="eval.toml")
    gt.add_argument("--run", default=None, help="run directory to check (default: the latest run of the config)")
    gt.add_argument("--baseline", default=None, help="baseline file (default: [gate] baseline)")

    hi = sub.add_parser("history", help="how scores move across the runs in a folder, and whether the latest run regressed")
    hi.add_argument("runs_dir", help="a folder of run directories (the config's output_dir, e.g. runs/)")
    hi.add_argument("--name", default=None, help="only runs of this eval name")
    hi.add_argument("--split", choices=("all", "dev", "heldout"), default=None)
    hi.add_argument("--html", metavar="FILE", default=None, help="also write a self-contained HTML page with charts")
    hi.add_argument("--fail-on-regression", action="store_true", help="exit 1 if the latest run is a significant drop")

    sub.add_parser("worker", help=argparse.SUPPRESS)  # internal: used by isolation = "process" / "docker"

    jc = sub.add_parser("judge-check", help="probe an llm_judge for length, position and injection bias")
    jc.add_argument("config")
    jc.add_argument("--grader", default=None, help="name of the llm_judge grader to probe (default: the first)")
    jc.add_argument("--sample", type=int, default=20, help="how many cases to use (default 20)")
    jc.add_argument("--repeats", type=int, default=3, help="times to judge the same answer (default 3)")
    jc.add_argument("--seed", type=int, default=0)
    jc.add_argument("--max-calls", type=int, default=200, help="refuse to make more judge calls than this")
    jc.add_argument("--cache", metavar="DIR", default=None, help="cache judge replies here, so re-running costs nothing")
    jc.add_argument("--json", dest="json_out", default=None)

    pr = sub.add_parser("pairwise", help="have a judge decide, case by case, which of two runs answered better")
    pr.add_argument("run_a", help="baseline run directory")
    pr.add_argument("run_b", help="candidate run directory")
    pr.add_argument("--rubric", required=True, help="what 'better' means, in a sentence or two")
    pr.add_argument("--judge", default="mock", help="judge backend: mock, anthropic, or a plugin's judge (default: mock)")
    pr.add_argument("--judge-opt", action="append", default=[], metavar="KEY=VALUE", help="judge option, repeatable")
    pr.add_argument("--plugin", action="append", default=[], help="extra module to import (for plugin judges)")
    pr.add_argument("--single-order", action="store_true",
                    help="judge each pair once in a random order instead of both orders (half the cost, less robust)")
    pr.add_argument("--seed", type=int, default=0)
    pr.add_argument("--max-calls", type=int, default=200, help="refuse to make more judge calls than this")
    pr.add_argument("--cache", metavar="DIR", default=None, help="cache judge replies here, so re-running costs nothing")
    pr.add_argument("--json", dest="json_out", default=None)

    k = sub.add_parser("calibrate", help="compare a grader with human labels (from `label import`)")
    k.add_argument("run_dir")
    k.add_argument("--grader", default="llm_judge", help="a grader name, or 'overall' for the final pass/fail verdict")
    k.add_argument("--json", dest="json_out", default=None, help="also write the result as JSON")

    lb = sub.add_parser("label", help="human labelling: export a sheet for reviewers, import their labels")
    ls = lb.add_subparsers(dest="label_cmd", required=True)
    le = ls.add_parser("export", help="write a CSV sheet of outputs for people to mark pass/fail")
    le.add_argument("run_dir")
    le.add_argument("-o", "--out", default=None, help="sheet path (default: <run_dir>/label_sheet.csv)")
    le.add_argument("--sample", type=int, default=None, help="label only N attempts (random, reproducible)")
    le.add_argument("--seed", type=int, default=0)
    le.add_argument("--balance", action="store_true", help="with --sample, take about equal passes and failures")
    le.add_argument("--show-verdicts", action="store_true",
                    help="include automatic verdicts (off by default so reviewers are not anchored by them)")
    le.add_argument("--unlabelled-only", action="store_true",
                    help="skip attempts that already have a label (e.g. carried over from an earlier run)")
    le.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    lc = ls.add_parser("carry", help="copy labels from an earlier run onto this one where the output is identical")
    lc.add_argument("from_run")
    lc.add_argument("to_run")
    li = ls.add_parser("import", help="read a filled sheet into <run_dir>/labels.jsonl")
    li.add_argument("run_dir")
    li.add_argument("sheet")
    li.add_argument("--labeler", default=None, help="name for every row (otherwise the sheet's labeler column)")

    ld = ls.add_parser("disagreements", help="list attempts where reviewers and a grader differ")
    ld.add_argument("run_dir")
    ld.add_argument("--grader", default="overall", help="a grader name, or 'overall' (default)")
    ld.add_argument("--limit", type=int, default=20)
    ld.add_argument("--show-output", action="store_true", help="also print (the start of) each output")

    l = sub.add_parser("list", help="list registered targets and graders")
    l.add_argument("--plugin", action="append", default=[], help="extra module to import")

    args = p.parse_args(argv)
    try:
        return _dispatch(args)
    except ConfigError as e:
        print("config error:\n" + "\n".join(f"  - {m}" for m in e.problems), file=sys.stderr)
        return 2


def _dispatch(args) -> int:

    if args.cmd == "run":
        cfg = load_config(args.config)
        if args.max_cost is not None:
            cfg.max_cost_usd = args.max_cost
        try:
            results, summary, out_dir = run(cfg, resume=Path(args.resume) if args.resume else None,
                                            retry_errors=args.retry_errors, force=args.force, split=args.split)
        except RunInterrupted as e:
            print(f"\ninterrupted after {e.completed}/{e.planned} jobs; results so far are in {e.out_dir}\n"
                  f"resume with: evalharness run {args.config} --resume {e.out_dir}", file=sys.stderr)
            return 130
        except ResumeMismatch as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        report.print_report(results, summary, out_dir)
        if summary["incomplete"]:
            print(f"resume with a higher budget: evalharness run {args.config} --resume {out_dir} --max-cost <USD>",
                  file=sys.stderr)
            return 3
        if args.fail_under is not None and summary["pass_rate"] < args.fail_under:
            return 1
        if args.max_error_rate is not None and summary["error_rate"] > args.max_error_rate:
            print(f"error rate {summary['error_rate']:.0%} exceeds --max-error-rate {args.max_error_rate:.0%}",
                  file=sys.stderr)
            return 1
        return 0
    if args.cmd == "label":
        if args.label_cmd == "export":
            out = Path(args.out) if args.out else Path(args.run_dir) / "label_sheet.csv"
            info = export_sheet(Path(args.run_dir), out, args.sample, args.seed, args.balance,
                                args.show_verdicts, args.force, args.unlabelled_only)
            print(f"wrote {info['rows']} of {info['eligible']} attempts to {info['path']}"
                  + (f" ({info['errored_skipped']} errored attempts skipped)" if info["errored_skipped"] else "")
                  + f"\nreviewers fill human_pass (yes/no) and optionally notes and labeler; "
                    f"{'automatic verdicts are hidden' if info['blind'] else 'automatic verdicts are shown'}"
                  + f"\nthen: evalharness label import {args.run_dir} {info['path']}")
            return 0
        if args.label_cmd == "disagreements":
            items = disagreements(Path(args.run_dir), args.grader)
            print(format_disagreements(items, limit=args.limit, show_output=args.show_output))
            return 0
        if args.label_cmd == "carry":
            info = carry_labels(Path(args.from_run), Path(args.to_run))
            print(f"carried {info['carried']} labels onto {args.to_run} ({info['no_match']} not carried: output changed "
                  f"or case missing; {info['already_labelled']} already labelled there)")
            return 0
        if args.label_cmd == "import":
            info = import_sheet(Path(args.run_dir), Path(args.sheet), args.labeler)
            print(f"imported {info['imported']} labels ({info['updated']} replaced earlier ones, "
                  f"{info['blank_skipped']} blank rows skipped) from {', '.join(info['labelers']) or 'nobody'}")
            return 0
    if args.cmd == "init":
        files = init_project(args.directory)
        print(f"created {len(files)} files in {args.directory}\nnext: cd {args.directory} && evalharness check eval.toml "
              "&& evalharness run eval.toml")
        return 0
    if args.cmd == "init-plugin":
        root, files = init_plugin(args.name, args.dir)
        print(f"created {len(files)} files in {root}\nnext: cd {root} && pip install -e . && evalharness run eval.toml")
        return 0
    if args.cmd == "split":
        cfg = load_config(args.config)
        cases = load_cases(cfg.dataset)
        parts = split_cases(cases, cfg.split_dev_fraction, cfg.split_salt)
        explicit = sum(1 for c in cases if "split" in c.metadata)
        for name in SPLITS:
            print(f"{name:<8}{len(parts[name]):>5} cases ({len(parts[name]) / len(cases):.0%})")
        print(f"{explicit} case(s) set metadata.split explicitly; the rest were assigned by hash of id"
              + (f" (dev_fraction={cfg.split_dev_fraction}, salt={cfg.split_salt!r})" if cfg.split_dev_fraction else ""))
        if args.export:
            for name, path in export_splits(cases, cfg.split_dev_fraction, cfg.split_salt, Path(args.export),
                                            args.only, args.force).items():
                print(f"wrote {path}")
        return 0
    if args.cmd == "power":
        n = args.n if args.n is not None else (len(load_cases(load_config(args.config).dataset)) if args.config else None)
        if (args.delta is None) == (n is None):
            raise ConfigError("give either --delta (how many cases do I need?) or --n / --config (what can I detect?)")
        if args.paired and args.discordant is None:
            raise ConfigError("--paired needs --discordant, the fraction of cases where the two systems differ")
        try:
            if args.delta is not None:
                need = (sample_size_paired(args.delta, args.discordant, args.alpha, args.power) if args.paired
                        else sample_size_unpaired(args.baseline, args.delta, args.alpha, args.power))
                print(f"to detect a pass-rate change of {args.delta:+.1%} from {args.baseline:.0%} "
                      f"({'paired' if args.paired else 'two independent samples'}, alpha={args.alpha}, "
                      f"power={args.power:.0%}): {need} cases" + ("" if args.paired else " per system"))
            else:
                assert n is not None  # guaranteed by the check above: either --delta or --n/--config was given
                d = (detectable_effect_paired(n, args.discordant, args.alpha, args.power) if args.paired
                     else detectable_effect_unpaired(n, args.baseline, args.alpha, args.power))
                print(f"with {n} cases (baseline {args.baseline:.0%}, alpha={args.alpha}, power={args.power:.0%}) "
                      + ("no difference is reliably detectable" if d != d else
                         f"the smallest reliably detectable difference is about {d:.1%}"))
                if d == d and d > 0.15:
                    print("that is a large gap: with this few cases only big differences will show up; "
                          "add cases before trusting a small one")
        except ValueError as e:
            raise ConfigError(str(e)) from e
        print("assumes independent cases (repeating a case adds precision about the system's randomness, not new cases) "
              "and a normal approximation; treat it as a planning estimate")
        return 0
    if args.cmd == "check":
        cfg = load_config(args.config)
        load_plugins(cfg)
        cases = load_cases(cfg.dataset)
        target = build_target(cfg)
        graders = build_graders(cfg)
        for note in (enforce_local_only(target, graders) if cfg.local_only else []):
            print(f"privacy warning: {note}", file=sys.stderr)
        dm = resolve_meta(cfg.dataset, cfg.dataset_meta)
        und = set(registry.undeclared())
        used = [("target", cfg.target["type"])] + [("grader", g["type"]) for g in cfg.graders]
        for kind, name in used:
            if (kind, name) in und:
                print(f"note: {kind} '{name}' declares no plugin API version; it may break on a major upgrade "
                      f"(set `evalharness_api = {registry.API_VERSION}` on the class)", file=sys.stderr)
        print("dataset metadata: " + (f"{dm.name or '?'} v{dm.version or '?'}, licence {dm.license or 'unrecorded'}"
                                      if dm else "none (lint will warn)"))
        print(f"ok: {len(cases)} cases, target '{cfg.target['type']}', graders "
              f"{[g.name + ('' if g.role == 'required' else ' (advisory)') for g in graders]}")
        return 0
    if args.cmd == "compare":
        if args.markdown:
            text, n_regressed = report.markdown_compare(Path(args.baseline), Path(args.candidate), args.title)
            print(text)
            return 1 if n_regressed else 0
        return 1 if report.compare(Path(args.baseline), Path(args.candidate)) else 0
    if args.cmd == "lint":
        path = Path(args.target)
        if path.suffix == ".jsonl":
            dataset, override, store, frac, salt = path, None, None, None, ""
        else:
            cfg = load_config(path)
            dataset, override, store = cfg.dataset, cfg.dataset_meta, cfg.privacy_store
            frac, salt = cfg.split_dev_fraction, cfg.split_salt
        cases = load_cases(dataset)
        findings = lint(cases, min_cases=args.min_cases, check_meta=True, meta=resolve_meta(dataset, override),
                        dataset_path=dataset, privacy_store=store, split_dev_fraction=frac, split_salt=salt)
        print(format_findings(findings, len(cases)))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(to_dicts(findings), indent=2, ensure_ascii=False), encoding="utf-8")
        return 1 if args.strict and any(f.level == "warn" for f in findings) else 0
    if args.cmd == "selftest":
        cfg = load_config(args.config)
        load_plugins(cfg)
        oracle = _make("target", cfg.selftest_oracle, "[selftest.oracle]") if cfg.selftest_oracle else None
        rep = selftest(load_cases(cfg.dataset), build_graders(cfg), args.min_oracle, args.max_bad, oracle)
        print(format_report(rep))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if rep.ok else 1
    if args.cmd == "report":
        print(report_html.write(Path(args.run_dir)))
        return 0
    if args.cmd == "show":
        report.show(Path(args.run_dir))
        return 0
    if args.cmd == "baseline":
        cfg = load_config(args.config)
        run_dir = Path(args.run_dir) if args.run_dir else latest_run(cfg.output_dir, cfg.name)
        out = Path(args.out) if args.out else baseline_path(cfg, Path(args.config).resolve())
        previous = load_baseline(out)
        base = promote(run_dir, out)
        print(f"promoted {run_dir.name} as the baseline: {out}"
              + (f"\n(replaced {previous['run_id']})" if previous else "")
              + "\n" + "\n".join(f"  {k} = {v:.4f}" for k, v in sorted(base["metrics"].items()) if not k.startswith(("tag.", "grader.")))
              + "\ncommit this file so CI can compare against it")
        if base["metrics"].get("error_rate", 0) > 0:
            print(f"warning: this run had target errors (error_rate {base['metrics']['error_rate']:.0%}); a baseline with errors "
                  "makes later comparisons lenient", file=sys.stderr)
        return 0
    if args.cmd == "gate":
        cfg = load_config(args.config)
        if not cfg.gate:
            raise ConfigError(f"{args.config} has no [gate] section: add rules such as [gate.min] pass_rate = 0.75")
        run_dir = Path(args.run) if args.run else latest_run(cfg.output_dir, cfg.name)
        baseline = load_baseline(baseline_path(cfg, Path(args.config).resolve(), args.baseline))
        outcome = evaluate_gate(run_dir, baseline, cfg.gate)
        print(f"gate: {run_dir.name}" + (f" vs baseline {baseline['run_id']}" if baseline else " (no baseline)"))
        for line in format_for_ci(outcome):
            print(line)
        print("GATE PASSED" if outcome.passed else f"GATE FAILED ({len(outcome.failures)} problem(s))")
        return 0 if outcome.passed else 1
    if args.cmd == "history":
        series = analyse(scan(Path(args.runs_dir), args.name, args.split))
        print(format_history(series))
        if args.html:
            Path(args.html).write_text(render_html(series), encoding="utf-8")
            print(f"\nwrote {args.html}")
        bad = [s for s in series if s["regression"] and s["regression"]["regressed"]]
        return 1 if args.fail_on_regression and bad else 0
    if args.cmd == "worker":
        from .worker import main as worker_main
        return worker_main()
    if args.cmd == "meta-eval":
        cfg = load_config(args.config)
        cases = load_cases(cfg.dataset)
        split = args.split or ("dev" if (cfg.split_dev_fraction is not None or any("split" in c.metadata for c in cases)) else "all")
        from .splits import record_heldout_look, select
        in_use = cfg.split_dev_fraction is not None or any("split" in c.metadata for c in cases)
        looks = record_heldout_look(cfg.output_dir, cfg.dataset, cfg.config_sha256, split, "meta-eval") \
            if in_use and split in ("heldout", "all") else 0
        try:
            rates = [float(x) for x in args.rates.split(",")] if args.rates else None
        except ValueError:
            raise ConfigError(f"--rates must be comma-separated numbers, got {args.rates!r}") from None
        if rates and any(not 0 < r <= 1 for r in rates):
            raise ConfigError("--rates values must be in (0, 1]")
        result = run_meta_eval(cfg, select(cases, split, cfg.split_dev_fraction, cfg.split_salt), args.min_drop,
                               args.alpha, args.repeats, sensitivity=(rates or list(DEFAULT_RATES)) if args.sensitivity else None,
                               auto=args.auto, max_mutants=args.max_mutants, seed=args.seed, allow_network=args.allow_network)
        result["split"] = split
        if looks:
            result["heldout_looks"] = looks
        print(format_meta_eval(result))
        if looks:
            print(f"held-out look #{looks} on this dataset version")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        too_many = args.max_survivors is not None and result["auto_survivors"] > args.max_survivors
        return 0 if result["ok"] and not too_many else 1
    if args.cmd == "judge-check":
        cfg = load_config(args.config)
        load_plugins(cfg)
        built = build_graders(cfg)
        if args.cache:
            from .graders import attach_judge_cache
            from .judges import JudgeCache
            attach_judge_cache(built, JudgeCache(Path(args.cache)))
        grader = find_judge_grader(built, args.grader)
        if getattr(grader, "network", None) is True:
            print("note: the judge is a hosted model; this sends the sampled cases' answers to it and may cost money",
                  file=sys.stderr)
        result = run_checks(load_cases(cfg.dataset), grader, args.sample, args.repeats, args.seed, args.max_calls)
        print(format_checks(result))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if result["ok"] else 1
    if args.cmd == "pairwise":
        registry.load_entry_points()
        registry.load_modules(args.plugin)
        opts = {}
        for item in args.judge_opt:
            if "=" not in item:
                raise ConfigError(f"--judge-opt expects KEY=VALUE, got {item!r}")
            key, raw = item.split("=", 1)
            try:
                val = json.loads(raw)
            except json.JSONDecodeError:
                val = raw
            opts[key] = val if isinstance(val, (bool, int, float)) else raw  # numbers and true/false; all else stays text
        judge = registry.get_judge(args.judge, **opts) if args.judge in registry.available()["judges"] else None
        if judge is None:
            raise ConfigError(f"unknown judge '{args.judge}'. Available: {', '.join(registry.available()['judges'])}")
        if getattr(judge, "network", None) is True:
            print("note: the judge is a hosted model; case inputs and both outputs are sent to it", file=sys.stderr)
        if args.cache:
            from .judges import CachingJudge, JudgeCache
            from .pairwise import PAIR_PROMPT_VERSION
            judge = CachingJudge(judge, JudgeCache(Path(args.cache)), PAIR_PROMPT_VERSION)
        res = compare_runs(Path(args.run_a), Path(args.run_b), judge, args.rubric, not args.single_order, args.seed,
                           args.max_calls)
        print(format_pairwise(res, Path(args.run_a).name, Path(args.run_b).name))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(res.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return 0
    if args.cmd == "calibrate":
        r = calibrate(Path(args.run_dir), args.grader)
        print(format_calibration(r))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0
    if args.cmd == "list":
        registry.load_entry_points()
        registry.load_modules(args.plugin)
        und = set(registry.undeclared())
        singular = {"targets": "target", "graders": "grader", "judges": "judge"}
        print(f"evalharness {__version__}, plugin API {registry.API_VERSION}")
        for kind, names in registry.available().items():
            print(f"{kind}: " + ", ".join(n + ("*" if (singular[kind], n) in und else "") for n in names))
        if und:
            print("* declares no plugin API version (set `evalharness_api = " + str(registry.API_VERSION) + "` on the class)")
        for what, why in registry.LOAD_ERRORS.items():
            print(f"could not load {what}: {why}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
