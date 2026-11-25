"""Bound RU2701 leg continuity from the first night to the following holding display."""

import argparse
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_replay import display, read_session_series
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA
from lms405_right_side_study import ONE, US
from lms405_sh_protection_replacement import compatible_counts
from lms405_sizing_audit import SPECS, load_specs
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

VERSION = "lms405-rubber-leg-transition-v1"
CONTRACT = "RU2701"
DAY = date(2026, 10, 23)
PLAN, FIRST, LATER, CLOSE = "A5356884885635211", "WRnTlEfj1t", "WRnZKEysLc", "WRo00BFM1E"
RECAP = "WRo1EvBQCD"
M_NEAR = Decimal("19790")
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
MINUTE_SHA = "15762997bcf3d1b7cdb1b955dc40673abbf10fd3821126300682cd57fd0188de"
IMAGES = {
    FIRST: ("RnTlEfj1t-table2-screen.png", "eb6bc29a2f01068202e0f79c6570602edc0b3c7acbf7a6b5102d91ec6d6f9802"),
    LATER: ("RnZKEysLc-table2-screen.png", "d78135497fbc2396a59fdfdf055667ba5626428795ae98a26e6228d732de032c"),
    CLOSE: ("Ro00BFM1E-table3-screen.png", "a8ef858874c4264203b6d4ef22db3e7ee92767a37b133cd624ca67b12bc7ac56"),
    "WRnTmqo3x5": ("RnTmqo3x5-software3-screen.png", "06b8a8e2beb8da91dddd1619d3701e3c17feac67a14d70370df8495a7ffc71a6"),
    "WRnZKEysLc-return": ("RnZKEysLc-software4-screen.png",
                         "03bdc1dd6785e7a87971cadfc831932abe86ea36442ca79f21e541b9dfaed1db"),
    "WRoEvFgWlh": ("RoEvFgWlh-iih9qdgrv6-screen.png", "8911ea14cdc964de5e872367da9f0c1a02e105ebda7858c7c0dcf89db6b8db2a"),
}


def displayed_mark(average, points, floating, *, lots, tick, multiplier):
    """Check the opening average, rounded point spread and currency P/L together."""
    options = []
    spread = floating / (lots * multiplier)
    for tick_total in displayed_tick_totals(average, lots, tick):
        mean = tick_total * tick / lots
        mark = mean + spread
        if (spread.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) == points
                and mark % tick == 0):
            options.append((mean, mark))
    if len(options) != 1:
        raise ValueError("RU_DISPLAY_MARK_NOT_UNIQUE")
    return options[0]


def position_change(prices, old_at, later_at, m_at, *, tick, lots, old_totals, new_totals):
    old = tick_bounds([bar for bar in prices if bar.bar_end <= old_at], tick)
    # Allow one old snapshot minute in both envelopes to avoid asserting its internal order.
    changed = [bar for bar in prices if old_at <= bar.bar_end <= later_at]
    pre_m = tick_bounds([bar for bar in changed if bar.bar_end < m_at], tick)
    at_or_after_m = tick_bounds([bar for bar in changed if bar.bar_end >= m_at], tick)
    allowed = compatible_counts(lots, old_totals, new_totals, old, pre_m, at_or_after_m)
    return dict(old_price_bounds_ticks=old, pre_m_new_price_bounds_ticks=pre_m,
                at_or_after_m_new_price_bounds_ticks=at_or_after_m, possible_count=len(allowed),
                minimum_replaced_lots=lots - max(row[0] for row in allowed) if allowed else None,
                maximum_replaced_lots=lots - min(row[0] for row in allowed) if allowed else None,
                minimum_new_lots_at_or_after_m=min((row[2] for row in allowed), default=None),
                minimum_lots_originating_before_m=lots - max(row[2] for row in allowed) if allowed else None,
                all_new_before_m_possible=any(row[2] == 0 for row in allowed))


def source_images(index):
    images = {}
    for key, (basename, expected) in IMAGES.items():
        source = key.removesuffix("-return")
        path = Path(index[source]["archive_path"]).parent / basename
        if sha((ARCHIVE.parent / path).read_bytes()) != expected:
            raise ValueError("RU_POSITION_TRANSITION_IMAGE_CHANGED")
        images[key] = dict(path=path.as_posix(), sha256=expected, source_url=index[source]["source_url"])
    return images


def study(session, market):
    spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
    timeline = read_session_series(session, market, "ru", CONTRACT, "1m", ONE, (DAY,))
    if len(timeline) != 345 or bars_sha(timeline) != MINUTE_SHA:
        raise ValueError("RU_TRANSITION_MARKET_CHANGED")
    index = input_sources()
    images = source_images(index)
    frozen_photo = verified_json(PHOTO, PHOTO_SHA)["photos"]
    tick, multiplier, lots = spec["tick"], spec["multiplier"], 20
    earlier_display, later_display = Decimal("19505.0"), Decimal("19674.8")
    mean, mark = displayed_mark(later_display, Decimal("115.3"), Decimal("23050"),
                                lots=lots, tick=tick, multiplier=multiplier)
    upper = datetime.fromisoformat(index[LATER]["published_at"])
    available = [b for b in timeline if b.bar_end + US < upper]
    if mean != Decimal("19674.75") or mark != Decimal("19790"):
        raise ValueError("RU_POSITION_TRANSITION_DISPLAY_CHANGED")
    matches = [b.bar_end for b in available if b.low <= mark <= b.high]
    if not matches:
        raise ValueError("RU_POSITION_TRANSITION_MARK_NOT_OBSERVED")
    prior = [datetime.fromisoformat(t) for t in frozen_photo[FIRST]["per_symbol"]["ru"]["contains"]]
    other = frozen_photo[LATER]["per_symbol"]
    overlap = Counter(t for row in other.values() for t in row["contains"])
    old_totals = displayed_tick_totals(earlier_display, lots, tick)
    new_totals = displayed_tick_totals(later_display, lots, tick)
    first_m = next(b.bar_end for b in available if b.high >= M_NEAR)
    bounds = {
        display(old): {display(new): position_change(available, old, new, first_m, tick=tick, lots=lots,
                                                    old_totals=old_totals, new_totals=new_totals) for new in matches}
        for old in prior
    }
    return dict(
        version=VERSION, contract=CONTRACT, quote_kind="DISPLAY_ARITHMETIC_WITH_PRICE_COMPATIBILITY_ONLY",
        trading_day=DAY, source_images=images,
        sources={key: index[key] for key in (PLAN, FIRST, LATER, CLOSE, RECAP)},
        initial=dict(lots=lots, today=lots, opening_average=earlier_display),
        later=dict(lots=lots, today=lots, opening_average=later_display, point_difference="115.3",
                   per_position_float="23050", exact_mean=mean, quote_candidate=mark, opposite_leg_visible=False),
        tick=tick, multiplier=multiplier, frozen_market_sha256=MINUTE_SHA, comparable_minutes=len(available),
        later_mark_compatible=[dict(end=display(t), other_symbols_matched=overlap[display(t)],
                                    includes_all_other_symbols=overlap[display(t)] == len(other)) for t in matches],
        m_near=M_NEAR, first_m_contact_minute_end=display(first_m), pairwise_conditional_bounds=bounds,
        actual_capture_time=None, same_account=None, actual_replacement=None, actual_order_at=None,
        admitted_author_actions=0, executable=False, fills=None, pnl=None,
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
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (OperationalError, MarketDataError):
        parser.error("LOCAL_MARKET_READ_FAILED")
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()
