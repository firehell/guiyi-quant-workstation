from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import CanonicalBar
from app.market_data.market_trend_focus import (
    FocusBar,
    SwingPivot,
    TrendFocusInputError,
    daily_trend_state,
    evaluate_hot_admission,
    hourly_trend_state,
    replay_lifecycle,
    reduce_swings,
    volume_support,
)


_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(index: int, *, close: str, volume: str = "100") -> CanonicalBar:
    price = Decimal(close)
    return CanonicalBar(
        bar_end=_START + timedelta(days=index),
        trading_day=date(2026, 1, 1) + timedelta(days=index),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(volume),
        turnover=None,
        open_interest=None,
    )


def _focus_bar(
    index: int,
    *,
    high: str,
    low: str,
    close: str | None = None,
    volume: str = "100",
    frequency: str = "15m",
    contract: str = "JM2609",
) -> FocusBar:
    high_value = Decimal(high)
    low_value = Decimal(low)
    close_value = Decimal(close) if close is not None else (high_value + low_value) / 2
    return FocusBar(
        bar=CanonicalBar(
            bar_end=_START + timedelta(minutes=15 * index),
            trading_day=date(2026, 1, 1),
            open=close_value,
            high=high_value,
            low=low_value,
            close=close_value,
            volume=Decimal(volume),
            turnover=None,
            open_interest=None,
        ),
        frequency=frequency,
        physical_contract=contract,
    )


def _pivot(
    kind: str,
    *,
    pivot_index: int,
    confirmed_index: int,
    price: str,
    epoch: int = 0,
    contract: str = "JM2609",
) -> SwingPivot:
    return SwingPivot(
        kind=kind,
        pivot_time=_START + timedelta(minutes=15 * pivot_index),
        confirmed_at=_START + timedelta(minutes=15 * confirmed_index),
        price=Decimal(price),
        physical_contract=contract,
        epoch=epoch,
    )


def test_daily_sma21_requires_23_bars_and_returns_long_for_rising_sma() -> None:
    bars = tuple(_bar(index, close=str(index + 1)) for index in range(23))

    assert daily_trend_state(bars) == "long"


def test_daily_sma21_returns_neutral_below_23_bars() -> None:
    bars = tuple(_bar(index, close=str(index + 1)) for index in range(22))

    assert daily_trend_state(bars) == "neutral"


def test_daily_sma21_returns_short_for_falling_sma() -> None:
    bars = tuple(_bar(index, close=str(100 - index)) for index in range(23))

    assert daily_trend_state(bars) == "short"


def test_daily_sma21_returns_neutral_when_close_does_not_confirm_slope() -> None:
    bars = tuple(_bar(index, close="10") for index in range(23))

    assert daily_trend_state(bars) == "neutral"


def test_hot_admission_accepts_exact_thresholds_when_two_of_three_match() -> None:
    result = evaluate_hot_admission(
        price_change_1d=Decimal("-0.02"),
        volume_ratio20=Decimal("1.50"),
        atr14_percentile252=Decimal("0.79"),
    )

    assert result.available is True
    assert result.current_hot is True
    assert result.hot_count == 2
    assert result.conditions == ("price_move_down", "volume_expansion")


def test_hot_admission_accepts_exact_volatility_threshold() -> None:
    result = evaluate_hot_admission(
        price_change_1d=Decimal("0.01"),
        volume_ratio20=Decimal("1.49"),
        atr14_percentile252=Decimal("0.80"),
    )

    assert result.available is True
    assert result.current_hot is False
    assert result.hot_count == 1
    assert result.conditions == ("high_volatility",)


def test_hot_admission_is_unavailable_when_any_metric_is_missing() -> None:
    result = evaluate_hot_admission(
        price_change_1d=Decimal("0.03"),
        volume_ratio20=None,
        atr14_percentile252=Decimal("0.90"),
    )

    assert result.available is False
    assert result.current_hot is False
    assert result.hot_count == 0
    assert result.conditions == ()


