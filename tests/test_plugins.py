"""Tests: plugins."""
from helpers import *  # noqa: F401,F403


# ---- plugin API version ----


def test_api_version_is_exported_and_listed(capsys):
    import eval_uate_me
    assert eval_uate_me.API_VERSION == 1
    assert main(["list"]) == 0
    assert "plugin API 1" in capsys.readouterr().out


def test_incompatible_plugin_api_is_refused_with_both_versions(tmp_path, monkeypatch, capsys):
    from eval_uate_me import PluginError, registry
    with pytest.raises(PluginError, match="plugin API 2, but this is eval_uate_me plugin API 1"):
        @register_target("future_target")
        class Future(Target):
            eval_uate_me_api = 2

            def run(self, case):
                ...
    assert "future_target" not in registry.available()["targets"]
    mod = _plugin_module(tmp_path, monkeypatch, "future_plugin_mod", (
        '@register_target("future_via_config")\n'
        'class T(Target):\n'
        '    eval_uate_me_api = 7\n'
        '    def run(self, case):\n'
        '        return TargetOutput(output="x")\n'))
    f = _plugin_cfg(tmp_path, mod, "future_via_config")
    assert main(["check", str(f)]) == 2
    assert "plugin API 7" in capsys.readouterr().err


def test_undeclared_plugins_work_but_are_flagged(tmp_path, monkeypatch, capsys):
    mod = _plugin_module(tmp_path, monkeypatch, "undeclared_plugin_mod", (
        '@register_target("undeclared_t")\n'
        'class T(Target):\n'
        '    def run(self, case):\n'
        '        return TargetOutput(output=case.input)\n'
        '@register_target("declared_t")\n'
        'class D(Target):\n'
        '    eval_uate_me_api = 1\n'
        '    def run(self, case):\n'
        '        return TargetOutput(output=case.input)\n'))
    assert main(["check", str(_plugin_cfg(tmp_path, mod, "undeclared_t"))]) == 0
    assert "note: target 'undeclared_t' declares no plugin API version" in capsys.readouterr().err
    assert main(["check", str(_plugin_cfg(tmp_path, mod, "declared_t"))]) == 0
    assert "declares no plugin API version" not in capsys.readouterr().err
    assert main(["list", "--plugin", mod]) == 0
    out = capsys.readouterr().out
    targets_line = next(l for l in out.splitlines() if l.startswith("targets:"))
    assert "undeclared_t*" in targets_line and "declared_t*" not in targets_line.replace("undeclared_t*", "")
    assert "declares no plugin API version" in out
    assert run(load_config(_plugin_cfg(tmp_path, mod, "undeclared_t")))[0][0].passed


def test_plugin_import_problems_are_readable(tmp_path, monkeypatch, capsys):
    f = _plugin_cfg(tmp_path, "no_such_plugin_module", "echo")
    assert main(["check", str(f)]) == 2
    assert "plugin module 'no_such_plugin_module' could not be imported" in capsys.readouterr().err
    mod = _plugin_module(tmp_path, monkeypatch, "exploding_plugin_mod", "raise RuntimeError('bad init')\n")
    assert main(["check", str(_plugin_cfg(tmp_path, mod, "echo"))]) == 2
    assert "failed while loading: RuntimeError: bad init" in capsys.readouterr().err


def test_a_broken_entry_point_is_recorded_not_fatal(tmp_path, monkeypatch, capsys):
    from eval_uate_me import registry

    class BrokenEntry:
        name = "broken_ep_target"

        def load(self):
            raise ImportError("missing dependency xyz")

    monkeypatch.setattr(registry, "entry_points", lambda group: [BrokenEntry()] if group == "eval_uate_me.targets" else [])
    registry.LOAD_ERRORS.clear()
    registry.load_entry_points()                                         # must not raise
    assert registry.LOAD_ERRORS == {"target 'broken_ep_target'": "ImportError: missing dependency xyz"}
    assert main(["list"]) == 0
    assert "could not load target 'broken_ep_target': ImportError: missing dependency xyz" in capsys.readouterr().out
    f = tmp_path / "e.toml"
    (tmp_path / "c.jsonl").write_text('{"id":"1","input":"a","expected":"a"}')
    f.write_text('dataset = "c.jsonl"\n[target]\ntype = "broken_ep_target"\n[[graders]]\ntype = "exact_match"\n')
    assert main(["check", str(f)]) == 2
    assert "The plugin that provides it failed to load: ImportError: missing dependency xyz" in capsys.readouterr().err
    registry.LOAD_ERRORS.clear()


def test_scaffolded_plugin_declares_the_api(tmp_path, monkeypatch, capsys):
    assert main(["init-plugin", "api_scaffold", "--dir", str(tmp_path)]) == 0
    root = tmp_path / "eval_uate_me-api-scaffold"
    assert "eval_uate_me_api = 1" in (root / "api_scaffold" / "__init__.py").read_text()
    monkeypatch.syspath_prepend(str(root))
    capsys.readouterr()
    assert main(["check", str(root / "eval.toml")]) == 0
    assert "declares no plugin API version" not in capsys.readouterr().err
