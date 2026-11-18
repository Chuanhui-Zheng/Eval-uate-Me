# Versioning and stability

From 1.0.0 eval_uate_me follows [semantic versioning](https://semver.org): **MAJOR** for a breaking change, **MINOR** for
backwards-compatible additions, **PATCH** for fixes. This page says what "breaking" means here.

## What is stable (the public surface)
A change to any of these that makes existing plugins, configs, scripts or saved files stop working is a major release.
`tests/test_public_api.py` snapshots most of this and fails when it changes, so a break cannot happen by accident.

1. **The Python API for plugins**: the names in `eval_uate_me.__all__` (`Case`, `TargetOutput`, `Score`, `CaseResult`, `Target`,
   `Grader`, `Judge`, `register_target`, `register_grader`, `register_judge`, `API_VERSION`, `ConfigError`, `PluginError`), the
   signatures of `Target.run`, `Grader.grade`, `Judge.complete` and the `register_*` decorators, and the fields of the
   dataclasses. New *optional* fields and methods may be added in a minor release; removing or renaming one is major.
2. **The plugin API version** (`eval_uate_me.API_VERSION`, currently 1). It changes only in a major release. A plugin declares the
   version it targets with `eval_uate_me_api = 1`.
3. **The command line**: command names, documented flags and exit codes. New commands and flags are minor.
4. **The config file**: the top-level and `[run]` keys and the shape of the `[target]`, `[[graders]]`, `[[mutants]]`,
   `[split]`, `[privacy]` and `[selftest]` tables. New optional keys are minor; unknown keys are rejected, so a config written for
   a newer minor release fails clearly on an older one.
5. **On-disk formats**: the line shape of `results.jsonl`, the keys of `summary.json`, `manifest.json` and `labels.jsonl`, the
   label sheet columns, and the dataset `.meta.toml` keys. These change only by *adding* keys. Every file eval_uate_me writes for a run
   carries `"format_version"` (currently 1); a reader accepts older files (no field counts as 0) and **refuses** a newer one with a
   message to upgrade, instead of misreading it. A change that removes, renames or re-types a key bumps the number, and the release
   notes then say how to migrate. Dataset rows may carry an optional `schema_version`, checked the same way.

## What is not covered (may change in a minor release)
- Human-readable console text and the layout of the HTML report and history page (parse the JSON files instead).
- The prompts sent to LLM judges (`llm_judge`, `pairwise`, `judge-check`) and the default thresholds of `selftest`, `judge-check`
  and `meta-eval`: improving them changes scores, and release notes will say so.
- Anything not documented, and every module other than the package root: `eval_uate_me.runner`, `eval_uate_me.stats` and the like are
  importable but private.

## Deprecation
A feature slated for removal is announced in the release notes, keeps working and prints a warning for at least one minor release,
and is removed only in the next major release.

## An honest caveat about 1.0
The number says *we intend to keep this surface stable*. It is not evidence that the surface is right: at 1.0 no outside user has
run eval_uate_me, and several parts have never met real conditions (no live language-model judge has been run, and the example agent's
own score is circular). If real use shows the plugin API needs reshaping, expect a 2.0 sooner than a mature project would need one.
