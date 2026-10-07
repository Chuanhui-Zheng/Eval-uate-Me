"""Guards against test habits that make a suite lie.

While this project was built, assertions like `assert x == y or True` were written more than once: they can never fail, so they
verify nothing. This test scans every test file for them, so the mistake cannot come back unnoticed.
"""
import re
from pathlib import Path

ROOTS = [Path(__file__).parent, Path(__file__).parent.parent / "examples"]
NEVER_FAILS = [
    (re.compile(r"\bor True\b"), "`... or True` can never fail"),
    (re.compile(r"^\s*assert True\b"), "`assert True` verifies nothing"),
    (re.compile(r"\band False\b"), "`... and False` can never pass"),
]


def test_no_assertion_that_can_never_fail():
    offenders = []
    for root in ROOTS:
        for path in root.rglob("test_*.py"):
            if path.name == "test_hygiene.py":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for pattern, why in NEVER_FAILS:
                    if pattern.search(line):
                        offenders.append(f"{path.relative_to(Path(__file__).parent.parent)}:{n}: {why}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_the_guard_itself_catches_the_pattern():
    assert NEVER_FAILS[0][0].search("    assert main() == 0 or True")
    assert NEVER_FAILS[1][0].search("    assert True")
    assert not NEVER_FAILS[0][0].search("    assert result == 'orange'")
