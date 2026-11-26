"""Test earlier SH2701 short origins and the next-session protection against fixed photos."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import SIDES, compare_leg, leg_changes
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import input_sources
from lms405_portfolio_task_policy import gated_replay, published_protection_events
from lms405_protection_lot_timing import (
    displayed_tick_totals, earlier_lot_counts, latest_whole_leg_start, tick_bounds, verified_json,
)
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_contract_handoff import OCTOBER_PHOTO, OCTOBER_SHORT_AVERAGE, PLAN
from lms405_sh_lock_lifecycle import signals
from lms405_v_ta_case import identity
from lms_near405_replay import encoded

VERSION = "lms405-sh-original-short-study-v1"
CONTRACT = "SH2701"
NIGHT = "WRo2KQ43iX"
DAYS = tuple(date(2026, 10, day) for day in (16, 19, 20, 21, 22, 23, 26))
HORIZONS = (16, 19, 20, 21, 23)
WINDOW_END = at("2026-10-23T22:08")
TICK = Decimal(1)
LOTS = 20
DIVIDER = Decimal(1726)
HANDOFF = (Path("output/lms405-sh-contract-handoff-20261126/final-a.json"),
           "7003c3230578e3f1363d0f720d5eec851b341c70e2b974dedbe706cff998689b")
PORTFOLIO = (Path("output/lms405-published-band-policy-20261126/reviewed-a.json"),
             "d4c94838b935a0c59ec8db8e608499bf20409e7826ef545b59bce3a918a201d7")


def day_prefix(series, start):
    return {period: [bar for bar in values if bar.start >= start] for period, values in series.items()}


def quotes_by_photo(frozen):
    photos = {}
    for row in frozen["contracts"][CONTRACT]:
        source = row["source"]
        if source not in (OCTOBER_PHOTO, NIGHT):
            continue
        if row["status"] != "CHECKED":
            raise ValueError("SH_ORIGINAL_SHORT_PHOTO_SCOPE_CHANGED")
        quotes = row["by_variant"][frozen["variant"]]
        day = date.fromisoformat(row["assumed_trading_day"])
        photos.setdefault(source, {})[row["side"]] = (
            row["visible"], day, tuple(quotes), Decimal(row["reported_quote"]), row["quote_scope"],
        )
    if set(photos) != {OCTOBER_PHOTO, NIGHT} or any(set(rows) != set(SIDES) for rows in photos.values()):
        raise ValueError("SH_ORIGINAL_SHORT_PHOTO_SIDES_MISSING")
    return photos


def compare_photos(raw, actions, photos):
    state = leg_changes(CONTRACT, actions)
    market = {bar.bar_end: bar for bar in raw}
    result = {}
    for source, sides in photos.items():
        by_side, before_minute = {}, {}
        for side, (visible, day, quotes, mark, scope) in sides.items():
            by_side[side], before_minute[side] = {}, {}
            average = Decimal(visible["opening_average"])
            if side == "short":
                if average != OCTOBER_SHORT_AVERAGE:
                    raise ValueError("SH_ORIGINAL_SHORT_AVERAGE_CHANGED")
                average = OCTOBER_SHORT_AVERAGE
            for key in quotes:
                end = datetime.fromisoformat(key)
                bar = market[end]
                if (bar.trading_day != day or not bar.low <= mark <= bar.high
                        or (scope == "ALIGNED" and bar.close != mark)):
                    raise ValueError("SH_ORIGINAL_SHORT_QUOTE_PRICE_CHANGED")
                for output, cutoff in ((by_side, end), (before_minute, end - ONE)):
                    book = next((after for when, after in reversed(state) if when < cutoff), {})
                    output[side][key] = compare_leg(visible, average, day, cutoff, book.get(side), raw, LOTS, TICK)
        result[source] = dict(sides=by_side, both_strict_same_quote=joint_quotes(by_side),
                              sides_excluding_quote_minute=before_minute,
                              both_strict_excluding_quote_minute=joint_quotes(before_minute))
    return result


def joint_quotes(sides):
    return [key for key in sides["long"] if all(sides[side].get(key, {}).get("status") == "PRICE_COMPATIBLE"
                                               and sides[side][key]["price_compatible_strict"] for side in SIDES)]


def entry_probes(raw, series, known):
    through = at("2026-10-20T15:01")
    after_plan = [bar for bar in raw if known < bar.bar_end - ONE and bar.bar_end < through]
    total = displayed_tick_totals(OCTOBER_SHORT_AVERAGE, LOTS, TICK)
    price_crosses = [bar for prev, bar in zip(series[1], series[1][1:], strict=False)
                     if known < prev.start and bar.end + US < through
                     and prev.end == bar.start and prev.close >= DIVIDER > bar.close]
    first_cross = price_crosses[0] if price_crosses else None

    def check_price(instant, base):
        earlier = [bar for bar in base if bar.bar_end < instant]
        later = [bar for bar in base if instant < bar.bar_end - ONE]
        permissive_later = [bar for bar in base if instant < bar.bar_end]
        earlier_bounds = tick_bounds(earlier, TICK)
        strict_bounds, permissive_bounds = (tick_bounds(rows, TICK) for rows in (later, permissive_later))
        strict = earlier_lot_counts(earlier_bounds, strict_bounds, LOTS, total)
        permissive = earlier_lot_counts(earlier_bounds, permissive_bounds, LOTS, total)
        return dict(whole_leg_strict_after_signal=0 in strict, required_earlier_lots_strict=min(strict, default=None),
                    strict_later_bounds=strict_bounds, whole_leg_including_signal_overlap=0 in permissive,
                    required_earlier_lots_with_overlap=min(permissive, default=None),
                    later_bounds_with_overlap=permissive_bounds)

    rows = []
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        for signal in signals(series, shape, confirm, side="SHORT", start=known + US, cut=through):
            signal_at = signal["available_at"]
            beyond = signal["close"] < DIVIDER
            rows.append(dict(signal=signal, clock=f"{shape}m_to_{confirm}m", strict_below_divider=beyond,
                             crossing_already_known=first_cross is not None and first_cross.end + US < signal_at,
                             price_after_plan=check_price(signal_at, after_plan),
                             price_after_first_cross=(check_price(signal_at, [
                                 bar for bar in after_plan if first_cross.end + US < bar.bar_end - ONE
                             ]) if first_cross is not None and first_cross.end + US < signal_at else None)))
    first = (dict(known_at=first_cross.end + US, close=first_cross.close,
                  **check_price(first_cross.end + US, after_plan)) if first_cross is not None else None)
    return dict(analysis_end=through, divider=DIVIDER, first_cross=first, shape_candidates=rows,
                strict_price_only_latest_minute_start=latest_whole_leg_start(after_plan, TICK, LOTS, total),
                published_divider_does_not_confirm_entry=True)


def study(session, market):
    handoff, portfolio = verified_json(*HANDOFF), verified_json(*PORTFOLIO)["rolling_nine_contract_comparison"]
    index = input_sources()
    plan = load_source(index, PLAN)
    if plan != handoff["sources"][PLAN]:
        raise ValueError("SH_ORIGINAL_SHORT_PLAN_CHANGED")
    plan_known = datetime.fromisoformat(plan["published_at"]) + ONE
    raw, series = read_pair(session, market, CONTRACT, DAYS)
    for day in DAYS[:-1]:
        if identity([bar for bar in raw[1] if bar.trading_day == day]) != handoff["coverage"][
            f"{day}:{CONTRACT}"
        ]["identity"]:
            raise ValueError("SH_ORIGINAL_SHORT_FROZEN_MINUTES_CHANGED")
    plans, _, sources = plan_rows(index, CONTRACT)
    photos = quotes_by_photo(portfolio)
    replay = {}
    weeks = {day.day: next(bar.bar_end - ONE for bar in raw[1] if bar.trading_day == day)
             for day in DAYS if day.day in HORIZONS}
    for day, start in weeks.items():
        scoped = day_prefix(series, start)
        protection = published_protection_events(scoped, plans, WINDOW_END)
        actions, blocked = gated_replay(scoped[5], WINDOW_END, protection, minutes=scoped[1])
        for cutoff in (plan_known, at("2026-10-22T22:08"), at("2026-10-23T21:16"), WINDOW_END):
            if cutoff <= start:
                continue
            prefix = {period: [bar for bar in candles if bar.end + US < cutoff]
                      for period, candles in scoped.items()}
            actual = gated_replay(prefix[5], cutoff, published_protection_events(prefix, plans, cutoff),
                                  minutes=prefix[1])
            if actual != ([row for row in actions if datetime.fromisoformat(row["at"]) < cutoff],
                          [row for row in blocked if row["at"] < cutoff]):
                raise ValueError("SH_ORIGINAL_SHORT_REPLAY_PREFIX_CHANGED")
        replay[day] = dict(start=start, actions=actions, blocked=blocked,
                           photos=compare_photos(raw[1], actions, photos))
    control = [row for row in portfolio["gates"][CONTRACT]["protections"]
               if datetime.fromisoformat(row["at"]) < WINDOW_END]
    if encoded([row for row in replay[23]["actions"] if row["action"] == "LOCK"]) != encoded(control):
        raise ValueError("SH_ORIGINAL_SHORT_CONTROL_CHANGED")
    return dict(version=VERSION, contract=CONTRACT, plan=plan, plan_known=plan_known, protection_sources=sources,
                source_historical_revision_verified=False, tested_start_trading_days=list(weeks),
                market={f"{period}m": identity(values) for period, values in raw.items()},
                rolling_replay=replay, entry_probes=entry_probes(raw[1], series, plan_known),
                screenshot_positions_used_for_replay=False, candidate_priors="COLD_START_ONLY",
                references=dict(handoff=HANDOFF[1], portfolio=PORTFOLIO[1]), author_action_samples=0,
                author_match_rate=None, fills=None, pnl=None, executable=False)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as out:
            out.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError, StopIteration) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('SH_ORIGINAL_SHORT_') and code.isidentifier() else 'SH_ORIGINAL_SHORT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
