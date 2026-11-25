"""Compare near-edge, prior target reach, and current far-edge recovery hypotheses."""

import argparse
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import JM_INDEX, strict_runs
from lms405_right_side_study import US, at
from lms_near405_replay import encoded, sha

JM_ORIGINAL_INDEX = JM_INDEX.with_name("jm2601-original-records-20261023.csv")
CASES = (
    ("pvc_not_unlocked", "V2609", "2026-04-27", "session_start", "15:01", "LONG", "5226 5262",
     "S5292358960155373", "PREVIOUS_STRONG_TARGET", "AUTHOR_405_REPORTED_LONG_UNLOCK_NOT_TAKEN"),
    ("pvc_target_completed", "V2609", "2026-04-28", "session_start", "15:01", "LONG", "5226 5262",
     "S5292720017903146", "FIRST_STRONG_TARGET", "TARGET_COMPLETED_ACTION_UNKNOWN"),
    ("caustic_soda_afternoon", "SH2701", "2026-10-27", "11:35", "15:00", "SHORT", "1511 1516",
     "A5358325972992140", "OLD_RESISTANCE_RECOVERY_PROXY", "CLOSE_SNAPSHOT_LONG_LEG_NOT_DISPLAYED"),
    ("coal_morning", "JM2601", "2025-11-27", "09:00", "11:34", "SHORT", "1061 1072",
     "N03", "AUTHOR_DISCLOSED_NEAR_EDGE_FOR_EARLY_REENGAGEMENT", "AUTHOR_REPORTED_UNLOCK_VERSION_UNKNOWN"),
)


def evaluate(series, *, start, cut, side, band):
    minutes = [bar for bar in series[1] if bar.start >= start and bar.end + US < cut]
    near, far = band if side == "LONG" else band[::-1]
    near_runs = strict_runs(minutes, near, side)
    far_runs = strict_runs(minutes, far, side)
    reached = next((bar.end + US for bar in minutes
                    if (bar.high >= far if side == "LONG" else bar.low <= far)), None)
    events = []
    for shape, confirm in VARIANTS:
        rows = geometry_events(series, shape, confirm, start=start, as_of=cut, side=side)
        for event in rows:
            end = event["confirmed_at"]
            near_run, far_run = near_runs.get(end), far_runs.get(end)
            modes = []
            for name, run in (("NEAR", near_run), ("FAR", far_run)):
                if (run and run["close_count"] >= 2 and run["fresh_crossing_known_at"] is not None
                        and run["fresh_crossing_known_at"] < event["available_at"]):
                    modes.append(name)
            if "NEAR" in modes and reached is not None and reached < event["available_at"]:
                modes.append("NEAR_AFTER_PRIOR_FAR_REACH")
            if modes:
                events.append(event | dict(shape_minutes=shape, confirm_minutes=confirm, modes=modes))
    events.sort(key=lambda event: (event["available_at"], event["shape_minutes"], event["confirm_minutes"]))
    return dict(first_far_reach_known_at=reached, candidates=events, minute_count=len(minutes))


def study(session, market):
    index = input_sources()
    with JM_INDEX.open(newline="", encoding="utf-8") as stream:
        (jm_source,) = [row for row in csv.DictReader(stream) if row["source_id"] == "N03"]
    with JM_ORIGINAL_INDEX.open(newline="", encoding="utf-8") as stream:
        (jm_noon,) = [row for row in csv.DictReader(stream) if row["source_id"] == "O01"]
    source_fingerprint = sha(JM_INDEX.read_bytes())
    cases = {}
    for name, contract, day, lower, upper, side, raw_band, source_id, role, observation in CASES:
        series = read_window(session, market, contract, date.fromisoformat(day))
        start = series[1][0].start if lower == "session_start" else at(f"{day}T{lower}")
        cut = at(f"{day}T{upper}")
        band = tuple(map(Decimal, raw_band.split()))
        args = dict(start=start, side=side, band=band)
        result = evaluate(series, cut=cut, **args)
        checkpoints = {event["available_at"] for event in result["candidates"]}
        if result["first_far_reach_known_at"] is not None:
            checkpoints.add(result["first_far_reach_known_at"])
        cuts = checkpoints | {instant + US for instant in checkpoints}
        for stop in sorted(cuts):
            prefix = {p: [bar for bar in rows if bar.end + US < stop] for p, rows in series.items()}
            earlier = evaluate(prefix, cut=stop, **args)
            expected = [event for event in result["candidates"] if event["available_at"] < stop]
            reached = result["first_far_reach_known_at"]
            if earlier["candidates"] != expected or earlier["first_far_reach_known_at"] != (
                reached if reached is not None and reached < stop else None
            ):
                raise ValueError("UNLOCK_BOUNDARY_PREFIX_DIVERGED")
        source = (jm_source | dict(archive_path=str(JM_INDEX), archive_sha256=source_fingerprint)
                  if source_id == "N03" else load_source(index, source_id))
        market_input = {f"{period}m": dict(count=len(bars), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in bars
        ]).encode())) for period, bars in series.items()}
        cases[name] = result | dict(
            contract=contract, trading_day=day, source=source, side=side, band=band,
            band_role=role, observation=observation, start=start, cutoff_exclusive=cut,
            checked_prefixes=len(cuts), market_input=market_input, author_actual_action_time=None,
        )
        if name == "caustic_soda_afternoon":
            cases[name]["position_sources"] = {key: load_source(index, key) for key in ("WRoAkcEppg", "U03")}
        if name == "coal_morning":
            if at(jm_noon["published_shanghai"].replace(" ", "T")) != cut:
                raise ValueError("UNLOCK_BOUNDARY_REPORT_TIME_CHANGED")
            cases[name]["report_source"] = jm_noon | dict(
                archive_path=str(JM_ORIGINAL_INDEX), archive_sha256=sha(JM_ORIGINAL_INDEX.read_bytes()),
            )
    return dict(
        version="lms405-unlock-boundary-comparison-v1", cases=cases,
        evaluation="RETROSPECTIVE_PRICE_AND_GEOMETRY_ONLY", edge_run_period_minutes=1,
        admitted_author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "UNLOCK_BOUNDARY_INPUT_OR_PREFIX_UNVERIFIED\n")


if __name__ == "__main__":
    main()
