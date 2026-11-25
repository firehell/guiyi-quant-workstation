"""Separate OI2609 target progress, protection searches and reported 4.0.5 actions."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded

CONTRACT = "OI2609"
VERSION = "lms405-oi-target-protection-v1"
MAY_DAYS = ("2026-05-22", "2026-05-25", "2026-05-26", "2026-05-27")
JULY_DAYS = ("2026-07-17", "2026-07-20", "2026-07-23", "2026-07-24")
MAY_TARGETS = ((Decimal(9697), Decimal(9708)), (Decimal(9672), Decimal(9681)))
JULY_PROTECTION = (Decimal(9992), Decimal(10004))
JULY_TARGET = (Decimal(10151), Decimal(10231))
MAY_SHORT, MAY_LOCK = "S5301416650348072", "S5303228212185872"
JULY_PLAN, JULY_RECAP = "S5321717736278116", "S5324242473192979"
SOURCES = {MAY_SHORT: MAY_DAYS[0], MAY_LOCK: MAY_DAYS[-1], JULY_PLAN: JULY_DAYS[0], JULY_RECAP: JULY_DAYS[-1]}


def day_readback(series, day):
    bars = series[1]
    close = at(f"{day}T15:00")
    if bars[-1].end != close or bars[0].start >= close:
        raise ValueError("OI_SOURCE_TRADE_DAY_CLOCK_CHANGED")
    return dict(open=bars[0].open, low=min(b.low for b in bars), high=max(b.high for b in bars), close=bars[-1].close,
                start=bars[0].start, end=close,
                fingerprints={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()})


def may_context(series, day, source_available_at):
    info = day_readback(series, day)
    is_initial = day == MAY_DAYS[0]
    if (is_initial and info["end"] >= source_available_at) or (not is_initial and source_available_at >= info["start"]):
        raise ValueError("OI_MAY_SOURCE_CLOCK_CHANGED")
    return info | dict(
        bands=[dict(band=band, observation=observations(series[1], band, "SHORT")) for band in MAY_TARGETS],
        purpose="REPORTED_SHORT_TARGET_COMPLETION" if is_initial else "PAST_SHORT_TARGETS_FOR_PRICE_COMPARISON_ONLY",
        active_protection_band=None, historical_same_position=None, author_action_at=None,
    )


def signal_context(event, band, first_overlap_known_at, source_available_at):
    low, high = band
    price = event["close"]
    return event | dict(
        in_reported_band=low <= price <= high,
        prior_overlap_known=first_overlap_known_at is not None and first_overlap_known_at < event["available_at"],
        direction_side_of_band="ABOVE" if price > high else "BELOW" if price < low else "INSIDE",
        report_known_before_shape=source_available_at < event["shape_start"],
    )


def july_context(series, day, source_available_at):
    info = day_readback(series, day)
    initial = day == JULY_DAYS[0]
    if (initial and info["end"] >= source_available_at) or (not initial and source_available_at >= info["start"]):
        raise ValueError("OI_JULY_SOURCE_CLOCK_CHANGED")
    low, high = JULY_PROTECTION
    overlap = next((b for b in series[1] if b.low <= high and b.high >= low), None)
    overlap_known_at = overlap.end + US if overlap else None
    events, signal_checks = window_signals(series, info["start"], info["end"] + 2 * US, "SHORT")
    matches = {clock: [signal_context(row, JULY_PROTECTION, overlap_known_at, source_available_at) for row in rows]
               for clock, rows in events.items()}
    return info | dict(
        band=JULY_PROTECTION, observation=observations(series[1], JULY_PROTECTION, "SHORT"),
        band_scope="POST_SESSION_CONFIRMATION_OF_REFERENCED_PROTECTION_SEARCH" if initial
        else "PREVIOUS_REFERENCE_IF_CARRIED_SENSITIVITY_ONLY",
        long_target_on_recap_day=observations(series[1], JULY_TARGET, "LONG") if day == JULY_DAYS[-1] else None,
        short_signal_proxies=matches, signal_prefix_checks=signal_checks,
        author_signal_at=None, active_protection_on_later_day_verified=False, author_action_at=None,
    )


def study(session, market):
    index = input_sources()
    sources, available = {}, {}
    for key, day in SOURCES.items():
        source = load_source(index, key)
        published = datetime.fromisoformat(source["published_at"])
        if published.date().isoformat() != day or published <= at(f"{day}T15:00"):
            raise ValueError("OI_SOURCE_IDENTITY_OR_TIME_CHANGED")
        sources[key] = source
        available[key] = published.replace(second=0, microsecond=0) + ONE
    may = {day: may_context(read_window(session, market, CONTRACT, date.fromisoformat(day)), day, available[MAY_SHORT])
           for day in MAY_DAYS}
    july = {day: july_context(read_window(session, market, CONTRACT, date.fromisoformat(day)), day, available[JULY_PLAN])
            for day in JULY_DAYS}
    return dict(version=VERSION, contract=CONTRACT, sources=sources, conservative_source_availability=available,
                may=may, july=july, primary_observations={
                    MAY_SHORT: "405_SHORT_REPORTED_WITH_PASSIVE_EXIT_OR_LOCK_WAIT",
                    MAY_LOCK: "405_LOCK_REPORTED_ORIGINAL_LEG_AND_EXACT_TIME_UNKNOWN",
                    JULY_PLAN: "PROTECTION_SEARCH_REFERENCE_NOT_EXECUTED_ACTION",
                    JULY_RECAP: "405_PROTECTION_AND_50_TREND_ROLES_NO_ACTION_ATTESTED",
                }, prior_plan_historical_revision_verified=False, author_position_continuity=None,
                author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        name = str(exc)
        parser.exit(2, (name if name.isidentifier() and name.startswith("OI_") else "OI_TARGET_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