def test_hourly_state_is_mirrored_around_daily_direction() -> None:
    rising = tuple(_bar(index, close=str(index + 1)) for index in range(23))
    falling = tuple(_bar(index, close=str(100 - index)) for index in range(23))

    assert hourly_trend_state(rising, "long") == "continuation"
    assert hourly_trend_state(falling, "long") == "reversal_block"
    assert hourly_trend_state(falling, "short") == "continuation"
    assert hourly_trend_state(rising, "short") == "reversal_block"


def test_hourly_state_uses_pullback_for_insufficient_or_mixed_bars() -> None:
    insufficient = tuple(_bar(index, close=str(index + 1)) for index in range(22))
    flat = tuple(_bar(index, close="10") for index in range(23))

    assert hourly_trend_state(insufficient, "long") == "pullback"
    assert hourly_trend_state(flat, "short") == "pullback"


def test_volume_support_accepts_equal_completed_volumes() -> None:
    bars = (_bar(0, close="10", volume="100"), _bar(1, close="11", volume="100"))

    assert volume_support(bars) is True
    assert volume_support(bars[:1]) is False


def test_swing_high_is_known_only_on_the_later_reversal_bar() -> None:
    bars = (
        _focus_bar(0, high="10", low="8"),
        _focus_bar(1, high="12", low="9"),
        _focus_bar(2, high="13", low="10"),
        _focus_bar(3, high="12", low="9"),
    )

    result = reduce_swings(bars, observed_at=bars[-1].bar.bar_end)

    assert len(result.pivots) == 1
    assert result.pivots[0].kind == "high"
    assert result.pivots[0].pivot_time == bars[2].bar.bar_end
    assert result.pivots[0].confirmed_at == bars[3].bar.bar_end
    assert result.pivots[0].pivot_time < result.pivots[0].confirmed_at


def test_swing_low_is_the_exact_mirror_of_high() -> None:
    bars = (
        _focus_bar(0, high="12", low="10"),
        _focus_bar(1, high="11", low="8"),
        _focus_bar(2, high="10", low="7"),
        _focus_bar(3, high="11", low="8"),
    )

    result = reduce_swings(bars, observed_at=bars[-1].bar.bar_end)

    assert [(pivot.kind, pivot.price) for pivot in result.pivots] == [
        ("low", Decimal("7")),
    ]
    assert result.pivots[0].confirmed_at == bars[3].bar.bar_end


def test_inside_and_equal_bars_do_not_invent_a_swing_direction() -> None:
    bars = (
        _focus_bar(0, high="12", low="8"),
        _focus_bar(1, high="12", low="8"),
        _focus_bar(2, high="11", low="9"),
    )

    result = reduce_swings(bars, observed_at=bars[-1].bar.bar_end)

    assert result.direction == "unresolved"
    assert result.pivots == ()


def test_outside_bar_starts_a_new_epoch_and_clears_the_running_leg() -> None:
    bars = (
        _focus_bar(0, high="10", low="8"),
        _focus_bar(1, high="12", low="9"),
        _focus_bar(2, high="13", low="7"),
        _focus_bar(3, high="14", low="8"),
        _focus_bar(4, high="13", low="7"),
    )

    result = reduce_swings(bars, observed_at=bars[-1].bar.bar_end)

    assert result.epoch == 1
    assert result.pivots[0].epoch == 1
    assert result.pivots[0].pivot_time == bars[3].bar.bar_end
    assert result.pivots[0].confirmed_at == bars[4].bar.bar_end


def test_same_swing_reducer_accepts_5m_bars() -> None:
    bars = tuple(
        _focus_bar(
            index,
            high=high,
            low=low,
            frequency="5m",
        )
        for index, (high, low) in enumerate(
            (("10", "8"), ("12", "9"), ("13", "10"), ("12", "9"))
        )
    )

    result = reduce_swings(bars, observed_at=bars[-1].bar.bar_end)

    assert result.pivots[0].kind == "high"


