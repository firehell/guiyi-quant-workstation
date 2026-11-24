"""Review archived participation cases alongside, separately from, market diagnostics."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Position, timestamp
from guiyi_quant.lms405.participation import VERSION, Participation, assess_participation
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_replay import input_sources
from lms_near405_replay import encoded, sha


def report(casebook, geometry):
    raw = casebook.read_bytes()
    book = json.loads(raw)
    raw_geometry = geometry.read_bytes()
    if sha(raw_geometry) != book["geometry_sha256"]:
        raise ValueError("GEOMETRY_SHA256_MISMATCH")
    geometry = json.loads(raw_geometry)["cases"]
    review = datetime.fromisoformat(book["review_at"])
    timestamp(review)
    catalog = input_sources()
    cases = {}
    for row in book["cases"]:
        case_id = row["id"]
        if case_id in cases:
            raise ValueError("DUPLICATE_PARTICIPATION_CASE")
        sources = {key: catalog[key]["source_url"] for key in row["sources"]}
        source = next(iter(sources.values()))
        before = row["position"]
        side = row["side"]
        if before not in ("FLAT", "DIRECTIONAL"):
            raise ValueError("UNSUPPORTED_CASE_POSITION")
        long = Decimal(int(before == "DIRECTIONAL" and side == "LONG"))
        short = Decimal(int(before == "DIRECTIONAL" and side == "SHORT"))
        request = Participation(Position(row["contract"], long, short), side, f"review-plan:{case_id}",
                                f"unit-position:{case_id}", review, review, source, row["version_405"])
        facts = ()
        if "right_policy_at_review" in row:
            facts = (Condition("RIGHT_POLICY_PERMITS", request.scope, row["contract"],
                               row["right_policy_at_review"], review, review, source,
                               "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME"),)
        market = None
        if market_key := row.get("geometry"):
            observation = geometry[market_key]
            if observation["contract"] != row["contract"] or not set(observation["sources"]) & set(sources):
                raise ValueError("GEOMETRY_CASE_SCOPE_MISMATCH")
            market = dict(case=market_key, role="OBSERVATION_ONLY_NO_AUTHOR_CONDITION",
                          status=observation["status"], window=observation.get("window"),
                          first_beyond=observation.get("first_beyond"),
                          first_shape=observation.get("first_shape_confirmation_after_price_setup"),
                          reference_reached=observation.get("first_reference_reached"),
                          monday_frames=observation.get("monday_frames"))
        assessment = assess_participation(request, facts, as_of=review + timedelta(microseconds=1))
        cases[case_id] = dict(sources=sources, note=row["note"], scenario_price=row.get("scenario_price"),
                              position=dict(long=str(long), short=str(short)), side=side,
                              position_kind="UNIT_HYPOTHESIS_NOT_AUTHOR_POSITION",
                              assessment=assessment, price_path_observation=market)
    return dict(version=VERSION, casebook_sha256=sha(raw), geometry_sha256=book["geometry_sha256"],
                cases=cases, admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casebook", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = encoded(report(args.casebook, args.geometry))
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(data)
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()
