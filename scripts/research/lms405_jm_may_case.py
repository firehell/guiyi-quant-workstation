"""Frozen JM2609 May case: retrospective geometry, never signals or fills.

Input is the hash-bound, read-only MarketDataService export documented in
docs/research/lms405/evidence/JM2609_MAY_CASE.md. No data discovery or download.
"""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from guiyi_quant.lms405 import Bar
from lms405_alignment_audit import daytime_extrema
from lms405_node_audit import geometry

INPUT_HASH = "cedca0a8ce6ff61ac52f985749391abe79ff70661e43dd88adc955285b894874"
NODES = (
    ("watershed", "1223", "1228.5"),
    ("long-target-1", "1229", "1235"),
    ("long-target-2", "1241.5", "1248.5"),
    ("short-target-1", "1214.5", "1216"),
    ("short-target-2", "1206", "1210.5"),
    ("short-target-3", "1196.5", "1205.5"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUT_HASH:
        parser.error("FROZEN_MDS_EXPORT_HASH_MISMATCH")
    bars = []
    for row in csv.DictReader(raw.decode().splitlines()):
        b = Bar(
            row["contract"],
            datetime.fromisoformat(row["bar_end_shanghai"]),
            *(Decimal(row[k]) for k in ("open", "high", "low", "close")),
        )
        bars.append(SimpleNamespace(bar_end=b.end, high=b.high, low=b.low, close=b.close))
    published = datetime.fromisoformat("2026-05-20T17:24:00+08:00")
    # Calendar-day session only. Night bars are deliberately excluded from the
    # author's day-session high/low comparison; they remain in the input export.
    day_bars = [
        b for b in bars
        if b.bar_end.date() == date(2026, 5, 21)
        and "09:00" < b.bar_end.strftime("%H:%M") <= "15:00"
    ]
    report = {
        "identity": "lms405-jm2609-may-case-v1",
        "source_ids": ["G02", "G03", "G04", "G05", "G06", "F08"],
        "mode": "RETROSPECTIVE_GEOMETRY_ONLY",
        "input_snapshot_sha256": INPUT_HASH,
        "input_bar_count": len(bars),
        "source_period": "UNKNOWN",
        "historical_known_at_verified": False,
        "publication_proxy": published.isoformat(),
        "source_split": "development",
        "day_session_extrema": {
            d: daytime_extrema(bars, date.fromisoformat(d))
            for d in ("2026-05-20", "2026-05-21", "2026-05-22")
        },
        "nodes_may21_day_session": [
            dict(id=name, lower=lo, upper=hi,
                 **geometry(day_bars, published, Decimal(lo), Decimal(hi)))
            for name, lo, hi in NODES
        ],
        "author_position_transition": "CONSISTENT_WITH_BUT_NOT_IDENTIFIED",
        "same_account_verified": False,
        "missing_screenshot_leg_is_zero": False,
        "complete_action_cases": 0,
        "signal_comparison": None,
        "action_match_rate": None,
        "fill": None,
        "performance": None,
        "executable": False,
    }
    with args.output.open("x") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"status": report["mode"], "bars": len(bars)}))


if __name__ == "__main__":
    main()
