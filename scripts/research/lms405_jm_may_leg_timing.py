"""Bound JM2609 displayed legs around the 20 May late-session M report."""

import argparse
import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_jm_may_case import INPUT_HASH
from lms405_portfolio_replay import EVIDENCE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds
from lms405_replay import display
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_sh_lock_lifecycle import signals
from lms405_trial_to_trend import frozen
from lms_near405_replay import encoded

VERSION = "lms405-jm-may-leg-timing-v1"
CONTRACT = "JM2609"
TICK = Decimal("0.5")
LOTS = 20
LONG_AVERAGE = Decimal("1206.00")
OLD_SHORT_AVERAGE = Decimal("1213.00")
NEXT_SHORT_AVERAGE = Decimal("1215.88")
MAY_INDEX = EVIDENCE / "evidence/jm2609-may-20261016.csv"
MAY_INDEX_HASH = "cf43c505a8f2eb121827f2921aef1770de72de817b3e95020011a1c78f6dcaee"
SPECIFICATION = "https://np-newsimg.dfcfw.com/download/A2_cms_f_20241220154509661337?abc2722.pdf=&direct=1"


def frozen_minutes(path):
    bars = []
    for row in csv.DictReader(frozen(path, INPUT_HASH).decode().splitlines()):
        end = datetime.fromisoformat(row["bar_end_shanghai"])
        if row["contract"] != CONTRACT or end != datetime.fromisoformat(row["bar_end_utc"]):
            raise ValueError("JM_MINUTE_IDENTITY_MISMATCH")
        bars.append(Bar(CONTRACT, end, *(Decimal(row[k]) for k in ("open", "high", "low", "close")), start=end - ONE))
    if not bars or any(left.end >= right.end for left, right in zip(bars, bars[1:], strict=False)):
        raise ValueError("JM_MINUTES_NOT_STRICTLY_ORDERED")
    return bars


def five_minute_geometry_input(minutes):
    """Rebuild completed 5m candles for research geometry within exact minute coverage."""
    index = {bar.end: bar for bar in minutes}
    fives = []
    for end in index:
        if end.minute % 5:
            continue
        parts = [index.get(end - offset * ONE) for offset in (4, 3, 2, 1, 0)]
        if any(bar is None for bar in parts):
            raise ValueError("JM_FIVE_MINUTE_GEOMETRY_GAP")
        fives.append(Bar(CONTRACT, end, parts[0].open, max(bar.high for bar in parts),
                         min(bar.low for bar in parts), parts[-1].close, start=end - FIVE))
    return fives


def forecast_bound(minutes, decision_boundary, totals, *, include_overlap):
    """Give the post-confirmation side either the next minute or only full minutes."""
    if include_overlap:
        earlier = [bar for bar in minutes if bar.end <= decision_boundary]
        later = [bar for bar in minutes if bar.end > decision_boundary]
    else:
        earlier = [bar for bar in minutes if bar.start <= decision_boundary]
        later = [bar for bar in minutes if bar.start > decision_boundary]
    previous, following = tick_bounds(earlier, TICK), tick_bounds(later, TICK)
    counts = earlier_lot_counts(previous, following, LOTS, totals)
    return dict(first_post_window_minute_end=display(later[0].end) if later else None,
                earlier_bounds_in_ticks=previous, later_bounds_in_ticks=following,
                prior_lots_min=min(counts, default=None), prior_lots_max=max(counts, default=None),
                all_lots_possible_after=0 in counts)


