"""Output-level mutation: systematic, deterministic damage to what a target returned, to find what the evaluation does not notice.

A mutant is an *operator* applied at a *path* of the output of the real target, to a fraction of the cases (`rate`):

    [[mutants]]
    name = "drops-a-finding-1-in-4"
    operator = "drop_item"            # see OPERATORS
    path = "findings"                 # dot path; [*] means every list element, e.g. findings[*].classification
    rate = 0.25                       # fraction of cases damaged (chosen by a hash of the case id, so reproducible)

Because it edits outputs that were already produced (the real target runs once, not once per mutant), hundreds of mutants cost
almost nothing and need no model calls. `evalharness meta-eval --auto` generates mutants for every field it finds in the real
outputs; a field whose every mutation survives is a field that no grader looks at.
"""
from __future__ import annotations

import copy
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import MUTATION_OPERATORS
from .models import Case, TargetOutput
from .splits import bucket
from .targets import Target

Location = tuple[Any, Any]  # (container, key): container[key] is the addressed value


def parse_path(path: str) -> list[tuple[str, int | str | None]]:
    """'findings[*].evidence.accession' -> [('findings', '*'), ('evidence', None), ('accession', None)]. '' is the whole output."""
    tokens: list[tuple[str, int | str | None]] = []
    for part in [p for p in path.split(".") if p] if path else []:
        m = re.fullmatch(r"([^\[\]]*)(?:\[(\*|\d+)\])?", part)
        if not m:
            raise ValueError(f"bad path segment {part!r} in {path!r}: use name, name[*] or name[0]")
        idx: int | str | None = None if m.group(2) is None else ("*" if m.group(2) == "*" else int(m.group(2)))
        tokens.append((m.group(1), idx))
    return tokens


def resolve(root: Any, path: str) -> list[Location]:
    """Every location the path addresses in `root` (wrapped in a holder so the root itself can be replaced)."""
    locs: list[Location] = [({"": root}, "")]
    for key, idx in parse_path(path):
        nxt: list[Location] = []
        for cont, k in locs:
            val = cont[k]
            if key:
                if not (isinstance(val, dict) and key in val):
                    continue
                cont, k, val = val, key, val[key]
            if idx is None:
                nxt.append((cont, k))
            elif isinstance(val, list):
                rng = range(len(val)) if idx == "*" else ([idx] if isinstance(idx, int) and idx < len(val) else [])
                nxt.extend((val, i) for i in rng)
        locs = nxt
    return locs


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _empty_like(v: Any) -> Any:
    return "" if isinstance(v, str) else [] if isinstance(v, list) else {} if isinstance(v, dict) else False if isinstance(v, bool) else 0


@dataclass
class OpContext:
    path: str
    params: dict[str, Any]
    donor: Any = None  # another case's output, for swap_value


def _set(cont: Any, k: Any, new: Any) -> bool:
    changed = cont[k] != new
    cont[k] = new
    return changed


def _op_drop_key(cont, k, ctx) -> bool:
    if isinstance(cont, dict) and k in cont and k != "":
        del cont[k]
        return True
    return False


def _op_drop_item(cont, k, ctx) -> bool:
    v = cont[k]
    if not isinstance(v, list) or not v:
        return False
    v.pop(-1 if ctx.params.get("which") == "last" else 0)
    return True


def _op_duplicate_item(cont, k, ctx) -> bool:
    v = cont[k]
    if not isinstance(v, list) or not v:
        return False
    v.insert(1, copy.deepcopy(v[0]))
    return True


def _op_reverse_list(cont, k, ctx) -> bool:
    v = cont[k]
    if not isinstance(v, list) or len(v) < 2 or v == v[::-1]:
        return False
    v.reverse()
    return True


def _op_empty_value(cont, k, ctx) -> bool:
    v = cont[k]
    new = _empty_like(v)
    return _set(cont, k, new) if (v != new or type(v) is not type(new)) else False


