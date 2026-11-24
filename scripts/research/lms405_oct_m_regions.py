"""Audit where two published VPLUS rebound ladders were reached in local price data."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.lms405 import Bar
from lms405_locked_exit_audit import confirmed_shapes, verify_aggregation
from lms405_replay import display, ohlc, photo_comparison, read_session_series
from lms_near405_replay import encoded, sha

LOCAL = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 10, 28)
ONE, FIVE = timedelta(minutes=1), timedelta(minutes=5)
PLAN_POST = datetime(2026, 10, 27, 17, 38, tzinfo=LOCAL)
NIGHT_POST = datetime(2026, 10, 27, 22, 12, tzinfo=LOCAL)
RECAP_POST = datetime(2026, 10, 28, 15, 22, tzinfo=LOCAL)
LADDERS = {
    "SH2701": {"resistance": (1478, 1490), "interruption": (1490, 1501),
               "m": (1513, 1523), "extreme_m": (1523, 1536)},
    "RU2701": {"resistance": (19200, 19360), "interruption": (19360, 19405),
               "m": (19515, 19610), "extreme_m": (19765, 19970)},
}


def measure(minutes, fives, ladder):
    if not minutes or not fives:
        raise ValueError("COMPLETED_SEGMENT_REQUIRED")
    levels = {}
    for name, (lower, upper) in ladder.items():
        edges = levels[name] = {}
        for edge, raw_level in (("lower", lower), ("upper", upper)):
            level = Decimal(raw_level)
            reaches = next((b for b in minutes if b.high >= level), None)
            one_close = next((b for b in minutes if b.close > level), None)
            five_close = next((b for b in fives if b.close > level), None)
            edges[edge] = dict(
                price=str(level),
                first_1m_high_at_or_above=display(reaches.bar_end) if reaches else None,
                first_1m_close_strictly_above=display(one_close.bar_end) if one_close else None,
                first_5m_close_strictly_above=display(five_close.bar_end) if five_close else None,
            )
    return dict(
        counts={"1m": len(minutes), "5m": len(fives)}, first_bar_end=display(minutes[0].bar_end),
        last_bar_end=display(minutes[-1].bar_end),
        high=str(max(b.high for b in minutes)), low=str(min(b.low for b in minutes)), levels=levels,
    )


def split_scope(bars, step, civil_day, cut):
    # Exclude a Bar that starts in the plan's publication minute or ends in the recap minute.
    return [b for b in bars if b.bar_end.astimezone(LOCAL).date() == civil_day
            and PLAN_POST + ONE <= b.bar_end - step and b.bar_end < cut]


def geometry_after_formation(signals, minutes):
    start = minutes[0].bar_end - ONE
    through = minutes[-1].bar_end
    scoped_signals = [b for b in signals if b.start >= start and b.end <= through]
    rows = confirmed_shapes(scoped_signals, minutes, start=start, through=through, side="LONG")
    close_by_end = {b.bar_end: b.close for b in minutes}
    for row in rows:
        for speed in ("fast", "slow"):
            raw = row[f"{speed}_at"]
            end = datetime.fromisoformat(raw) if raw else None
            row[f"{speed}_at"] = display(end) if end is not None else None
            row[f"{speed}_close"] = str(close_by_end[end]) if end is not None else None
        row["shape_at"] = display(datetime.fromisoformat(row["shape_at"]))
    return rows


def study(session, market):
    from app.market_data.market_data_service import MarketDataError

    cases, verified_minutes = {}, {}
    for contract, ladder in LADDERS.items():
        row = cases[contract] = {}
        try:
            minutes = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (DAY,))
            fives = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, (DAY,))
            signals = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in fives]
            verify_aggregation(signals, minutes)
            scopes = {}
            for name, civil_day, cut in (
                ("night_before_holdings_post", PLAN_POST.date(), NIGHT_POST),
                ("full_night", PLAN_POST.date(), RECAP_POST),
                ("following_day", DAY, RECAP_POST),
            ):
                scoped_minutes = split_scope(minutes, ONE, civil_day, cut)
                scoped_fives = split_scope(fives, FIVE, civil_day, cut)
                prices = measure(scoped_minutes, scoped_fives, ladder)
                scopes[name] = prices | dict(long_geometry=geometry_after_formation(signals, scoped_minutes))
        except MarketDataError as exc:
            row.update(status="WINDOW_UNAVAILABLE", reason=exc.code)
            continue
        except (KeyError, ValueError):
            row.update(status="WINDOW_UNAVAILABLE", reason="SESSION_OR_AGGREGATION_UNVERIFIED")
            continue

        verified_minutes[contract] = minutes
        row.update(status="WINDOW_READABLE", scopes=scopes, inputs={
            period: dict(count=len(bars), sha256=sha(encoded([
                (b.bar_end.isoformat(), *map(str, ohlc(b))) for b in bars
            ]).encode())) for period, bars in (("1m", minutes), ("5m", fives))
        })

    quote_checks = {}
    if verified_minutes.keys() == LADDERS.keys():
        quote_checks["sh_ru"] = photo_comparison(
            verified_minutes, PLAN_POST, NIGHT_POST, {"SH2701": "1491", "RU2701": "19480"},
        )
        try:
            oilseed = read_session_series(session, market, "oi", "OI2701", "1m", ONE, (DAY,))
        except MarketDataError as exc:
            quote_checks["oi_input_status"] = exc.code
        except (KeyError, ValueError):
            quote_checks["oi_input_status"] = "SESSION_COVERAGE_UNVERIFIED"
        else:
            quote_checks["sh_ru_oi"] = photo_comparison(
                verified_minutes | {"OI2701": oilseed}, PLAN_POST, NIGHT_POST,
                {"SH2701": "1491", "RU2701": "19480", "OI2701": "10237"},
            )
            quote_checks["oi_input_status"] = "WINDOW_READABLE"
            quote_checks["oi_input_sha256"] = sha(encoded([
                (b.bar_end.isoformat(), *map(str, ohlc(b))) for b in oilseed
            ]).encode())
    return dict(
        version="lms405-oct-m-regions-v1", trading_day=DAY.isoformat(),
        source_plan="A5358686695981271", plan_published=PLAN_POST.isoformat(),
        price_evidence_scope="CURRENT_VISIBLE_PLAN_RETROSPECTIVE",
        holdings_source="WRoEvasxQR", holdings_post_minute=NIGHT_POST.isoformat(),
        recap_source="WRoLeVhPQ1", recap_post_minute=RECAP_POST.isoformat(),
        contract_cases=cases, photo_quote_comparisons=quote_checks,
        author_m_contract=None, author_m_switch_at=None, author_action_matches=None,
        admitted_author_action_samples=0, executable=False, fills=None, pnl=None,
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
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded(report))


if __name__ == "__main__":
    main()
