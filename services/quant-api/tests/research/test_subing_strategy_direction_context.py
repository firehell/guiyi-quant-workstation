from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.subing_daily_watch import (
    SubingDailyWatchDecision,
    SubingDailyWatchItem,
)
from app.market_data.subing_daily_watch_calendar import SubingDailyWatchCalendarError
from app.market_data.subing_ema_trend import (
    PriceSide,
    SubingStitchedEmaTrendSnapshot,
)
from app.market_data.subing_strategy.contracts import SubingStrategyDirection
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyContextIdentityError,
    SubingStrategyDirectionContextResolver,
)


TARGET_LONG = date(2026, 8, 26)
TARGET_SHORT = date(2026, 8, 27)
SOURCE_LONG = date(2026, 8, 25)
SOURCE_SHORT = date(2026, 8, 26)
HISTORY_FLOOR = date(2026, 8, 26)


def _trend(
    timeframe: BarFrequency,
    *,
    source_day: date,
    contract: str = "JM2609",
) -> SubingStitchedEmaTrendSnapshot:
    return SubingStitchedEmaTrendSnapshot(
        timeframe=timeframe,
        bar_end=datetime.combine(source_day, datetime.min.time(), UTC),
        trading_day=source_day,
        contract=contract,
        current_segment_start_trading_day=date(2026, 8, 17),
        warmup_start_trading_day=date(2026, 6, 1),
        warmup_bar_count=30,
        warmup_segment_count=2,
        history_mode="rank1_stitched_raw",
        close=Decimal("102"),
        ema21=Decimal("100"),
        price_side=PriceSide.ABOVE,
        slope_5_raw=Decimal("1"),
        slope_10_raw=Decimal("2"),
        slope_5_bps_per_bar=Decimal("1"),
        slope_10_bps_per_bar=Decimal("2"),
    )


def _item(
    decision: SubingDailyWatchDecision,
    *,
    source_day: date,
    unavailable_reasons: tuple[str, ...] = (),
) -> SubingDailyWatchItem:
    if decision is SubingDailyWatchDecision.UNAVAILABLE:
        return SubingDailyWatchItem(
            symbol="jm",
            product_name="焦煤",
            sector="black",
            decision=decision,
            reason_codes=(),
            daily=None,
            hourly=None,
            unavailable_reasons=unavailable_reasons,
        )
    reasons = {
        SubingDailyWatchDecision.LONG_WATCH: ("D1_H1_LONG_ALIGNED",),
        SubingDailyWatchDecision.SHORT_WATCH: ("D1_H1_SHORT_ALIGNED",),
        SubingDailyWatchDecision.EXCLUDED: ("D1_H1_DIRECTION_MISMATCH",),
    }[decision]
    daily = _trend(BarFrequency.D1, source_day=source_day)
    hourly = _trend(BarFrequency.H1, source_day=source_day)
    if decision is SubingDailyWatchDecision.SHORT_WATCH:
        daily = _short_trend(daily)
        hourly = _short_trend(hourly)
    elif decision is SubingDailyWatchDecision.EXCLUDED:
        hourly = _short_trend(hourly)
    return SubingDailyWatchItem(
        symbol="jm",
        product_name="焦煤",
        sector="black",
        decision=decision,
        reason_codes=reasons,
        daily=daily,
        hourly=hourly,
        unavailable_reasons=(),
    )


def _short_trend(
    trend: SubingStitchedEmaTrendSnapshot,
) -> SubingStitchedEmaTrendSnapshot:
    from dataclasses import replace

    return replace(
        trend,
        close=Decimal("98"),
        price_side=PriceSide.BELOW,
        slope_5_raw=Decimal("-1"),
        slope_10_raw=Decimal("-2"),
        slope_5_bps_per_bar=Decimal("-1"),
        slope_10_bps_per_bar=Decimal("-2"),
    )


class _Projector:
    def __init__(self, items: dict[date, SubingDailyWatchItem]) -> None:
        self.items = items
        self.calls: list[tuple[str, date]] = []

    def project(self, symbol: str, *, source_trading_day: date) -> SubingDailyWatchItem:
        self.calls.append((symbol, source_trading_day))
        return self.items[source_trading_day]


def _previous(target_day: date) -> date:
    return {
        TARGET_LONG: SOURCE_LONG,
        TARGET_SHORT: SOURCE_SHORT,
    }[target_day]