def _op_truncate_text(cont, k, ctx) -> bool:
    v = cont[k]
    return isinstance(v, str) and len(v) > 1 and _set(cont, k, v[: len(v) // 2])


def _op_replace_text(cont, k, ctx) -> bool:
    v = cont[k]
    if not isinstance(v, str) or "pattern" not in ctx.params:
        return False
    return _set(cont, k, re.sub(str(ctx.params["pattern"]), str(ctx.params.get("replacement", "")), v))


def _op_perturb_number(cont, k, ctx) -> bool:
    v = cont[k]
    if not _is_num(v):
        return False
    return _set(cont, k, v * float(ctx.params["factor"]) if "factor" in ctx.params else v + float(ctx.params.get("delta", 1)))


def _op_flip_bool(cont, k, ctx) -> bool:
    return isinstance(cont[k], bool) and _set(cont, k, not cont[k])


def _op_null_value(cont, k, ctx) -> bool:
    return cont[k] is not None and _set(cont, k, None)


def _op_swap_value(cont, k, ctx) -> bool:
    if ctx.donor is None:
        return False
    donors = [c[k2] for c, k2 in resolve(ctx.donor, ctx.path)]
    if not donors:
        return False
    return _set(cont, k, copy.deepcopy(donors[0])) if cont[k] != donors[0] else False


OPS: dict[str, Callable[[Any, Any, OpContext], bool]] = {
    "drop_key": _op_drop_key, "null_value": _op_null_value, "empty_value": _op_empty_value, "truncate_text": _op_truncate_text,
    "replace_text": _op_replace_text, "swap_value": _op_swap_value, "perturb_number": _op_perturb_number, "flip_bool": _op_flip_bool,
    "drop_item": _op_drop_item, "duplicate_item": _op_duplicate_item, "reverse_list": _op_reverse_list,
}
assert set(OPS) | {"empty_output"} == set(MUTATION_OPERATORS), "config.MUTATION_OPERATORS must list exactly the implemented operators"


def apply_operator(output: Any, operator: str, path: str, params: dict[str, Any], donor: Any = None) -> tuple[Any, bool]:
    """Return (mutated copy of output, whether anything changed). A path that does not exist in this output changes nothing."""
    if operator == "empty_output":
        return None, output is not None
    root = copy.deepcopy(output)
    locs = resolve(root, path)
    ctx = OpContext(path, params, donor)
    changed = False
    # deepest-first and last-index-first, so removing an element never shifts one we still have to visit
    for cont, k in reversed(locs):
        changed = OPS[operator](cont, k, ctx) or changed
    return (locs[0][0][""] if locs else root) if path == "" else root, changed


def selected(case_id: str, name: str, seed: int, rate: float) -> bool:
    """Deterministically damage about `rate` of the cases."""
    return rate >= 1.0 or bucket(case_id, f"{seed}:{name}") < rate


class MutatedTarget(Target):
    """Replays the real target's recorded outputs with one operator applied. The real target is not called again."""
    evalharness_api = 1
    network = False

    def __init__(self, replay: dict[str, TargetOutput], name: str, operator: str, path: str = "", rate: float = 1.0, seed: int = 0,
                 params: dict[str, Any] | None = None):
        self.replay, self.name, self.operator, self.path, self.rate, self.seed = replay, name, operator, path, rate, seed
        self.params = params or {}
        ok = sorted(c for c, o in replay.items() if o.error is None) or sorted(replay)  # donors must have a real output
        nxt = {c: ok[(i + 1) % len(ok)] for i, c in enumerate(ok)}
        self._next = {c: nxt.get(c, ok[0]) for c in replay}
        self.mutated: set[str] = set()  # ids of the cases that were really changed

    def run(self, case: Case) -> TargetOutput:
        base = self.replay[case.id]
        out = TargetOutput(output=base.output, trace=list(base.trace), usage=dict(base.usage), error=base.error)
        if base.error is not None or not selected(case.id, self.name, self.seed, self.rate):
            return out
        donor = self.replay[self._next[case.id]].output if self.operator == "swap_value" else None
        new, changed = apply_operator(base.output, self.operator, self.path, self.params, donor)
        if changed:
            self.mutated.add(case.id)
            out.output = new
        return out


# --- automatic mutant generation -----------------------------------------------------------------------------------------

@dataclass
class Site:
    path: str
    kind: str  # key | str | number | bool | list
    count: int = 0


def discover_sites(outputs: list[Any]) -> dict[str, Site]:
    """Every distinct field path found in the real outputs (list elements merged as [*]), with the kind of value seen there."""
    sites: dict[str, Site] = {}

    def add(path: str, kind: str) -> None:
        s = sites.setdefault(f"{path}\0{kind}", Site(path, kind))
        s.count += 1

    def walk(v: Any, path: str) -> None:
        if isinstance(v, dict):
            for k, child in v.items():
                p = f"{path}.{k}" if path else str(k)
                add(p, "key")
                walk(child, p)
        elif isinstance(v, list):
            add(path, "list")
            for child in v:
                walk(child, path + "[*]")
        elif isinstance(v, bool):
            add(path, "bool")
        elif _is_num(v):
            add(path, "number")
        elif isinstance(v, str):
            add(path, "str")

    for o in outputs:
        walk(o, "")
    return sites


_BY_KIND = {"key": ("drop_key", "null_value"), "str": ("empty_value", "truncate_text", "swap_value"),
            "number": ("perturb_number", "empty_value"), "bool": ("flip_bool",),
            "list": ("drop_item", "duplicate_item", "reverse_list", "empty_value")}


def generate_mutants(outputs: list[Any], max_mutants: int = 150, seed: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"name": "empty_output", "operator": "empty_output", "path": ""}]
    for site in sorted(discover_sites(outputs).values(), key=lambda s: (s.path, s.kind)):
        if not site.path:
            continue
        for op in _BY_KIND[site.kind]:
            out.append({"name": f"{op}:{site.path}", "operator": op, "path": site.path})
    seen, unique = set(), []
    for m in out:
        if m["name"] not in seen:
            seen.add(m["name"])
            unique.append(m)
    if len(unique) > max_mutants:
        unique = [unique[0]] + random.Random(seed).sample(unique[1:], max_mutants - 1)
        unique.sort(key=lambda m: (m["path"], m["operator"]))
    return unique
