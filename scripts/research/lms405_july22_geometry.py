"""Frozen JM2509 chart-alignment hypothesis, NOT an author signal algorithm."""

import argparse
import csv
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path


INPUT_SHA256 = "71c668cc3874cfdcb1c52b47c26615a89ed455977bfb5c80883a9e18b3cb91b3"
SOURCE_URL = "https://weibo.com/1885745060/PCeX7pZ6t"


def audit(path: Path) -> dict:
    if hashlib.sha256(path.read_bytes()).hexdigest() != INPUT_SHA256:
        raise ValueError("FROZEN_INPUT_HASH_MISMATCH")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_time = {row["bar_end_shanghai"]: row for row in rows}
    times = [f"2025-07-22T09:{minute:02d}:00+08:00" for minute in (5, 10, 15, 20, 25)]
    selected = [by_time[t] for t in times]
    first, inside, breakdown = selected[:3]
    d = Decimal
    publication = datetime.fromisoformat("2025-07-22T09:25:00+08:00")
    peak = by_time["2025-07-21T23:00:00+08:00"]
    return {
        "study": "JM2509_JULY22_ALIGNMENT_HYPOTHESIS_V1",
        "input_sha256": INPUT_SHA256,
        "bar_count": len(rows),
        "source_url": SOURCE_URL,
        "source_period": "5m explicitly stated in source text",
        "source_bar_time": None,
        "version_405_confirmed_for_this_chart": False,
        "alignment": "PROVISIONAL_VISUAL_SEQUENCE_ONLY",
        "original_ibar_formula_identified": False,
        "original_bbb_formula_identified": False,
        "author_ohlc_per_bar": None,
        "author_signal_prediction": None,
        "eligible_golden_signal_samples": 0,
        "execution": None,
        "return": None,
        "development_evidence": True,
        "bars": [
            {
                "bar_end_shanghai": row["bar_end_shanghai"],
                **{k: str(d(row[k]).normalize()) for k in ("open", "high", "low", "close")},
                "bar_end_strictly_before_displayed_publication": (
                    datetime.fromisoformat(row["bar_end_shanghai"]) < publication
                ),
            }
            for row in selected
        ],
        "local_geometry_only": {
            "0910_strict_inside_0905": (
                d(inside["high"]) < d(first["high"])
                and d(inside["low"]) > d(first["low"])
            ),
            "0915_low_below_0910_low": d(breakdown["low"]) < d(inside["low"]),
            "0915_close_below_0910_low": d(breakdown["close"]) < d(inside["low"]),
            "hypothetical_level": str(d(inside["low"]).normalize()),
            "intrabar_cross_time": None,
        },
        "provisional_peak_comparison": {
            "local_bar_end": peak["bar_end_shanghai"],
            "local_high": str(d(peak["high"]).normalize()),
            "source_image_high_label": "1034.5",
            "local_minus_image": str(d(peak["high"]) - d("1034.5")),
            "alignment_confirmed": False,
        },
        "limitations": [
            "No source time axis or individual OHLC; no unique alignment proof",
            "Public VPLUS is a simplified BBB relative, not identical",
            "Publication time does not prove historical content immutability",
            "No inferred fill from average position price",
            "09:25 bar completion relative to same-minute post is unknown",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.input)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
