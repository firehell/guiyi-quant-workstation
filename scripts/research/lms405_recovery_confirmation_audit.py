"""Compare fresh recovery signals, price returns and original-leg exits."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_counter_m_study import beyond
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_band_return_study import OCTOBER, OCTOBER_SHA
from lms405_protection_timeframes import PERIODS, VARIANTS, geometry_events, read_window
from lms405_replay import ohlc
from lms405_right_side_study import US, at
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

ORIGINAL = Path("output/lms405-original-leg-20261125/final.json")
ORIGINAL_SHA = "70e0c5ec10827cd6e3bd2cce561cd307fcc9c47b5c8fb937c2b65d7d1daed156"
JM_INDEX = Path("docs/research/lms405/evidence/jm2601-recovery-chain-20261023.csv")
CASES = (
    ("iron_afternoon", "I2701", "2026-10-27", "2026-10-27T11:35", "2026-10-27T15:00", "SHORT",
     "668.5 671.5", "A5358325549629506", "STRONG_SIDE_CONDITION_PROXY", "BOTH_LEGS_DISPLAYED"),
    ("sh_afternoon", "SH2701", "2026-10-27", "2026-10-27T11:35", "2026-10-27T15:00", "SHORT",
     "1511 1516", "A5358325972992140", "OLD_REBOUND_RESISTANCE_PROXY", "OLD_SHORT_DISPLAYED_LONG_UNKNOWN"),
    ("sh_after_extreme_m", "SH2609", "2026-07-27", "2026-07-27T09:00", "2026-07-27T15:00:00.000002", "SHORT",
     "1859 1870", "S5325329692361179", "SAME_DAY_REVIEW_ONLY", "AUTHOR_BLOCKED_ORIGINAL_SHORT_RECOVERY"),
    ("sh_next_day", "SH2609", "2026-07-28", "2026-07-27T21:00", "2026-07-28T15:00:00.000002", "SHORT",
     "1859 1870", "S5325329692361179", "PRIOR_BAND_APPLICABILITY_UNVERIFIED", "RECOVERY_NOT_REPORTED"),
    ("jm_reported_recovery", "JM2601", "2025-11-27", "2025-11-27T09:00", "2025-11-27T11:34", "SHORT",
     "1061 1072", "N03", "POST_SESSION_REVIEW_ONLY", "COMMODITY_UNLOCK_REPORTED_EXACT_LEG_UNKNOWN"),
    ("jm_waiting_then_counter_m", "JM2601", "2025-12-01", "2025-12-01T09:35", "2025-12-01T10:04", "SHORT",
     "1069 1077.5", "N02", "VISIBLE_NEAR_TRADE_TEXT_VERSION_UNVERIFIED", "COUNTER_DIRECTION_M_REPORTED"),
    ("ru_plan_day_review", "RU2609", "2026-08-12", "2026-08-12T09:00", "2026-08-12T15:00:00.000002", "LONG",
     "17065 17150", "A5331138280554800", "SAME_DAY_REVIEW_ONLY", "RECOVERY_NOT_REPORTED"),
    ("ru_post_plan", "RU2609", "2026-08-13", "2026-08-12T21:00", "2026-08-13T15:00:00.000002", "LONG",
     "17065 17150", "A5331138280554800", "RESISTANCE_BAND_STAND_ASSUMPTION", "RECOVERY_NOT_REPORTED"),
)


def strict_runs(minutes, edge, side):
    """Record active close runs, distinguishing a fresh crossing from starting beyond."""
    previous = crossing = None
    count = 0
    runs = {}
    for bar in minutes:
        continuous = previous is not None and bar.start == previous.end
        went_beyond = beyond(bar.close, edge, side)
        if not went_beyond or not continuous:
            crossing, count = None, 0
        if went_beyond:
            if continuous and not beyond(previous.close, edge, side):
                crossing = bar.end + US
            count += 1
            runs[bar.end] = dict(close_count=count, fresh_crossing_known_at=crossing)
        previous = bar
    return runs


def edge_candidates(minutes, events, edge, side):
    runs = strict_runs(minutes, edge, side)

    def fresh(event):
        run = runs.get(event["confirmed_at"])
        return (run is not None and run["fresh_crossing_known_at"] is not None
                and run["fresh_crossing_known_at"] < event["available_at"] and run["close_count"] >= 2)

    first_beyond = next((row for row in events if row["confirmed_at"] in runs), None)
    first_after = next((row for row in events if fresh(row)), None)
    return dict(
        edge=edge, first_close_beyond_at=next(iter(runs), None),
        first_fresh_cross_known_at=next((r["fresh_crossing_known_at"] for r in runs.values()
                                         if r["fresh_crossing_known_at"] is not None), None),
        first_shape_with_current_close_beyond=first_beyond,
        first_shape_after_fresh_cross_and_still_beyond=first_after,
        run_at_first_shape_beyond=None if first_beyond is None else runs[first_beyond["confirmed_at"]],
        fresh_run_at_shape=None if first_after is None else runs[first_after["confirmed_at"]],
    )


def examine(series, *, start, cut, side, band):
    minutes = [bar for bar in series[1] if bar.start >= start and bar.end + US < cut]
    if not minutes:
        raise ValueError("RECOVERY_WINDOW_HAS_NO_COMPLETED_MINUTES")
    near, far = band if side == "LONG" else band[::-1]
    groups = {}
    for shape, confirm in VARIANTS:
        events = geometry_events(series, shape, confirm, start=start, as_of=cut, side=side)
        groups[f"{shape}m_to_{confirm}m"] = dict(
            first_geometry=next(iter(events), None), geometry_count=len(events),
            near=edge_candidates(minutes, events, near, side),
            far=edge_candidates(minutes, events, far, side),
        )
    return dict(start=start, cutoff_exclusive=cut, minute_count=len(minutes), geometry=groups,
                first_minute_close=minutes[0].close,
                minute_price_progress=observations(minutes, band, side),
                extrema=dict(low=min(bar.low for bar in minutes), high=max(bar.high for bar in minutes)),
                market={f"{p}m": dict(bars=len(rows), sha256=sha(encoded(
                    [[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in rows]).encode()))
                        for p, rows in series.items()})


def study(session, market, original, lot_timing):
    from app.market_data.market_data_service import MarketDataError

    index = input_sources()
    with JM_INDEX.open(newline="", encoding="utf-8") as stream:
        jm_index = {row["source_id"]: row for row in csv.DictReader(stream)}
    jm_index_sha = sha(JM_INDEX.read_bytes())
    cases, missing = {}, {}
    for name, contract, day, start, cut, side, band, source_id, scope, description in CASES:
        try:
            series = read_window(session, market, contract, date.fromisoformat(day))
        except MarketDataError as exc:
            if exc.code != "DATASET_OR_PARTITION_MISSING":
                raise
            missing[name] = dict(contract=contract, trading_day=day, required_periods=PERIODS, code=exc.code)
            continue
        result = examine(series, start=at(start), cut=at(cut), side=side, band=tuple(map(Decimal, band.split())))
        if source_id in jm_index:
            source = dict(path=str(JM_INDEX), sha256=jm_index_sha) | jm_index[source_id]
        else:
            source = index[source_id] | dict(sha256=sha((ARCHIVE.parent / index[source_id]["archive_path"]).read_bytes()))
        observed_legs = None
        if name in ("iron_afternoon", "sh_afternoon"):
            minutes = [[b.end.isoformat(), *map(str, ohlc(b))] for b in series[1]]
            identity = dict(bars=len(minutes), ohlc_sha256=sha(json.dumps(minutes, separators=(",", ":")).encode()))
            if identity != lot_timing["cases"][contract]["market"]:
                raise ValueError("RECOVERY_SNAPSHOT_MARKET_CHANGED")
            earlier = original["cases"][contract]
            expected = earlier["afternoon"]
            if (result["start"] != datetime.fromisoformat(expected["start"])
                    or result["cutoff_exclusive"] != datetime.fromisoformat(expected["cutoff_exclusive"])
                    or result["extrema"] != {"low": Decimal(expected["minimum"]), "high": Decimal(expected["maximum"])}):
                raise ValueError("RECOVERY_SNAPSHOT_WINDOW_CHANGED")
            observed_legs = earlier["afternoon_comparison"]
        cases[name] = result | dict(
            contract=contract, trading_day=day, original_direction_hypothesis=side, plan_scope=scope,
            source_id=source_id, source=source, observation=description,
            observed_legs=observed_legs, original_exit_permission=None, author_signal_at=None, author_action_at=None,
        )
    return dict(version="lms405-recovery-confirmation-audit-v1", cases=cases, data_gaps=missing,
                original_leg_reference_sha256=ORIGINAL_SHA,
                lot_timing_reference_sha256=OCTOBER_SHA,
                evaluation="PRICE_AND_GEOMETRY_SENSITIVITY_ONLY", admitted_author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        original = verified_json(ORIGINAL, ORIGINAL_SHA)
        lot_timing = verified_json(OCTOBER, OCTOBER_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            value = study(session, build_market_data_service(session), original, lot_timing)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(value))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError):
        parser.exit(2, "RECOVERY_CONFIRMATION_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
