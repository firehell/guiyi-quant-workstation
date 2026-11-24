"""Recompute the plan handoff checks from archived source reviews."""

import argparse
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Position, timestamp
from guiyi_quant.lms405.handoff import Handoff, LOCK_ROUTES, VERSION, assess_handoff
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_replay import EVIDENCE, input_sources
from lms_near405_replay import encoded, sha


def report(path):
    raw = path.read_bytes()
    book = json.loads(raw)
    review_at = datetime.fromisoformat(book["review_at"])
    timestamp(review_at)
    catalog = {k: v["source_url"] for k, v in input_sources().items()}
    for name in ("jm-signal-followup-20261023.csv", "jm2601-original-records-20261023.csv"):
        with (EVIDENCE / "evidence" / name).open(newline="", encoding="utf-8") as stream:
            catalog.update((row["source_id"], row["url"]) for row in csv.DictReader(stream))
    cases = {}
    for row in book["cases"]:
        identity = row["id"]
        if identity in cases:
            raise ValueError("DUPLICATE_HANDOFF_CASE")
        sources = {key: catalog[key] for key in row["sources"]}
        route = row.get("route")
        case = dict(contract=row["contract"], sources=sources, historical_gap=row["gap"],
                    route=route, status="NO_ROUTE_IDENTIFIED", assessment=None, after=None)
        if route is not None:
            amount = Decimal(1 if route in LOCK_ROUTES else 0)
            before = Position(row["contract"], amount, amount)
            request = Handoff(route, before, row["original_side"], f"unit-plan:{identity}",
                              f"unit-cycle:{identity}", None if route == "RESUME_ORIGINAL"
                              else f"unit-next:{identity}", review_at, review_at)
            source = next(iter(sources.values()))
            facts = ()
            if "m_config_at_review" in row:
                facts = (Condition("M_CONFIG_PERMITS", request.scope, before.contract, row["m_config_at_review"],
                                   review_at, review_at, source, "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME"),)
            assessment = assess_handoff(request, facts, as_of=review_at + timedelta(microseconds=1), source=source,
                                        source_available_at=review_at, version_405=row["version_405"])
            case.update(status=assessment["status"], assessment=assessment, after=assessment["after"],
                        before=dict(long=str(before.long), short=str(before.short)),
                        before_kind="UNIT_HYPOTHESIS_NOT_AUTHOR_POSITION")
        cases[identity] = case
    return dict(version=VERSION, casebook_sha256=sha(raw), review_at=review_at.isoformat(),
                executable=False, admitted_author_samples=0, author_matches=None,
                fills=None, performance=None, cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casebook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = encoded(report(args.casebook))
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(data)
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()