@pytest.mark.parametrize(
    ("decision", "expected"),
    (
        (SubingDailyWatchDecision.LONG_WATCH, SubingStrategyDirection.LONG_ONLY),
        (SubingDailyWatchDecision.SHORT_WATCH, SubingStrategyDirection.SHORT_ONLY),
        (SubingDailyWatchDecision.EXCLUDED, SubingStrategyDirection.NO_NEW_ENTRY),
        (SubingDailyWatchDecision.UNAVAILABLE, SubingStrategyDirection.UNAVAILABLE),
    ),
)
def test_context_maps_daily_watch_decision_exactly(
    decision: SubingDailyWatchDecision,
    expected: SubingStrategyDirection,
) -> None:
    reasons = ("SOURCE_TRADING_DAY_MISSING",) if decision is SubingDailyWatchDecision.UNAVAILABLE else ()
    projector = _Projector({SOURCE_LONG: _item(decision, source_day=SOURCE_LONG, unavailable_reasons=reasons)})
    resolver = SubingStrategyDirectionContextResolver(
        projector=projector,
        previous_trading_day=_previous,
    )

    result = resolver.resolve("jm", (TARGET_LONG,))[TARGET_LONG]

    assert result.direction is expected
    assert result.source_trading_day == SOURCE_LONG
    assert result.reason_codes == (reasons or _item(decision, source_day=SOURCE_LONG).reason_codes)


def test_one_unavailable_day_does_not_block_another_target_day() -> None:
    projector = _Projector({SOURCE_LONG: _item(SubingDailyWatchDecision.LONG_WATCH, source_day=SOURCE_LONG)})

    def previous(target_day: date) -> date:
        if target_day == TARGET_SHORT:
            raise SubingDailyWatchCalendarError("PREVIOUS_TRADING_DAY_UNAVAILABLE")
        return SOURCE_LONG

    resolver = SubingStrategyDirectionContextResolver(
        projector=projector,
        previous_trading_day=previous,
    )

    result = resolver.resolve("jm", (TARGET_SHORT, TARGET_LONG))

    assert result[TARGET_SHORT].direction is SubingStrategyDirection.UNAVAILABLE
    assert result[TARGET_SHORT].reason_codes == ("PREVIOUS_TRADING_DAY_UNAVAILABLE",)
    assert result[TARGET_LONG].direction is SubingStrategyDirection.LONG_ONLY


def test_source_before_history_floor_is_causal_warmup_without_projection() -> None:
    projector = _Projector({})
    resolver = SubingStrategyDirectionContextResolver(
        projector=projector,
        previous_trading_day=_previous,
        source_floor=lambda symbol: HISTORY_FLOOR,
    )

    result = resolver.resolve("jm", (TARGET_LONG,))[TARGET_LONG]

    assert result.direction is SubingStrategyDirection.UNAVAILABLE
    assert result.source_trading_day is None
    assert result.reason_codes == ("PREVIOUS_TRADING_DAY_UNAVAILABLE",)
    assert projector.calls == []


def test_identity_failure_inside_history_floor_still_escalates() -> None:
    projector = _Projector(
        {
            SOURCE_SHORT: _item(
                SubingDailyWatchDecision.UNAVAILABLE,
                source_day=SOURCE_SHORT,
                unavailable_reasons=("DOMINANT_SEGMENT_UNAVAILABLE",),
            )
        }
    )
    resolver = SubingStrategyDirectionContextResolver(
        projector=projector,
        previous_trading_day=_previous,
        source_floor=lambda symbol: HISTORY_FLOOR,
    )

    with pytest.raises(SubingStrategyContextIdentityError):
        resolver.resolve("jm", (TARGET_SHORT,))


def test_authoritative_daily_watch_identity_failure_escalates() -> None:
    projector = _Projector(
        {
            SOURCE_LONG: _item(
                SubingDailyWatchDecision.UNAVAILABLE,
                source_day=SOURCE_LONG,
                unavailable_reasons=("DATA_IDENTITY_MISMATCH",),
            )
        }
    )
    resolver = SubingStrategyDirectionContextResolver(
        projector=projector,
        previous_trading_day=_previous,
    )

    with pytest.raises(SubingStrategyContextIdentityError):
        resolver.resolve("jm", (TARGET_LONG,))
