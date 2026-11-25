"""Bound protection-lot timing from displayed averages and completed minute ranges."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from math import ceil
from pathlib import Path

from lms405_i2701_case import FROZEN_COMPARISON_SHA256, readback
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 27)
EXPOSURE = Path("output/lms405-exposure-20261125/exposure-audit.json")
MARKET = Path("output/lms-i2701-oct-20261125/comparison.json")
LUNCH = "WRoAkcEppg"
MORNING = "WRozNbg3en"
CASES = {
    "I2701": dict(plan="A5358325549629506", update=None, holding=LUNCH, quote="666.5",
                  cutoff="2026-10-27T11:30:00.000002", day_open="2026-10-27T09:00",
                  target=("654", "662.5"), protection=("667", "671"), counter_m=("675", "677.5")),
    "SH2701": dict(plan="A5358325972992140", update="WRouYm67Bc", holding=MORNING, quote=None,
                   cutoff="2026-10-27T10:13", day_open="2026-10-27T09:00",
                   target=("1483", "1485"), protection=("1516", "1529"), counter_m=("1544", "1547")),
}


def displayed_tick_totals(average, lots, tick):
    """Integer tick sums inside the positive half-up rounding interval."""
    half_step = Decimal(1).scaleb(average.as_tuple().exponent) / 2
    return range(ceil((average - half_step) * lots / tick), ceil((average + half_step) * lots / tick))


def tick_bounds(bars, tick):
    if not bars:
        return None
    low, high = min(b.low for b in bars) / tick, max(b.high for b in bars) / tick
    if low != int(low) or high != int(high):
        raise ValueError("OFF_TICK_PRICE_BOUND")
    return int(low), int(high)


def earlier_lot_counts(earlier, later, lots, totals):
    """Necessary counts only. Each lot may independently use any tick inside its window envelope."""
    if not totals:
        raise ValueError("OPENING_AVERAGE_TICK_SUM_UNAVAILABLE")
    counts = []
    for count in range(lots + 1):
        remaining = lots - count
        if (count and earlier is None) or (remaining and later is None):
            continue
        low_a, high_a = earlier or (0, 0)
        low_b, high_b = later or (0, 0)
        lower, upper = count * low_a + remaining * low_b, count * high_a + remaining * high_b
        if max(lower, totals.start) <= min(upper, totals.stop - 1):
            counts.append(count)
    return counts


def latest_whole_leg_start(minutes, tick, lots, totals):
    """Latest minute start whose remaining price envelope can contain the whole leg."""
    envelope = None
    for bar in reversed(minutes):
        low, high = tick_bounds((bar,), tick)
        envelope = (min(envelope[0], low), max(envelope[1], high)) if envelope else (low, high)
        if earlier_lot_counts(None, envelope, lots, totals):
            return display(bar.bar_end - ONE)
    return None


def documented_gates(bars, config, since):
    active = [bar for bar in bars if bar.bar_end - ONE >= since]
    if not active:
        raise ValueError("ACTIVE_WINDOW_MISSING")
    target_low, target_high = map(Decimal, config["target"])
    weak_low, weak_high = map(Decimal, config["protection"])
    m_low = Decimal(config["counter_m"][0])
    day_open = at(config["day_open"])
    first_target = next((bar for bar in active if bar.low <= target_high), None)
    # A contained price range is different from being already beyond the band at the open.
    return {
        "short_target_near": first_target,
        "short_target_far": next((bar for bar in active if bar.low <= target_low), None),
        "short_target_far_strict_close": next((bar for bar in active if bar.close < target_low), None),
        "protection_first_overlap": next((bar for bar in active if bar.low <= weak_high and bar.high >= weak_low), None),
        "protection_after_target_near": next((bar for bar in active if first_target
                                             and bar.bar_end - ONE > first_target.bar_end
                                             and bar.low <= weak_high and bar.high >= weak_low), None),
        "day_protection_first_overlap": next((bar for bar in active if bar.bar_end > day_open
                                             and bar.low <= weak_high and bar.high >= weak_low), None),
        "day_protection_close_above_near": next((bar for bar in active if bar.bar_end > day_open
                                                 and bar.close > weak_low), None),
        "protection_far_strict_close": next((bar for bar in active if bar.close > weak_high), None),
        "counter_m_near": next((bar for bar in active if bar.high >= m_low), None),
    }


def timing_bounds(minutes, gate, *, tick, lots, totals):
    if gate is None:
        return None
    # The gate bar only becomes known after its close. The following minute
    # may overlap that instant, so assigning its whole range to the later
    # window gives the proposed trigger an optimistic allowance.
    before = tick_bounds([bar for bar in minutes if bar.bar_end <= gate.bar_end], tick)
    later = tick_bounds([bar for bar in minutes if bar.bar_end > gate.bar_end], tick)
    counts = earlier_lot_counts(before, later, lots, totals)
    return dict(gate_bar_end=display(gate.bar_end), earlier_window_tick_bounds=before, later_window_tick_bounds=later,
                compatible_earlier_lots=counts, minimum_earlier_lots=min(counts, default=None))


def verified_json(path, digest):
    raw = path.read_bytes()
    if sha(raw) != digest:
        raise ValueError("PROTECTION_TIMING_INPUT_CHANGED")
    return json.loads(raw)


def study(session, market, exposure, market_reference):
    sources = input_sources()
    holdings = {table["source"]: table for table in exposure["tables"]}
    specs = load_specs(json.loads(SPECS.read_bytes()))
    cases = {}
    for contract, cfg in CASES.items():
        symbol = contract[:-4].lower()
        minutes = read_session_series(session, market, symbol, contract, "1m", ONE, (DAY,))
        identity = readback(minutes)[DAY.isoformat()]
        if identity != market_reference["market_1m"][symbol][DAY.isoformat()]:
            raise ValueError("PROTECTION_TIMING_MARKET_CHANGED")
        table = holdings[cfg["holding"]]
        image, lunch_image = table["image"], holdings[LUNCH]["image"]
        for attached in (image, lunch_image):
            if sha((ARCHIVE.parent / attached["path"]).read_bytes()) != attached["sha256"]:
                raise ValueError("PROTECTION_TIMING_IMAGE_CHANGED")
        long = table["contracts"][contract]["legs"]["long"]
        noon = holdings[LUNCH]["contracts"][contract]["legs"]["long"]
        if (noon["today_quantity"] != noon["quantity"] or noon["quantity"] != long["quantity"]
                or noon["opening_average"] != long["opening_average"]):
            raise ValueError("PROTECTION_TIMING_LEG_FIELDS_CHANGED")
        cutoff = at(cfg["cutoff"])
        visible = [bar for bar in minutes if bar.bar_end + US < cutoff]
        # A post timestamp has minute precision. Add the two overlapping
        # minutes to a second, optimistic price envelope, but never use them
        # to generate a pre-publication gate.
        possible_photo_prices = (
            visible if cfg["quote"] is not None else [bar for bar in minutes if bar.bar_end <= cutoff + ONE]
        )
        if cfg["quote"] is not None and visible[-1].close != Decimal(cfg["quote"]):
            raise ValueError("PROTECTION_TIMING_ANCHOR_CHANGED")
        basis = cfg["update"] or cfg["plan"]
        since = datetime.fromisoformat(sources[basis]["published_at"]) + ONE
        gates = documented_gates(visible, cfg, since)
        if cfg["update"]:
            older_start = datetime.fromisoformat(sources[cfg["plan"]]["published_at"]) + ONE
            older = [bar for bar in visible if bar.bar_end - ONE >= older_start and bar.bar_end + US < since]
            low, high = map(Decimal, cfg["protection"])
            gates["pre_update_protection_first_overlap"] = next(
                (bar for bar in older if bar.low <= high and bar.high >= low), None,
            )
            gates["pre_update_protection_strict_close"] = next((bar for bar in older if bar.close > low), None)
            gates["return_above_previous_target_proxy"] = next(
                (bar for bar in visible if bar.bar_end - ONE >= since and bar.close > Decimal("1498")), None,
            )
            gates["visible_update_available"] = next(bar for bar in reversed(visible) if bar.bar_end <= since)
        average, lots, tick = Decimal(long["opening_average"]), long["quantity"], specs[contract]["tick"]
        totals = displayed_tick_totals(average, lots, tick)
        cases[contract] = dict(
            market=identity, completed_minutes_in_window=len(visible), cutoff=cutoff, source_image=image,
            optimistic_price_minutes=len(possible_photo_prices),
            holding_source=cfg["holding"], lunch_source_image=lunch_image, source_quote_anchor=cfg["quote"],
            price_sources=list(dict.fromkeys((cfg["plan"], basis))),
            price_source_historical_edits_verified=False, source_version_binding_per_leg=None,
            same_current_day_leg_as_lunch_assumption=cfg["holding"] != LUNCH,
            searched_role_start=since, bands={name: cfg[name] for name in ("target", "protection", "counter_m")},
            protection_band_status="OLDER_PRE_UPDATE_ONLY" if cfg["update"] else "CURRENT_VISIBLE_PLAN",
            reviewed_update_price_band=None, observed_lots=lots, displayed_opening_average=average,
            tick_size=tick, display_rounding_assumption="HALF_UP_AT_DISPLAYED_PRECISION",
            compatible_tick_totals=list(totals), avg_whole_window_tick_bounds=tick_bounds(visible, tick),
            latest_price_compatible_whole_leg_start=latest_whole_leg_start(visible, tick, lots, totals),
            optimistic_latest_whole_leg_start=latest_whole_leg_start(possible_photo_prices, tick, lots, totals),
            bounds={name: timing_bounds(visible, gate, tick=tick, lots=lots, totals=totals)
                    for name, gate in gates.items()},
            optimistic_photo_bounds=(
                {name: timing_bounds(possible_photo_prices, gate, tick=tick, lots=lots, totals=totals)
                 for name, gate in gates.items()} if cfg["quote"] is None else None
            ),
            account_continuity=None, real_action_at=None,
        )
    return dict(version="lms405-protection-lot-timing-v1", cases=cases, admitted_author_action_samples=0,
                author_matches=None, executable=False, fills=None, pnl=None)


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
        exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
        market_reference = verified_json(MARKET, FROZEN_COMPARISON_SHA256)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=30):
            result = study(session, build_market_data_service(session), exposure, market_reference)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "PROTECTION_TIMING_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
