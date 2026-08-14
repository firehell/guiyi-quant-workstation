from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorStatus,
    calculate_subing_factor,
    calculate_subing_factor_series,
)
from guiyi_quant.indicators import get_indicator, require_formal_policy


_SCOPED_SIGNAL_MACD_EQUIVALENCE_TARGET = (
    "sma_window",
    2,
    "fast12_slow26_signal9",
    True,
)


def _bars_from_closes(
    closes: list[Decimal],
    *,
    previous_volume: Decimal = Decimal("100"),
    final_volume: Decimal = Decimal("300"),
) -> tuple[CanonicalBar, ...]:
    start = datetime(2026, 8, 3, 1, tzinfo=UTC)
    bars: list[CanonicalBar] = []
    for index, close in enumerate(closes):
        volume = Decimal("200")
        if index == len(closes) - 2:
            volume = previous_volume
        elif index == len(closes) - 1:
            volume = final_volume
        bars.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=5 * index),
                trading_day=date(2026, 8, 3),
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=volume,
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(bars)


def _ready_bars(
    *,
    count: int = 48,
    previous_volume: Decimal = Decimal("100"),
    final_volume: Decimal = Decimal("300"),
) -> tuple[CanonicalBar, ...]:
    closes = [Decimal("100") + Decimal(index) for index in range(count)]
    return _bars_from_closes(
        closes,
        previous_volume=previous_volume,
        final_volume=final_volume,
    )


def _calculate(bars: tuple[CanonicalBar, ...]):
    return calculate_subing_factor(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )


def test_ready_factor_preserves_raw_observation_values_and_identity() -> None:
    bars = _ready_bars(count=48, previous_volume=Decimal("100"), final_volume=Decimal("300"))

    series = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    result = _calculate(bars)

    assert len(series) == len(bars)
    assert series[-1] == result
    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.timeframe is BarFrequency.M5
    assert result.snapshot.contract == "JM2609"
    assert result.snapshot.segment_start_trading_day == date(2026, 8, 3)
    assert result.snapshot.bar_source == "canonical"
    assert result.snapshot.price_side is PriceSide.ABOVE
    assert result.snapshot.slope_5_raw == Decimal("1")
    assert result.snapshot.slope_10_raw == Decimal("1")
    assert result.snapshot.slope_5_bps_per_bar == Decimal("74.07407407407407407407407407")
    assert result.snapshot.slope_10_bps_per_bar == Decimal("75.47169811320754716981132075")
    assert result.snapshot.volume_ratio_prev == Decimal("3")
    with pytest.raises(FrozenInstanceError):
        result.snapshot.close = Decimal("0")  # type: ignore[misc]


def test_segment_local_warmup_is_insufficient_until_previous_macd_is_ready() -> None:
    bars = _ready_bars(count=34)

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.snapshot is None


@pytest.mark.parametrize(
    ("final_close", "expected_cross"),
    (
        (Decimal("101"), MacdCross.GOLDEN),
        (Decimal("99"), MacdCross.DEAD),
    ),
)
def test_macd_cross_accepts_equality_on_the_previous_bar(
    final_close: Decimal,
    expected_cross: MacdCross,
) -> None:
    bars = _bars_from_closes([Decimal("100")] * 47 + [final_close])

    series = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    previous = series[-2]
    result = series[-1]

    assert previous.status is SubingFactorStatus.READY
    assert previous.snapshot is not None
    assert previous.snapshot.macd_dif == previous.snapshot.macd_dea
    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.macd_cross is expected_cross
    if expected_cross is MacdCross.GOLDEN:
        assert result.snapshot.macd_dif > result.snapshot.macd_dea
    else:
        assert result.snapshot.macd_dif < result.snapshot.macd_dea


