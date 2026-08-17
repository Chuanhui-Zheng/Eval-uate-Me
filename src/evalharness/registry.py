"""Plugin registry. Plugins register targets/graders by name.

Plugins are discovered three ways:
  1. built-ins (imported by this package)
  2. entry points in groups `evalharness.targets` / `evalharness.graders`
  3. modules listed under `plugins = [...]` in the config (imported, and
     expected to call register_target / register_grader at import time)
"""
from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Callable

from .config import PluginError

# The plugin API version: the contract between evalharness and plugins (Target.run, Grader.grade, Judge.complete,
# the dataclasses in models, and the register_* decorators). It changes only on a breaking change, which is a major
# release. A plugin declares the version it was written for with a class attribute `evalharness_api = 1`.
API_VERSION = 1

_TARGETS: dict[str, Callable] = {}
_GRADERS: dict[str, Callable] = {}
_JUDGES: dict[str, Callable] = {}
_UNDECLARED: set[tuple[str, str]] = set()   # (kind, name) of third-party plugins that declare no API version
LOAD_ERRORS: dict[str, str] = {}            # entry-point name -> why it could not be loaded


def _check_api(kind: str, name: str, factory) -> None:
    declared = getattr(factory, "evalharness_api", None)
    if declared is None:
        if not str(getattr(factory, "__module__", "")).startswith("evalharness."):  # built-ins need no declaration
            _UNDECLARED.add((kind, name))
        return
    if declared != API_VERSION:
        raise PluginError(f"{kind} '{name}' was written for evalharness plugin API {declared}, but this is evalharness "
                          f"plugin API {API_VERSION}: install a matching version of the plugin or of evalharness")


def register_target(name: str):
    def deco(factory):
        _check_api("target", name, factory)
        _TARGETS[name] = factory
        return factory
    return deco


def register_grader(name: str):
    def deco(factory):
        _check_api("grader", name, factory)
        _GRADERS[name] = factory
        return factory
    return deco


def register_judge(name: str):
    def deco(factory):
        _check_api("judge", name, factory)
        _JUDGES[name] = factory
        return factory
    return deco


def load_entry_points() -> None:
    """Load plugins registered through entry points. A broken plugin is recorded and skipped, not fatal: it only matters
    if the config asks for something it provides (the error then says why it is missing)."""
    for kind, group, table in (("target", "evalharness.targets", _TARGETS), ("grader", "evalharness.graders", _GRADERS),
                               ("judge", "evalharness.judges", _JUDGES)):
        for ep in entry_points(group=group):
            if ep.name in table:
                continue
            try:
                factory = ep.load()
                _check_api(kind, ep.name, factory)
                table[ep.name] = factory
            except Exception as e:  # noqa: BLE001
                LOAD_ERRORS[f"{kind} '{ep.name}'"] = f"{type(e).__name__}: {e}"


def load_modules(modules: list[str]) -> None:
    for m in modules:
        try:
            importlib.import_module(m)
        except PluginError:
            raise
        except ImportError as e:
            raise PluginError(f"plugin module '{m}' could not be imported ({e}): is it installed, or on PYTHONPATH?") from e
        except Exception as e:  # noqa: BLE001
            raise PluginError(f"plugin module '{m}' failed while loading: {type(e).__name__}: {e}") from e


def undeclared() -> list[tuple[str, str]]:
    return sorted(_UNDECLARED)


def _missing(kind: str, name: str, table: dict) -> str:
    why = LOAD_ERRORS.get(f"{kind} '{name}'")
    return (f"unknown {kind} '{name}'. available: {sorted(table)}"
            + (f". The plugin that provides it failed to load: {why}" if why else ""))


def get_target(name: str, /, **options):
    if name not in _TARGETS:
        raise KeyError(_missing("target", name, _TARGETS))
    return _TARGETS[name](**options)


def get_grader(name: str, /, **options):
    if name not in _GRADERS:
        raise KeyError(_missing("grader", name, _GRADERS))
    return _GRADERS[name](**options)


def get_judge(name: str, /, **options):
    if name not in _JUDGES:
        raise KeyError(_missing("judge", name, _JUDGES))
    return _JUDGES[name](**options)


def get(kind: str, name: str, /, **options):
    return factory(kind, name)(**options)


def factory(kind: str, name: str):
    return {"target": _TARGETS, "grader": _GRADERS, "judge": _JUDGES}[kind][name]


def available() -> dict[str, list[str]]:
    return {"targets": sorted(_TARGETS), "graders": sorted(_GRADERS), "judges": sorted(_JUDGES)}
