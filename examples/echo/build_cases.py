"""Build a 100-case exact-match dataset for the echo target."""
import json
from pathlib import Path


OUT = Path(__file__).with_name("cases.jsonl")


def main() -> None:
    # Keep the deliberately wrong golden answer as a visible exact-match failure.
    rows = [
        {"id": "hello", "input": "hello", "expected": "hello"},
        {"id": "number", "input": 42, "expected": 42},
        {"id": "should-fail", "input": "a", "expected": "b"},
    ]
    for n in range(4, 101):
        value = [
            f"echo case {n:03}",
            n,
            round(n / 7, 6),
            {"request_id": f"ECHO-{n:03}", "payload": f"sample {n}"},
        ][(n - 4) % 4]
        rows.append({"id": f"echo-{n:03}", "input": value, "expected": value})
    OUT.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
    print(f"Wrote {len(rows)} cases to {OUT}")


if __name__ == "__main__":
    main()
