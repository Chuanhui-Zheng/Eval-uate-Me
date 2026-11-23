"""Expand authored ticket scenarios into a reproducible 100-case dataset."""
import json
from pathlib import Path


DATA = Path(__file__).parent / "data" / "cases.jsonl"


def main() -> None:
    base = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    rows = []
    for n in range(100):
        source = base[n % len(base)]
        row = json.loads(json.dumps(source))
        if n >= len(base):
            row["id"] = f"tt-{n + 1:03}"
            row["input"]["body"] += f" Ticket reference TT-{n + 1:03} is included for tracking."
        row.setdefault("metadata", {})["source_case"] = source["id"]
        rows.append(row)
    DATA.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
    print(f"Wrote {len(rows)} cases to {DATA}")


if __name__ == "__main__":
    main()
