"""Audit same-segment ordered recovery against the JM2609 May position displays."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm_may_leg_timing import CONTRACT, INPUT_HASH, MAY_INDEX, MAY_INDEX_HASH, frozen_minutes
from lms405_jm_may_short_continuity import AFTERNOON_START, CLOSE, LUNCH, SESSION_START
from lms405_ordered_original_short import observe
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest
from lms405_trial_to_trend import frozen
from lms_near405_replay import encoded

RETENTION_REPORT = Path("output/lms405-jm-may-short-continuity-20261125/position-report.json")
RETENTION_SHA = "9f3d19fdff44c2a4177ebbf30c0f297cf24e8d92b49e204831def7956e604a91"
LEVELS = (
    ("watershed_then_first_target_near", ("1223", "1228.5"), "1214.5"),
    ("first_target_then_second_target_near", ("1214.5", "1216"), "1210.5"),
    ("first_target_then_second_target_far", ("1214.5", "1216"), "1206"),
    ("second_target_then_third_target_near", ("1206", "1210.5"), "1205.5"),
)


def overlapping_breaks(renewed_trigger):
    """Expose trigger bars rejected because their start predates known pressure."""
    return [
        dict(variant=branch["variant"], pressure_at=branch["pressure_at"], trigger_at=row["at"],
             price=row["close"])
        for branch in renewed_trigger["branches"] for row in renewed_trigger["fresh_crosses"]
        if row["at"] + US < branch["expires_before"]
        and branch["pressure_at"] <= row["at"]
        and row["at"] - ONE <= branch["pressure_at"] + US
    ]


def study(session, market, month_minutes):
    observations = verified_json(RETENTION_REPORT, RETENTION_SHA)
    source_rows = {row["id"]: row for row in csv.DictReader(frozen(MAY_INDEX, MAY_INDEX_HASH).decode().splitlines())}
    sources = {key: source_rows[key] for key in ("G02", "G03", "G04", "G07")}
    plan, lunch, close, recap = (datetime.fromisoformat(row["published_at"]) for row in sources.values())
    if not plan < SESSION_START < LUNCH < lunch < AFTERNOON_START < CLOSE < close < recap:
        raise ValueError("JM_MAY_RESET_SOURCE_ORDER_CHANGED")
    series = read_window(session, market, CONTRACT, date(2026, 5, 21))
    reference = [b for b in frozen_minutes(month_minutes) if SESSION_START < b.end <= CLOSE]
    if [(b.start, b.end, ohlc(b)) for b in series[1]] != [(b.start, b.end, ohlc(b)) for b in reference]:
        raise ValueError("JM_MAY_RESET_MDS_INPUT_CHANGED")
    scopes = (
        ("trading_night", SESSION_START, at("2026-05-21T09:00")),
        ("through_lunch", at("2026-05-21T09:00"), LUNCH + 2 * US),
        ("afternoon", AFTERNOON_START, CLOSE + 2 * US),
    )
    outcome = {}
    for role, raw_band, raw_trigger in LEVELS:
        band, trigger = tuple(map(Decimal, raw_band)), Decimal(raw_trigger)
        windows = observe(series, scopes, band, trigger)
        for window in windows.values():
            window["renewed_trigger"]["overlapping_breaks"] = overlapping_breaks(window["renewed_trigger"])
        outcome[role] = dict(pressure_band=band, trigger=trigger, windows=windows)
    return dict(
        version="lms405-jm-may-recovery-reset-v1", contract=CONTRACT, trading_day="2026-05-21",
        scope="RETROSPECTIVE_SENSITIVITY_AUTHOR_TARGETS_ARE_NOT_RECOVERY_GATE",
        plan_sources=sources, plan_index_sha256=MAY_INDEX_HASH, frozen_minute_export_sha256=INPUT_HASH,
        author_strategy_version="4.0.5", author_signal_at=None, actual_author_action_at=None,
        historical_plan_verified=False, screenshot_account_continuity=None, unshown_close_long_quantity=None,
        retention_reference_sha256=RETENTION_SHA, conditional_short_retention=observations["same_table_retention"],
        conditional_replacement_after_level=observations["conditional_replacement_after_level"],
        market={str(p): dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()},
        hypotheses=outcome, author_action_samples=0, author_match_rate=None, fills=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--frozen-minutes", type=Path, required=True)
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), args.frozen_minutes)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "JM_MAY_RESET_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