def test_historical_and_completed_live_have_identical_confirmed_factor_math() -> None:
    bars = _ready_bars()
    historical = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    completed_live = calculate_subing_factor_series(
        bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="live",
    )

    assert len(historical) == len(completed_live)
    for historical_result, live_result in zip(historical, completed_live, strict=True):
        assert historical_result.status is live_result.status
        if historical_result.snapshot is None:
            assert live_result.snapshot is None
            continue
        assert live_result.snapshot is not None
        assert replace(live_result.snapshot, bar_source="canonical") == historical_result.snapshot


@pytest.mark.parametrize("previous_volume", (Decimal("0"), Decimal("-1")))
def test_non_positive_previous_volume_keeps_factor_ready_but_ratio_unavailable(
    previous_volume: Decimal,
) -> None:
    bars = _ready_bars(previous_volume=Decimal("0"), final_volume=Decimal("300"))
    # CanonicalBar rejects negative volume at construction. Corrupt only this
    # test input to prove the pure Factor boundary remains fail-closed if an
    # invalid object ever bypasses that upstream contract.
    object.__setattr__(bars[-2], "volume", previous_volume)

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.previous_volume == previous_volume
    assert result.snapshot.volume_ratio_prev is None


def test_zero_close_makes_normalized_zero_distance_insufficient() -> None:
    bars = _bars_from_closes([Decimal("100")] * 47 + [Decimal("0")])

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.snapshot is None


def test_constant_price_reports_equal_side_without_a_cross() -> None:
    bars = _bars_from_closes([Decimal("100")] * 48)

    result = _calculate(bars)

    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.price_side is PriceSide.EQUAL
    assert result.snapshot.macd_cross is MacdCross.NONE
    assert result.snapshot.macd_zero_distance_bps == Decimal("0")


@pytest.mark.parametrize("bad_index", (12, 13))
def test_bar_end_must_be_strictly_increasing(bad_index: int) -> None:
    bars = list(_ready_bars())
    replacement_end = bars[bad_index - 1].bar_end
    if bad_index == 13:
        replacement_end -= timedelta(minutes=1)
    original = bars[bad_index]
    bars[bad_index] = CanonicalBar(
        bar_end=replacement_end,
        trading_day=original.trading_day,
        open=original.open,
        high=original.high,
        low=original.low,
        close=original.close,
        volume=original.volume,
        turnover=original.turnover,
        open_interest=original.open_interest,
    )

    with pytest.raises(ValueError, match="bar_end"):
        _calculate(tuple(bars))


def test_input_before_segment_start_is_rejected_instead_of_inheriting_state() -> None:
    bars = _ready_bars()

    with pytest.raises(ValueError, match="segment_start_trading_day"):
        calculate_subing_factor(
            bars,
            timeframe=BarFrequency.M5,
            contract="JM2609",
            segment_start_trading_day=date(2026, 8, 4),
            latest_bar_source="canonical",
        )


def test_factor_macd_matches_scoped_signal_equivalence_target_without_promotion() -> None:
    policy = require_formal_policy("web_macd_legacy_v1", consumer="subing_factor_observation")
    definition = get_indicator("macd")

    assert policy.policy_id == definition.formal_policy_id
    assert (
        policy.seed_policy,
        policy.histogram_scale,
        policy.lookback,
        policy.confirmed_only,
    ) == _SCOPED_SIGNAL_MACD_EQUIVALENCE_TARGET
    assert (
        definition.seed_policy,
        definition.histogram_scale,
        policy.lookback,
        definition.confirmed_only,
    ) == _SCOPED_SIGNAL_MACD_EQUIVALENCE_TARGET
    assert definition.default_parameters["fast"] == 12
    assert definition.default_parameters["slow"] == 26
    assert definition.default_parameters["signal"] == 9
    assert definition.status == "compatibility_validated"
    assert definition.backtest_capable is False
    assert definition.live_capable is False
    assert definition.alert_capable is False
    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_NOT_ALLOWED"):
        require_formal_policy("web_macd_legacy_v1", consumer="subing_signal")
