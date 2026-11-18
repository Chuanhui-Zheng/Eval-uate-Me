"""Worker process: build one target from a spec, run one case, print one result line.

Used by process (and docker) isolation. Reads a JSON request on stdin:
    {"plugins": [...], "target": {"type": ..., ...}, "case": {...}}
and writes the result as a line starting with SENTINEL on the real stdout. Anything the target prints goes to stderr,
so it cannot corrupt the result.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict

SENTINEL = "\x00EVALHARNESS-RESULT\x00"


def main() -> int:
    from . import judges, registry  # noqa: F401  (judges: registers built-ins)
    from .models import Case, TargetOutput

    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # plugin prints must not reach the result channel
    req = json.loads(sys.stdin.read())
    try:
        registry.load_entry_points()
        registry.load_modules(req.get("plugins", []))
        spec = dict(req["target"])
        target = registry.get_target(spec.pop("type"), **spec)
        out = target.run(Case(**req["case"]))
    except Exception as e:  # a failing target is an error result, not a crashed worker
        out = TargetOutput(error=f"{type(e).__name__}: {e}")
    real_stdout.write(SENTINEL + json.dumps(asdict(out), ensure_ascii=False, default=str) + "\n")
    real_stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
