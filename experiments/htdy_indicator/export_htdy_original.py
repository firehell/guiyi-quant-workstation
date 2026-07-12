"""Export HTDY original observation-only PoC values from CSV or synthetic bars."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from htdy_original_core import compute_htdy_original, compute_synthetic, summarize


REQUIRED_COLUMNS = ("datetime", "open", "high", "low", "close", "volume")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="CSV with datetime,open,high,low,close,volume columns.")
    parser.add_argument("--output", type=Path, help="Output path. Defaults to stdout.")
    parser.add_argument("--format", choices=("csv", "json"), default="json")
    parser.add_argument("--synthetic-length", type=int, default=96)
    parser.add_argument("--ascii-field-names", action="store_true", help="Use ascii field names instead of original formula aliases.")
    args = parser.parse_args()

    result = _compute_from_input(args.input, synthetic_length=args.synthetic_length)
    payload = {
        "summary": summarize(result),
        **result.to_payload(original_names=not args.ascii_field_names),
    }
    if args.format == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        _write_text(args.output, text + "\n")
        return 0

    rows = payload["rows"]
    if not rows:
        _write_text(args.output, "")
        return 0
    text = _rows_to_csv(rows)
    _write_text(args.output, text)
    return 0


def _compute_from_input(input_path: Path | None, *, synthetic_length: int):
    if input_path is None:
        return compute_synthetic(synthetic_length)

    rows = _read_csv(input_path)
    return compute_htdy_original(
        [row["datetime"] for row in rows],
        [row["open"] for row in rows],
        [row["high"] for row in rows],
        [row["low"] for row in rows],
        [row["close"] for row in rows],
        [row["volume"] for row in rows],
    )


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        return [
            {
                "datetime": row["datetime"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for row in reader
        ]


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write_text(path: Path | None, text: str) -> None:
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
