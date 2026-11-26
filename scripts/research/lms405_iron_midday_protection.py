"""Bound the origin and location of I2701's 27 October midday protection."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import readback
from lms405_first_night_shape_cross import breaches
from lms405_iron_first_protection import ORIGINAL, by_knowledge, support
from lms405_iron_original_exit import CONTRACT
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_quantity_stages import compatible_allocations
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import signals
from lms_near405_replay import encoded, sha

BEIJING_DAY = date(2026, 10, 27)
NIGHT_OPEN, DAY_OPEN = at("2026-10-26T21:00"), at("2026-10-27T09:00")
NOON, MORNING_POST_END = at("2026-10-27T11:30"), at("2026-10-27T10:14")
PLAN, UPDATED, LUNCH = "A5358325549629506", "A5358686423089344", "WRoAkcEppg"
FIRST = "WRnTlEfj1t"
MORNING = "WRozNbg3en"
PHOTO = (Path("02-持仓记录/2026-10-27/WRoAkcEppg-pos2-screen.png"),
         "482969294bdf44a7d4f6bd8b7527708f3d94719b26648befcc00cf72d8b788f8")
FROZEN = (Path("output/lms-i2701-oct-20261125/protection-window.json"),
          "1343cd7c6487e4cddfb0538a03ca18bc588e5fb3846dcd43d22a04d110658163")
BANDS = Decimal("664.5"), Decimal(667), Decimal(671)


def phase_prices(bars, *, split, trading_open, tick, lots, totals):
    """Solve all three counts jointly. A missing display row does not constrain any count."""
    windows = (
        [b for b in bars if b.end <= trading_open],
        [b for b in bars if trading_open <= b.start < split],
        [b for b in bars if b.start >= split],
    )
    bounds = tuple(tick_bounds(rows, tick) for rows in windows)
    allocations = compatible_allocations(lots, totals, bounds)
    return dict(
        phase_bounds_in_ticks=bounds,
        feasible_counts=allocations,
        night_lots=sorted({r[0] for r in allocations}),
        before_morning_post_lots=sorted({r[0] + r[1] for r in allocations}),
        post_morning_lots=sorted({r[2] for r in allocations}),
        compatible_single_phase=[any(row[i] == lots for row in allocations) for i in range(3)],
    )


def low_price_counts(bars, edge, *, tick, lots, totals):
    lower, upper = tick_bounds(bars, tick)
    limit = int(edge / tick)
    if limit * tick != edge:
        raise ValueError("IRON_NOON_EDGE_OFF_TICK")
    below = (lower, min(upper, limit - 1)) if lower < limit else None
    above = (max(lower, limit), upper) if upper >= limit else None
    return earlier_lot_counts(below, above, lots, totals)


def study(session, market):
    frozen = verified_json(*FROZEN)
    prior = verified_json(*ORIGINAL)["windows"]["2026-10-19"]["comparisons"]["require_disclosed_exit"]
    sources = input_sources()
    records = {key: load_source(sources, key) for key in (PLAN, UPDATED, LUNCH, FIRST, *frozen["early_holdings_sources"])}
    if not datetime.fromisoformat(records[PLAN]["published_at"]) + ONE < NIGHT_OPEN < NOON < datetime.fromisoformat(
        records[UPDATED]["published_at"]
    ) or (
        frozen["plan_source"] != PLAN or frozen["opening_average_source"] != LUNCH
        or sha((ARCHIVE.parent / PHOTO[0]).read_bytes()) != PHOTO[1]
        or datetime.fromisoformat(records[MORNING]["published_at"]) + ONE != MORNING_POST_END
    ):
        raise ValueError("IRON_NOON_PUBLISHED_SCOPE_CHANGED")
    selected = {(r["source"], r["side"]): r for r in prior["comparisons"]}
    lunch = selected[LUNCH, "long"]["visible"]
    short = selected[LUNCH, "short"]["by_variant"]["strict_replay"][NOON.isoformat()]
    first = selected[FIRST, "long"]
    short_first = selected[FIRST, "short"]["by_variant"]["strict_replay"]
    if (short["status"] != "PRICE_COMPATIBLE" or {r["origin_at"] for r in short_first.values()} != {short["origin_at"]}
            or any(selected[k, "long"]["status"] != "UNLISTED_UNKNOWN" for k in frozen["early_holdings_sources"])):
        raise ValueError("IRON_NOON_FROZEN_POSITION_SCOPE_CHANGED")
    lots, tick, average = lunch["quantity"], Decimal(frozen["tick_size"]), Decimal(lunch["opening_average"])
    totals = displayed_tick_totals(average, lots, tick)
    if (lots != frozen["quantity"] or lots != lunch["today_quantity"] or list(totals) != frozen["compatible_tick_totals"]
            or not date.fromisoformat(first["assumed_trading_day"]) < BEIJING_DAY):
        raise ValueError("IRON_NOON_TODAY_SCOPE_CHANGED")
    raw, data = read_pair(session, market, CONTRACT, (BEIJING_DAY,))
    actual = dict(minute=readback(raw[1])[str(BEIJING_DAY)], five_minute=readback(raw[5])[str(BEIJING_DAY)])
    if actual != frozen["market"]:
        raise ValueError("IRON_NOON_MARKET_CHANGED")
    minutes = [bar for bar in data[1] if bar.end <= NOON]
    day = [b for b in minutes if b.start >= DAY_OPEN]
    night = [b for b in minutes if b.end <= DAY_OPEN]
    resistance, protection, far = BANDS
    after_post = [b for b in day if b.start >= MORNING_POST_END]
    clocks = {name: next((b.end for b in rows if b.high >= price), None) for name, rows, price in (
        ("night_first_far_touch", night, far), ("day_first_resistance", day, resistance),
        ("post_first_resistance", after_post, resistance), ("day_first_near_protection", day, protection),
    )}
    options = {"same_trading_day": {b.end for b in minutes}, "night_only": {b.end for b in night},
               "day_only": {b.end for b in day}, "after_morning_post": {b.end for b in after_post}}
    cases = {}
    for include in (False, True):
        window = [b for b in minutes if b.end < NOON or include]
        checks = {}
        for overlap in (False, True):
            allowed = options | {name: by_knowledge(window, end + US if end else None, overlapping=overlap)
                                 for name, end in clocks.items()}
            if overlap:
                allowed |= {f"{name}_including_touch_minute": {b.end for b in window if end and b.end >= end}
                            for name, end in clocks.items()}
            checks["allow_overlap" if overlap else "strict_after_knowledge"] = {
                name: support(window, NOON, eligible, tick=tick, lots=lots, totals=totals, include_quote=include)
                for name, eligible in allowed.items()
            }
        cases["include_quote" if include else "exclude_quote"] = dict(
            price_tests=checks,
            phase_allocations=phase_prices(window, split=MORNING_POST_END, trading_open=DAY_OPEN,
                                           tick=tick, lots=lots, totals=totals),
            price_below_edge_lots={str(edge): low_price_counts(window, edge, tick=tick, lots=lots, totals=totals)
                                   for edge in BANDS},
        )
    fresh = {f"{a}m_to_{b}m": signals(data, a, b, start=NIGHT_OPEN, cut=NOON, side="LONG")
             for a, b in ((1, 1), (5, 1), (5, 5))}
    return dict(
        study="IRON_MIDDAY_PROTECTION_PHASE_AND_PRICE_BOUNDS", sources=records, market=actual,
        author_open_fields=lunch, opening_total_ticks=list(totals), noon_quote_end=NOON,
        original_simulated_short_entry=short["origin_at"], old_long_can_carry_to_noon_with_today_fields=False,
        earlier_long_rows_unknown=True, touch_bar_ends=clocks, by_quote_treatment=cases, new_shape_checks=fresh,
        five_minute_shape_intraminute_breaches=breaches(data[5], data[1], NIGHT_OPEN, NOON),
        holdings_image_sha256=PHOTO[1],
        historical_plan_revision_verified=False, author_action_samples=0, actual_author_permission=None,
        author_match_rate=None, fills=None, executable=False,
    )


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
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("IRON_NOON_")
                        else "IRON_NOON_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
