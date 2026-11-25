"""Recheck the JM2601 1072 report against overnight and morning recovery clocks."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_break_clock import check_prefixes
from lms405_jm_recovery_boundaries import ARTICLE_ENTRY_TIME, CONTRACT, read_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded

DAY = date(2025, 11, 27)
NIGHT, OPEN, NOON_POST = map(at, ("2025-11-26T21:00", "2025-11-27T09:00", "2025-11-27T11:34"))
EDGE, FAR = Decimal(1072), Decimal(1061)
REFERENCE = Path("output/lms405-jm-recovery-boundaries-20261125/verified.json")
REFERENCE_SHA = "748b658565e1eca6d0e7a46907e25a1d1c569103f555701bcbb0335d83267b03"
INDEX_HASHES = {"N03": "b622a66382a2846abd764d8aaeded1c6b722a7b3b68b5428183e1d547da25a66",
                "O01": "814b0378adb22d3ad3e9c34e265a01119e81163985d462524fc15c5a92dc05e8"}


def event_context(event, runs, *, published_minute_end):
    when = event["confirmed_at"]
    run = runs.get(when)
    first = when - (run["close_count"] - 1) * ONE if run else None
    return dict(
        active_below_run_start=first, active_below_close_count=run["close_count"] if run else 0,
        confirmed_in_current_run=first is not None,
        active_below_run_known_before_shape=first is not None and first + US < event["shape_start"],
        cited_article_entry_before_shape=published_minute_end < event["shape_start"],
    )


def window(series, *, start, cut, article_boundary):
    minutes = completed(series[1], start, cut)
    edges = {}
    for role, level in (("near_1072", EDGE), ("far_1061", FAR)):
        data = check_prefixes(series, side="SHORT", edge=level, start=start, cut=cut)
        runs = strict_runs(minutes, level, "SHORT")
        events = {}
        for period, gate in data["gates"].items():
            for variant, group in gate["groups"].items():
                for rule, event in group.items():
                    if not event:
                        continue
                    key = (variant, event["available_at"], event["shape_start"])
                    if key not in events:
                        # Gate-period-specific timestamps remain in the detailed groups.
                        shared = {field: value for field, value in event.items()
                                  if field not in ("first_gate_close", "gate_in_active_run")}
                        events[key] = shared | dict(variant=variant, first_for_comparisons=[],
                                                    **event_context(event, runs, published_minute_end=article_boundary))
                    events[key]["first_for_comparisons"].append([period, rule])
        ordered = sorted(events.values(), key=lambda row: (row["available_at"], row["variant"], row["shape_start"]))
        edges[role] = data | dict(
            first_strict_range_below=next((bar.end for bar in minutes if bar.low < level), None),
            opening_at_or_below=minutes[0].open <= level, context=ordered,
        )
    return dict(start=start, cutoff_exclusive=cut, bars=len(minutes), low=min(bar.low for bar in minutes), edges=edges)


def study(session, market):
    frozen = verified_json(REFERENCE, REFERENCE_SHA)["cases"]["november_27_reported_unlock"]
    old_indexes = read_sources()
    sources = {key: old_indexes[key] for key in INDEX_HASHES}
    if any(sources[key]["sha256"] != expected for key, expected in INDEX_HASHES.items()):
        raise ValueError("JM1072_INDEX_CHANGED")
    post = at(sources["O01"]["published_shanghai"].replace(" ", "T"))
    article_entry = at(ARTICLE_ENTRY_TIME)
    if not post == NOON_POST < article_entry:
        raise ValueError("JM1072_PUBLIC_CLOCK_CHANGED")
    series = read_window(session, market, CONTRACT, DAY)
    inputs = {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
    if {period: item["sha256"] for period, item in inputs.items()} != frozen["market"]:
        raise ValueError("JM1072_MARKET_CHANGED")
    windows = {}
    for name, start, cut in (("night", NIGHT, OPEN), ("morning", OPEN, NOON_POST), ("trading_day_prefix", NIGHT, NOON_POST)):
        windows[name] = window(series, start=start, cut=cut, article_boundary=article_entry + ONE)
    return dict(version="lms405-jm1072-public-clock-v1", contract=CONTRACT, trading_day=DAY, market=inputs,
                reference_sha256=REFERENCE_SHA, sources=sources, windows=windows,
                noon_report_displayed_at=NOON_POST, later_article_entry=article_entry,
                historical_plan_verified=False, earliest_attested_1072_source_before_noon=None,
                scope="RETROSPECTIVE_WITH_REPORTED_UNLOCK_NO_EXECUTION_ANCHOR", author_action_at=None,
                author_version_405=None, unshown_noon_long_quantity=None, author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("JM1072_") else "JM1072_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
