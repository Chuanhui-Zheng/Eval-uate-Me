"""Build a 100-case calculator dataset with numeric and tool-use coverage."""
import json
from pathlib import Path


OUT = Path(__file__).with_name("cases.jsonl")
CASES = [
    ("add", "+"), ("sub", "-"), ("mul", "*"), ("div", "/"),
]


def main() -> None:
    rows = [
        {"id": "add", "input": "2 + 3", "expected": 5, "metadata": {"tags": ["arithmetic"]}},
        {"id": "mul", "input": "12 * 3", "expected": 36, "metadata": {"tags": ["arithmetic"]}},
        {"id": "float", "input": "0.1 + 0.2", "expected": 0.3, "metadata": {"tags": ["arithmetic", "float"]}},
        {"id": "div-zero", "input": "1 / 0", "expected": "undefined", "metadata": {"tags": ["edge"]}},
        {"id": "unparseable", "input": "two plus three", "expected": 5, "metadata": {"tags": ["edge", "expected-to-error"]}},
    ]
    for n in range(6, 101):
        op = CASES[(n - 6) % len(CASES)][1]
        a = ((n * 7) % 97) - 48
        b = ((n * 11) % 31) - 15 or 1
        if op == "/":
            # Keep exact finite results for the numeric_close contract.
            a = b * ((n % 13) - 6)
        value = {"+": a + b, "-": a - b, "*": a * b, "/": a / b}[op]
        rows.append({"id": f"calc-{n:03}", "input": f"{a} {op} {b}", "expected": value,
                     "metadata": {"tags": ["arithmetic", "negative" if a < 0 or b < 0 else "positive"]}})
    OUT.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
    print(f"Wrote {len(rows)} cases to {OUT}")


if __name__ == "__main__":
    main()
