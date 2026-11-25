"""Bound OI2701 short-leg replacement across five archived holdings tables."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise, product
from pathlib import Path

from lms405_common_protection_window import OCT27_QUOTES
from lms405_i2701_case import FROZEN_COMPARISON_SHA256, readback
from lms405_m_permission_study import read_pair
from lms405_oi_leg_intent import CONTINUITY, CONTINUITY_SHA
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_right_side_study import ONE, at
from lms405_sh_protection_replacement import compatible_counts
from lms_near405_replay import encoded, sha

CONTRACT = "OI2701"
OPENING_AVERAGE = Decimal("10340.0")
LOTS = 40
TICK = Decimal(1)
FIRST, MORNING, LUNCH, CLOSE, NIGHT = "WRov1j6e10", "WRozNbg3en", "WRoAkcEppg", "U03", "WRoEvasxQR"
SOURCES = FIRST, MORNING, LUNCH, CLOSE, NIGHT
DAYS = date(2026, 10, 27), date(2026, 10, 28)


def replacement_bounds(minutes, captures, totals):
    cases = []
    for earlier, later in captures:
        if earlier >= later:
            raise ValueError("OI_RETENTION_QUOTE_ORDER_CHANGED")
        first_possible_prices = tick_bounds([bar for bar in minutes if bar.end <= earlier], TICK)
        # The earlier screenshot may be mid-minute. Give that entire minute to both sides.
        replacement_prices = tick_bounds([bar for bar in minutes if earlier <= bar.end <= later], TICK)
        possible = compatible_counts(LOTS, totals, totals, first_possible_prices, replacement_prices, None)
        cases.append(dict(earlier_quote_minute_end=earlier, later_quote_minute_end=later,
                          earlier_tick_range=first_possible_prices, replacement_tick_range=replacement_prices,
                          minimum_retained=min((old for old, _, _ in possible), default=None),
                          maximum_retained=max((old for old, _, _ in possible), default=None)))
    admissible = [row for row in cases if row["minimum_retained"] is not None]
    if not admissible:
        raise ValueError("OI_RETENTION_NO_PRICE_COMPATIBLE_CAPTURE_PAIR")
    return dict(total_quote_pairs=len(cases), price_compatible_quote_pairs=len(admissible),
                minimum_retained=min(row["minimum_retained"] for row in admissible),
                maximum_retained=max(row["maximum_retained"] for row in admissible), cases=cases)


def study(session, service):
    continuity = verified_json(CONTINUITY, CONTINUITY_SHA)
    quotes = verified_json(OCT27_QUOTES, FROZEN_COMPARISON_SHA256)
    source_index = input_sources()
    transitions = continuity["contracts"][CONTRACT]["transitions"]
    visible = {row["later"]: row["later_legs"] for row in transitions}
    snapshots = {}
    for key in SOURCES:
        table = continuity["sources"][key]
        photo = table["image"]
        if sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]:
            raise ValueError("OI_RETENTION_ATTACHMENT_CHANGED")
        legs = visible[key]
        short = legs["short"]
        if (short["quantity"], short["today_quantity"], Decimal(short["opening_average"])) != (
            LOTS, 0 if key == NIGHT else LOTS, OPENING_AVERAGE,
        ):
            raise ValueError("OI_RETENTION_SHORT_FIELDS_CHANGED")
        snapshots[key] = source_index[key] | dict(binding=table["binding"], image=photo, legs=legs,
                                                  quote_anchor=table["quote_anchor"])
    other = snapshots[NIGHT]["legs"]["long"]
    if (other["quantity"], other["today_quantity"], Decimal(other["opening_average"])) != (40, 40, Decimal("10224")):
        raise ValueError("OI_RETENTION_LONG_FIELDS_CHANGED")

    raw, bars = read_pair(session, service, CONTRACT, DAYS)
    market = readback(raw[1])
    if market != quotes["market_1m"]["oi"]:
        raise ValueError("OI_RETENTION_FROZEN_MARKET_CHANGED")
    minutes = [bar for bar, record in zip(bars[1], raw[1], strict=True) if record.trading_day == DAYS[0]]
    if len(minutes) != 345:
        raise ValueError("OI_RETENTION_FIRST_TRADING_DAY_INCOMPLETE")
    totals = displayed_tick_totals(OPENING_AVERAGE, LOTS, TICK)

    first_cut = datetime.fromisoformat(snapshots[FIRST]["published_at"])
    morning_cut = datetime.fromisoformat(snapshots[MORNING]["published_at"])
    first_session_start = at("2026-10-26T21:00")
    morning_start = at("2026-10-27T09:00")
    morning_mark = Decimal(quotes["photos"][MORNING]["per_symbol"]["oi"]["mark"])
    first_mark = OPENING_AVERAGE - Decimal("70.0")  # Visible short profit-difference column in the saved image.
    captures = {
        key: [bar.end.astimezone(cutoff.tzinfo) for bar in minutes
              if start <= bar.start < cutoff + ONE and bar.low <= price <= bar.high]
        for key, start, cutoff, price in (
            (FIRST, first_session_start, first_cut, first_mark), (MORNING, morning_start, morning_cut, morning_mark),
        )
    }
    for key in (LUNCH, CLOSE):
        captures[key] = [datetime.fromisoformat(snapshots[key]["quote_anchor"])]
    bound_pairs = [*pairwise(SOURCES[:-1]), (FIRST, LUNCH), (FIRST, CLOSE)]
    comparisons = {f"{earlier}/{later}": replacement_bounds(minutes, product(captures[earlier], captures[later]), totals)
                   for earlier, later in bound_pairs}
    direct = comparisons[f"{FIRST}/{CLOSE}"]["minimum_retained"]
    new_day = [bar for bar, record in zip(bars[1], raw[1], strict=True) if record.trading_day == DAYS[1]]
    scope = "SAME_ACCOUNT_AND_AVERAGE_CONVENTION_WITH_POSITION_AND_QUOTE_SYNCHRONOUS"
    return dict(version="lms405-oi-short-retention-v1", contract=CONTRACT, snapshots=snapshots, market=market,
                opening_average_display=OPENING_AVERAGE, lots=LOTS, tick=TICK, total_ticks=list(totals),
                conditional_scope=scope, early_marks={FIRST: first_mark, MORNING: morning_mark}, capture_minutes=captures,
                replacement_window_includes_earlier_quote_minute=True, quotes_include_publishing_minute=True,
                comparisons=comparisons, hindsight_next_trading_day_high=max(bar.high for bar in new_day),
                if_trading_day_and_close_snapshot_correspond=dict(short_retained_close_to_night=LOTS,
                                                                  minimum_first_short_in_dual_leg_display=direct,
                                                                  today_long_at_night=other["today_quantity"]),
                snapshot_times_verified=False, account_continuity=None, author_task_role=None,
                archived_followup=source_index["WRoLeVhPQ1"], recovered_author_legs_after_night=None,
                admitted_author_actions=0, author_action_at=None, author_match_rate=None,
                executable=False, fills=None, pnl=None)


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
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OI_RETENTION_') and code.isidentifier() else 'OI_RETENTION_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
