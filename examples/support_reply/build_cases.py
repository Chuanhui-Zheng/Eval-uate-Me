"""Expand the authored support scenarios into a reproducible 100-case set."""
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
            row["id"] = f"sr-{n + 1:03}"
            row["input"]["subject"] = f"{row['input']['subject']} (request SR-{n + 1:03})"
            row["input"]["body"] += f" Please use reference SR-{n + 1:03} when replying."
        row.setdefault("metadata", {})["source_case"] = source["id"]
        rows.append(row)
    DATA.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
    print(f"Wrote {len(rows)} cases to {DATA}")


if __name__ == "__main__":
    main()