def test_swing_input_fails_closed_for_order_contract_frequency_and_future() -> None:
    first = _focus_bar(0, high="10", low="8")
    second = _focus_bar(1, high="12", low="9")
    cases = (
        ((second, first), second.bar.bar_end, "BAR_ORDER_INVALID"),
        ((first, _focus_bar(1, high="12", low="9", contract="JM2701")), second.bar.bar_end, "PHYSICAL_CONTRACT_MISMATCH"),
        ((first, _focus_bar(1, high="12", low="9", frequency="5m")), second.bar.bar_end, "FREQUENCY_MISMATCH"),
        ((first, second), first.bar.bar_end, "INCOMPLETE_BAR"),
    )

    for bars, observed_at, expected_code in cases:
        try:
            reduce_swings(bars, observed_at=observed_at)
        except TrendFocusInputError as exc:
            assert exc.code == expected_code
        else:
            raise AssertionError(f"expected {expected_code}")


def test_four_converging_pivots_create_a_frozen_setup_range() -> None:
    bars = tuple(
        _focus_bar(index, high="11", low="9", close="10")
        for index in range(7)
    )
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
        _pivot("high", pivot_index=4, confirmed_index=5, price="10.5"),
        _pivot("low", pivot_index=5, confirmed_index=6, price="9.5"),
    )

    result = replay_lifecycle("long", bars, pivots)

    assert result.state is not None
    assert result.state.stage == "setup"
    assert result.state.trend_range.upper == Decimal("12")
    assert result.state.trend_range.lower == Decimal("8")
    assert result.state.trend_range.created_at == bars[4].bar.bar_end


def test_low_high_low_high_sequence_creates_the_same_range() -> None:
    bars = tuple(
        _focus_bar(index, high="11", low="9", close="10")
        for index in range(5)
    )
    pivots = (
        _pivot("low", pivot_index=0, confirmed_index=1, price="8"),
        _pivot("high", pivot_index=1, confirmed_index=2, price="12"),
        _pivot("low", pivot_index=2, confirmed_index=3, price="9"),
        _pivot("high", pivot_index=3, confirmed_index=4, price="11"),
    )

    result = replay_lifecycle("short", bars, pivots)

    assert result.state is not None
    assert result.state.trend_range.upper == Decimal("12")
    assert result.state.trend_range.lower == Decimal("8")


def test_nonconverging_pivots_do_not_create_setup() -> None:
    bars = tuple(
        _focus_bar(index, high="13", low="7", close="10")
        for index in range(5)
    )
    expanding_high = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="13"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
    )
    expanding_low = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="7"),
    )

    assert replay_lifecycle("long", bars, expanding_high).state is None
    assert replay_lifecycle("long", bars, expanding_low).state is None


def test_setup_opposite_close_invalidates_and_prevents_pivot_reuse() -> None:
    bars = tuple(
        _focus_bar(
            index,
            high="12",
            low="7",
            close="7.9" if index == 5 else "10",
        )
        for index in range(7)
    )
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
    )

    result = replay_lifecycle("long", bars, pivots)

    assert result.state is None
    assert [(item.stage, item.reason) for item in result.transitions] == [
        ("setup", "range_confirmed"),
        (None, "setup_invalidated"),
    ]


def test_breakout_requires_close_and_counts_only_three_later_bars() -> None:
    closes = ("10", "10", "10", "10", "10", "12", "12.1", "12.2", "12.3", "12.4")
    bars = tuple(
        _focus_bar(index, high="12.5", low="9", close=close)
        for index, close in enumerate(closes)
    )
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
    )

    before_breakout = replay_lifecycle("long", bars[:6], pivots)
    breakout = replay_lifecycle("long", bars[:7], pivots)
    confirmed = replay_lifecycle("long", bars, pivots)

    assert before_breakout.state is not None and before_breakout.state.stage == "setup"
    assert breakout.state is not None and breakout.state.stage == "breakout"
    assert breakout.state.confirmation_count == 0
    assert confirmed.state is not None and confirmed.state.stage == "retest"
    assert confirmed.state.confirmation_count == 3
    assert confirmed.state.breakout_at == bars[6].bar.bar_end
    assert confirmed.state.breakout_confirmed_at == bars[9].bar.bar_end


def test_breakout_confirmation_equal_boundary_resets_lifecycle() -> None:
    closes = ("10", "10", "10", "10", "10", "12.1", "12")
    bars = tuple(
        _focus_bar(index, high="12.5", low="9", close=close)
        for index, close in enumerate(closes)
    )
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
    )

    result = replay_lifecycle("long", bars, pivots)

    assert result.state is None
    assert result.transitions[-1].reason == "breakout_confirmation_failed"