def study(path):
    minutes = frozen_minutes(path)
    source_index = {row["id"]: row for row in csv.DictReader(frozen(MAY_INDEX, MAY_INDEX_HASH).decode().splitlines())}
    sources = {identity: source_index[identity] for identity in ("G02", "G03", "G04", "G05", "G06", "G07")}
    sources["S5300688465954469"] = input_sources()["S5300688465954469"]
    close = at("2026-05-20T15:00")
    day_start = at("2026-05-20T09:00")
    trading_start = at("2026-05-19T21:00")
    next_start = at("2026-05-20T21:00")
    next_lunch = datetime.fromisoformat(sources["G03"]["published_at"])
    may20 = [bar for bar in minutes if trading_start < bar.end <= close]
    daytime = [bar for bar in may20 if bar.start >= day_start]
    next_day = [bar for bar in minutes if next_start < bar.end + US < next_lunch and bar.start >= next_start]
    if (len(may20), len(daytime), len(next_day)) != (345, 225, 255):
        raise ValueError("JM_RESEARCH_WINDOW_INCOMPLETE")
    long_totals = displayed_tick_totals(LONG_AVERAGE, LOTS, TICK)
    old_short_totals = displayed_tick_totals(OLD_SHORT_AVERAGE, LOTS, TICK)
    next_short_totals = displayed_tick_totals(NEXT_SHORT_AVERAGE, LOTS, TICK)
    path_low = min(daytime, key=lambda bar: bar.low)
    after_low = [bar for bar in daytime if bar.end > path_low.end]
    landmarks = {
        "after_observed_low": path_low.end,
        "first_recovery_close_above_1205_5": next(b.end for b in after_low if b.close > Decimal("1205.5")),
        "first_recovery_close_above_1210_5": next(b.end for b in after_low if b.close > Decimal("1210.5")),
        "first_recovery_close_above_1216": next(b.end for b in after_low if b.close > Decimal("1216")),
        "from_1430": at("2026-05-20T14:30"),
    }
    price_checks = {name: dict(boundary=display(when),
                              trading_day=forecast_bound(may20, when, long_totals, include_overlap=True),
                              starts_after_confirmed=forecast_bound(may20, when, long_totals, include_overlap=False),
                              after_low_only=forecast_bound(after_low, when, long_totals, include_overlap=True))
                    for name, when in landmarks.items()}
    fives = five_minute_geometry_input(daytime)
    geometry = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = signals({1: daytime, 5: fives}, shape, confirm, side="LONG", start=day_start, cut=close + 2 * US)
        shape_step = ONE if shape == 1 else FIVE
        geometry[f"{shape}m_to_{confirm}m"] = [
            event | dict(shape_entirely_after_low_minute=event["shape_end"] - shape_step >= path_low.end,
                         price_bound=forecast_bound(may20, event["confirmed_at"], long_totals, include_overlap=True),
                         whole_minutes_after=forecast_bound(may20, event["confirmed_at"], long_totals,
                                                            include_overlap=False))
            for event in events if event["confirmed_at"] > path_low.end
        ]
    next_day_ticks = tick_bounds(next_day, TICK)
    old_or_new_long = earlier_lot_counts(tick_bounds(may20, TICK), next_day_ticks, LOTS, long_totals)
    next_night = [bar for bar in next_day if bar.end.date() == next_start.date()]
    next_night_ticks = tick_bounds(next_night, TICK)
    old_or_night_long = earlier_lot_counts(tick_bounds(may20, TICK), next_night_ticks, LOTS, long_totals)
    return dict(
        version=VERSION, physical_contract=CONTRACT, sources=sources, market_export_sha256=INPUT_HASH,
        source_index_sha256=MAY_INDEX_HASH, source_rows_are_frozen_transcriptions=True,
        price_tick=TICK, price_tick_source=SPECIFICATION,
        observed_low=dict(end=display(path_low.end), low=path_low.low),
        comparison_minutes=dict(may20_trading_day=len(may20), may20_day_session=len(daytime),
                                may21_through_lunch=len(next_day)),
        midday_short=dict(source="G06", lots=LOTS, opening_average=OLD_SHORT_AVERAGE, today_lots=LOTS),
        closing_long=dict(source="G05", lots=LOTS, opening_average=LONG_AVERAGE, today_lots=LOTS),
        next_lunch=dict(source="G03", long_lots=LOTS, long_opening_average=LONG_AVERAGE, long_today_lots=0,
                        short_lots=LOTS, short_opening_average=NEXT_SHORT_AVERAGE, short_today_lots=LOTS,
                        next_night_price_envelope_in_ticks=next_night_ticks,
                        price_only_minimum_older_long_lots_if_rest_added_at_night=min(old_or_night_long),
                        next_day_price_envelope_in_ticks=next_day_ticks,
                        price_only_minimum_older_long_lots=min(old_or_new_long),
                        fully_opened_on_next_day_compatible=0 in old_or_new_long,
                        unchanged_midday_short_average_compatible=bool(set(old_short_totals) & set(next_short_totals))),
        long_price_checks=price_checks, approximate_long_geometry_after_low=geometry,
        geometry_kind="REBUILT_COMPLETED_BARS_DIAGNOSTIC_NOT_AUTHOR_SIGNAL",
        conditional_on=(
            "Opening averages refer to surviving lots of the displayed physical contract, rounded half-up.",
            "The frozen stock of minute ranges gives price bounds only. Account and screenshot continuity are unknown.",
            "The next-day prior-lot minima assume all older lots originated on the 20 May trading day.",
        ),
        earlier_plan_source=None, actual_signal_at=None, actual_action_at=None, exact_lot_origin_at=None,
        admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    if (args := parser.parse_args()).output.exists():
        parser.error("OUTPUT_EXISTS")
    result = encoded(study(args.market))
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(result)
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()
