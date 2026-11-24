"""Replay scoped short participation and protection evidence on SH2701."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Bar, Position
from guiyi_quant.lms405.participation import Participation, assess_participation
from guiyi_quant.lms405.public_conditions import Condition
from lms405_locked_exit_audit import confirmed_shapes, verify_aggregation
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_replay import display, ohlc, read_session_series
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

CONTRACT = "SH2701"
MORNING = "WRnOnrllRX"
EVENING = "A5356884885635211"
HOLDINGS = "WRnTlEfj1t"
REFERENCE_SHA256 = "4341b322e096a06734c75f657845fee877e8a3cf58b8ff889c3ff993fc820558"


def market_identity(bars):
    return dict(count=len(bars), hash=sha(encoded([
        (bar.bar_end.isoformat(), *map(str, ohlc(bar))) for bar in bars
    ]).encode()))


def assess_source(plan, plan_id, as_of, *, no_chase):
    """The unit short is an input. The source describes policy, not a signal or a position."""
    known_at = datetime.fromisoformat(plan["published_at"]) + ONE
    request = Participation(
        Position(CONTRACT, short=Decimal(1)), "SHORT", plan_id, "unit-short", known_at,
        known_at, plan["source_url"], None,
    )
    facts = ()
    if no_chase:
        facts = (Condition(
            "RIGHT_POLICY_PERMITS", request.scope, CONTRACT, False, known_at, known_at,
            request.source, "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME",
        ),)
    result = assess_participation(request, facts, as_of=as_of)
    return dict(evidence_role="RETROSPECTIVE_SOURCE_POLICY_AND_UNIT_POSITION",
                version_binding=None, policy_available_at=known_at.isoformat(), **result)


def path(minutes, fives, *, start, before, band, extension, observed_average=None):
    eligible = [bar for bar in minutes if start <= bar.bar_end - ONE and bar.bar_end + US < before]
    if not eligible:
        raise ValueError("COMPLETED_WINDOW_REQUIRED")
    by_end = {bar.bar_end: bar for bar in eligible}
    low, high = band
    contacts = [bar for bar in eligible if bar.low <= high and bar.high >= low]
    candidates = {}
    for side in ("LONG", "SHORT"):
        rows = confirmed_shapes(fives, eligible, start=start, through=before - 2 * US, side=side)
        candidates[side] = events = []
        for row in rows:
            shape = datetime.fromisoformat(row["shape_at"])
            if shape - FIVE < start:
                continue
            for frequency, field in (("1m", "fast_at"), ("5m", "slow_at")):
                if not row[field]:
                    continue
                end = datetime.fromisoformat(row[field])
                quote = by_end[end].close
                earlier = next((bar for bar in reversed(contacts) if bar.bar_end < end), None)
                events.append(dict(
                    shape_at=display(shape), frequency=frequency, close_at=display(end), close=quote,
                    close_inside_protection_band=low <= quote <= high,
                    prior_protection_contact=display(earlier.bar_end) if earlier else None,
                    remaining_to_lower_extension=quote - extension,
                ))
        events.sort(key=lambda event: (event["close_at"], event["frequency"]))
    reference = next((bar for bar in eligible if bar.low <= extension), None)
    envelope = [bar for bar in eligible if observed_average is not None and bar.low <= observed_average <= bar.high]
    first_possible_prefix = None
    if observed_average is not None:
        minimum, maximum = eligible[0].low, eligible[0].high
        for bar in eligible:
            minimum, maximum = min(minimum, bar.low), max(maximum, bar.high)
            if minimum <= observed_average <= maximum:
                first_possible_prefix = bar.bar_end
                break
    return dict(
        start=display(start), before=display(before), minute_count=len(eligible),
        price_low=min(bar.low for bar in eligible), price_high=max(bar.high for bar in eligible),
        band=list(band), first_contact=display(contacts[0].bar_end) if contacts else None,
        last_contact=display(contacts[-1].bar_end) if contacts else None,
        extension=extension, first_extension_reached=display(reference.bar_end) if reference else None,
        geometric_confirmations=candidates,
        later_visible_opening_average=observed_average,
        first_minute_range_contains_average=display(envelope[0].bar_end) if envelope else None,
        first_window_prefix_range_contains_average=display(first_possible_prefix) if first_possible_prefix else None,
        range_contains_average_count=len(envelope), author_signal_at=None,
    )


def study(session, market, reference, exposure):
    sources = input_sources()
    morning, evening = (sources[key] for key in (MORNING, EVENING))
    (holdings,) = [row for row in exposure["tables"] if row["source"] == HOLDINGS]
    image = holdings["image"]
    if holdings["system"] != "4.0.5" or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("SH_HOLDINGS_SOURCE_CHANGED")
    legs = holdings["contracts"][CONTRACT]["legs"]
    bounds = (
        ("day", date(2026, 10, 22), morning, at("2026-10-22T09:31"), at("2026-10-22T15:01"),
         (Decimal("1653"), Decimal("1667")), Decimal("1623"), None),
        ("night", date(2026, 10, 23), evening, at("2026-10-22T21:00"), at("2026-10-22T22:10"),
         (Decimal("1610"), Decimal("1632")), Decimal("1543"), Decimal(legs["long"]["opening_average"])),
    )
    windows = {}
    for label, day, source, start, before, band, extension, average in bounds:
        if start < datetime.fromisoformat(source["published_at"]) + ONE:
            raise ValueError("PLAN_UNAVAILABLE")
        minutes, raw_fives = (read_session_series(session, market, "sh", CONTRACT, period, step, (day,))
                              for period, step in (("1m", ONE), ("5m", FIVE)))
        fives = [Bar(CONTRACT, bar.bar_end, *ohlc(bar), start=bar.bar_end - FIVE) for bar in raw_fives]
        verify_aggregation(fives, minutes)
        identity = {"1m": market_identity(minutes), "5m": market_identity(raw_fives)}
        if label == "day" and identity != reference["cases"]["sh-short"]["input"]:
            raise ValueError("FROZEN_SH_DAY_CHANGED")
        windows[label] = dict(
            plan_source=source,
            trading_day=day.isoformat(), market=identity,
            geometry=path(minutes, fives, start=start, before=before, band=band,
                          extension=extension, observed_average=average),
            participation=assess_source(source, MORNING if label == "day" else EVENING, before,
                                        no_chase=label == "day"),
        )
    return dict(
        version="lms405-sh-short-protection-path-v1", contract=CONTRACT, windows=windows,
        later_holdings=dict(source=HOLDINGS, source_url=holdings["source_url"], image=image,
                            published_at=holdings["published_at"], legs=legs, quote_at=None),
        provenance_scope="CURRENT_ARCHIVE_TEXT_HISTORICAL_REVISIONS_UNVERIFIED",
        market_geometry_is_not_a_protection_signal=True, actual_account_continuity=None,
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--right-side", type=Path, required=True)
    parser.add_argument("--exposure-audit", type=Path, required=True)
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
        raw_right, raw_exposure = args.right_side.read_bytes(), args.exposure_audit.read_bytes()
        if sha(raw_right) != REFERENCE_SHA256 or sha(raw_exposure) != EXPOSURE_SHA256:
            raise ValueError("FROZEN_INPUT_HASH_MISMATCH")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            result = study(session, build_market_data_service(session), json.loads(raw_right), json.loads(raw_exposure))
        result["input_sha256"] = {"right_side": REFERENCE_SHA256, "exposure": EXPOSURE_SHA256}
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