def _long_retest_fixture(
    *,
    ready_close: str = "15.1",
    ready_volume: str = "200",
    retest_low: str = "11",
) -> tuple[tuple[FocusBar, ...], tuple[SwingPivot, ...]]:
    closes = (
        "10", "10", "10", "10", "10",
        "12.1", "12.2", "12.3", "12.4",
        "14", "14", "13", "13", ready_close,
    )
    bars = tuple(
        _focus_bar(
            index,
            high="16",
            low="7",
            close=close,
            volume=(ready_volume if index == 13 else "100"),
        )
        for index, close in enumerate(closes)
    )
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
        _pivot("high", pivot_index=9, confirmed_index=10, price="15"),
        _pivot("low", pivot_index=11, confirmed_index=12, price=retest_low),
    )
    return bars, pivots


def test_retest_shadow_may_enter_range_and_later_rebreak_enters_ready() -> None:
    bars, pivots = _long_retest_fixture()

    result = replay_lifecycle("long", bars, pivots)

    assert result.state is not None
    assert result.state.stage == "ready"
    assert result.state.retest_held is True
    assert result.state.rebreak_reference == Decimal("15")
    assert result.state.ready_at == bars[13].bar.bar_end
    assert result.state.ready_invalidation == Decimal("11")
    assert result.state.volume_confirmed is True


def test_retest_close_at_original_range_boundary_invalidates() -> None:
    bars, pivots = _long_retest_fixture()
    changed = list(bars)
    changed[11] = _focus_bar(11, high="16", low="7", close="12")

    result = replay_lifecycle("long", changed, pivots)

    assert result.state is None
    assert result.transitions[-1].reason == "retest_range_invalidated"


def test_ready_rebreak_must_be_strictly_after_retest_confirmation() -> None:
    bars, pivots = _long_retest_fixture()
    same_boundary = list(bars[:13])
    same_boundary[12] = _focus_bar(12, high="16", low="7", close="15.1")

    result = replay_lifecycle("long", same_boundary, pivots)

    assert result.state is not None
    assert result.state.stage == "retest"
    assert result.state.retest_held is True


def test_ready_survives_without_2x_volume_but_records_false_quality_fact() -> None:
    bars, pivots = _long_retest_fixture(ready_volume="199")

    result = replay_lifecycle("long", bars, pivots)

    assert result.state is not None
    assert result.state.stage == "ready"
    assert result.state.volume_confirmed is False


def test_ready_strict_pivot_invalidation_ends_lifecycle() -> None:
    bars, pivots = _long_retest_fixture(retest_low="13")
    changed = list(bars)
    changed.append(_focus_bar(14, high="14", low="12.1", close="12.5"))

    result = replay_lifecycle("long", changed, pivots)

    assert result.state is None
    assert result.transitions[-1].reason == "ready_invalidated"


def test_short_retest_and_ready_are_exact_mirrors() -> None:
    long_bars, long_pivots = _long_retest_fixture()
    mirrored_bars = tuple(
        _focus_bar(
            index,
            high=str(Decimal("30") - bar.bar.low),
            low=str(Decimal("30") - bar.bar.high),
            close=str(Decimal("30") - bar.bar.close),
            volume=str(bar.bar.volume),
        )
        for index, bar in enumerate(long_bars)
    )
    mirrored_pivots = tuple(
        SwingPivot(
            kind="low" if pivot.kind == "high" else "high",
            pivot_time=pivot.pivot_time,
            confirmed_at=pivot.confirmed_at,
            price=Decimal("30") - pivot.price,
            physical_contract=pivot.physical_contract,
            epoch=pivot.epoch,
        )
        for pivot in long_pivots
    )

    result = replay_lifecycle("short", mirrored_bars, mirrored_pivots)

    assert result.state is not None
    assert result.state.stage == "ready"
    assert result.state.rebreak_reference == Decimal("15")
    assert result.state.ready_invalidation == Decimal("19")
