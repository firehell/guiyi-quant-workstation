from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import DominantContractSummary
from app.market_data.market_radar import MarketRadarSnapshot, RadarItem
from app.market_data.market_read_service import MarketDisplaySnapshot, MarketReadState
from app.market_data.market_trend_focus import (
    FocusBar,
    SwingPivot,
    TrendFocusInputError,
    build_market_trend_focus_snapshot,
    daily_trend_state,
    evaluate_hot_admission,
    hourly_trend_state,
    replay_lifecycle,
    replay_trend_focus,
    sort_opportunities,
    reduce_swings,
    volume_support,
)
from app.market_data.research_metrics import ResearchMetrics


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
            bar_end=_START + timedelta(
                minutes=(5 if frequency == "5m" else 15) * index
            ),
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
    minute_step: int = 15,
) -> SwingPivot:
    return SwingPivot(
        kind=kind,
        pivot_time=_START + timedelta(minutes=minute_step * pivot_index),
        confirmed_at=_START + timedelta(minutes=minute_step * confirmed_index),
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


def test_range_creation_bar_immediately_consumes_close_with_exact_boundaries() -> None:
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12"),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8"),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11"),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9"),
    )
    cases = (
        ("long", "7.9", None, "setup_invalidated"),
        ("long", "8", "setup", "range_confirmed"),
        ("long", "12", "setup", "range_confirmed"),
        ("long", "12.1", "breakout", "range_breakout"),
        ("short", "12.1", None, "setup_invalidated"),
        ("short", "12", "setup", "range_confirmed"),
        ("short", "8", "setup", "range_confirmed"),
        ("short", "7.9", "breakout", "range_breakout"),
    )

    for direction, close, expected_stage, expected_reason in cases:
        bars = tuple(
            _focus_bar(
                index,
                high="13",
                low="7",
                close=close if index == 4 else "10",
            )
            for index in range(5)
        )
        result = replay_lifecycle(direction, bars, pivots)

        assert (result.state.stage if result.state is not None else None) == expected_stage
        assert result.transitions[-1].reason == expected_reason
        if expected_reason != "range_confirmed":
            assert result.transitions[-1].transition_at == bars[4].bar.bar_end


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


def _five_minute_entry_fixture(
    *,
    trigger_volume: str = "200",
    trigger_close: str = "15.1",
) -> tuple[tuple[FocusBar, ...], tuple[SwingPivot, ...]]:
    bars = tuple(
        _focus_bar(
            index,
            high="16",
            low="12",
            close=(trigger_close if index == 42 else "14"),
            volume=(trigger_volume if index == 42 else "100"),
            frequency="5m",
        )
        for index in range(39, 43)
    )
    pivots = (
        _pivot(
            "high",
            pivot_index=40,
            confirmed_index=41,
            price="15",
            minute_step=5,
        ),
    )
    return bars, pivots


def test_5m_strict_after_rebreak_with_exact_2x_volume_starts_running() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_5m, pivots_5m = _five_minute_entry_fixture()

    result = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )

    assert result.state is not None
    assert result.state.stage == "running"
    assert result.state.five_minute_confirmed is True
    assert result.state.entry_confirmed_at == bars_5m[-1].bar.bar_end
    assert result.state.running_at == bars_5m[-1].bar.bar_end


def test_5m_reference_at_or_before_ready_is_not_reused() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_5m = tuple(
        _focus_bar(
            index,
            high="16",
            low="12",
            close=("15.1" if index == 42 else "14"),
            volume=("200" if index == 42 else "100"),
            frequency="5m",
        )
        for index in range(38, 43)
    )
    prior_pivot = _pivot(
        "high",
        pivot_index=38,
        confirmed_index=39,
        price="15",
        minute_step=5,
    )

    result = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=(prior_pivot,),
    )

    assert result.state is not None
    assert result.state.stage == "ready"
    assert result.state.five_minute_confirmed is False


def test_5m_trigger_must_be_later_than_reference_confirmation() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_5m = tuple(
        _focus_bar(
            index,
            high="16",
            low="12",
            close=("15.1" if index == 41 else "14"),
            volume=("200" if index == 41 else "100"),
            frequency="5m",
        )
        for index in range(39, 42)
    )
    pivot = _pivot(
        "high",
        pivot_index=40,
        confirmed_index=41,
        price="15",
        minute_step=5,
    )

    result = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=(pivot,),
    )

    assert result.state is not None
    assert result.state.stage == "ready"
    assert result.state.entry_reference == Decimal("15")


def test_5m_rebreak_below_2x_volume_does_not_confirm() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_5m, pivots_5m = _five_minute_entry_fixture(trigger_volume="199")

    result = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )

    assert result.state is not None
    assert result.state.stage == "ready"
    assert result.state.entry_reference == Decimal("15")


def test_first_post_ready_15m_trend_pivot_closes_entry_window_without_5m() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_15m = bars_15m + (_focus_bar(14, high="16", low="12", close="14"),)
    pivots_15m = pivots_15m + (
        _pivot("high", pivot_index=13, confirmed_index=14, price="16"),
    )

    result = replay_lifecycle("long", bars_15m, pivots_15m)

    assert result.state is not None
    assert result.state.stage == "running"
    assert result.state.five_minute_confirmed is False
    assert result.state.running_at == bars_15m[-1].bar.bar_end


def test_same_boundary_15m_pivot_closes_before_5m_confirmation() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_15m = bars_15m + (_focus_bar(14, high="16", low="12", close="14"),)
    pivots_15m = pivots_15m + (
        _pivot("high", pivot_index=13, confirmed_index=14, price="16"),
    )
    bars_5m, pivots_5m = _five_minute_entry_fixture()

    result = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )

    assert result.state is not None
    assert result.state.stage == "running"
    assert result.state.five_minute_confirmed is False
    assert result.state.running_at == bars_15m[-1].bar.bar_end


def test_running_uses_completed_close_not_shadow_for_weakening() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    bars_15m = bars_15m + (
        _focus_bar(14, high="14", low="12", close="13"),
        _focus_bar(15, high="14", low="10", close="11.1"),
    )
    bars_5m, pivots_5m = _five_minute_entry_fixture()

    result = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )

    assert result.state is not None
    assert result.state.stage == "running"


def test_running_close_below_latest_low_weakens_and_causal_rebreak_recovers() -> None:
    bars_15m, pivots_15m = _long_retest_fixture()
    continuation = tuple(
        _focus_bar(
            index,
            high="15",
            low="9",
            close={15: "10.5", 20: "14.1"}.get(index, "13"),
        )
        for index in range(14, 21)
    )
    bars_15m = bars_15m + continuation
    pivots_15m = pivots_15m + (
        _pivot("low", pivot_index=16, confirmed_index=17, price="10"),
        _pivot("high", pivot_index=18, confirmed_index=19, price="14"),
    )
    bars_5m, pivots_5m = _five_minute_entry_fixture()

    weakened = replay_lifecycle(
        "long",
        bars_15m[:16],
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )
    recovered = replay_lifecycle(
        "long",
        bars_15m,
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )
    awaiting_rebreak = replay_lifecycle(
        "long",
        bars_15m[:20],
        pivots_15m,
        bars_5m=bars_5m,
        pivots_5m=pivots_5m,
    )

    assert weakened.state is not None and weakened.state.stage == "weakening"
    assert weakened.state.weakened_at == bars_15m[15].bar.bar_end
    assert awaiting_rebreak.state is not None
    assert awaiting_rebreak.state.stage == "weakening"
    assert awaiting_rebreak.state.recovery_reference == Decimal("14")
    assert recovered.state is not None and recovered.state.stage == "running"
    assert recovered.state.last_transition_at == bars_15m[-1].bar.bar_end
    assert recovered.transitions[-1].reason == "trend_recovered"


def test_short_5m_entry_is_the_exact_price_axis_mirror() -> None:
    long_bars, long_pivots = _long_retest_fixture()
    long_five_bars, long_five_pivots = _five_minute_entry_fixture()
    short_bars = tuple(
        FocusBar(
            bar=CanonicalBar(
                bar_end=item.bar.bar_end,
                trading_day=item.bar.trading_day,
                open=Decimal("30") - item.bar.open,
                high=Decimal("30") - item.bar.low,
                low=Decimal("30") - item.bar.high,
                close=Decimal("30") - item.bar.close,
                volume=item.bar.volume,
                turnover=None,
                open_interest=None,
            ),
            frequency=item.frequency,
            physical_contract=item.physical_contract,
        )
        for item in long_bars
    )
    short_pivots = tuple(
        replace(
            pivot,
            kind="low" if pivot.kind == "high" else "high",
            price=Decimal("30") - pivot.price,
        )
        for pivot in long_pivots
    )
    short_five_bars = tuple(
        FocusBar(
            bar=CanonicalBar(
                bar_end=item.bar.bar_end,
                trading_day=item.bar.trading_day,
                open=Decimal("30") - item.bar.open,
                high=Decimal("30") - item.bar.low,
                low=Decimal("30") - item.bar.high,
                close=Decimal("30") - item.bar.close,
                volume=item.bar.volume,
                turnover=None,
                open_interest=None,
            ),
            frequency=item.frequency,
            physical_contract=item.physical_contract,
        )
        for item in long_five_bars
    )
    short_five_pivots = tuple(
        replace(pivot, kind="low", price=Decimal("30") - pivot.price)
        for pivot in long_five_pivots
    )

    result = replay_lifecycle(
        "short",
        short_bars,
        short_pivots,
        bars_5m=short_five_bars,
        pivots_5m=short_five_pivots,
    )

    assert result.state is not None
    assert result.state.stage == "running"
    assert result.state.five_minute_confirmed is True
    assert result.state.entry_reference == Decimal("15")


def test_full_bar_replay_builds_setup_from_private_causal_swings() -> None:
    bars = tuple(
        _focus_bar(index, high=high, low=low, close=close)
        for index, (high, low, close) in enumerate(
            (
                ("10", "8", "9"),
                ("12", "9", "10"),
                ("11", "7", "8"),
                ("11.5", "8", "9"),
                ("11", "7.5", "9"),
                ("11.2", "8.5", "9"),
            )
        )
    )

    result = replay_trend_focus("long", bars, (), observed_at=bars[-1].bar.bar_end)

    assert result.state is not None
    assert result.state.stage == "setup"
    assert result.state.trend_range.upper == Decimal("12")
    assert result.state.trend_range.lower == Decimal("7")


def test_future_bars_never_rewrite_prior_transition_prefixes() -> None:
    bars, pivots = _long_retest_fixture()
    full = replay_lifecycle("long", bars, pivots)

    for cutoff_index, cutoff_bar in enumerate(bars, start=1):
        prefix = replay_lifecycle("long", bars[:cutoff_index], pivots)
        expected = tuple(
            transition
            for transition in full.transitions
            if transition.transition_at <= cutoff_bar.bar.bar_end
        )
        assert prefix.transitions == expected

    assert replay_lifecycle("long", bars, pivots).state == full.state


def test_raw_15m_5m_replay_preserves_every_transition_under_all_cutoffs() -> None:
    raw_fifteen, raw_five = _running_intraday_pages()
    fifteen = tuple(FocusBar(bar, BarFrequency.M15, "JM2609") for bar in raw_fifteen)
    five = tuple(FocusBar(bar, BarFrequency.M5, "JM2609") for bar in raw_five)
    cutoffs = tuple(
        sorted({item.bar.bar_end for item in fifteen} | {item.bar.bar_end for item in five})
    )
    full = replay_trend_focus("long", fifteen, five, observed_at=cutoffs[-1])

    assert full.state is not None and full.state.stage == "running"
    assert {item.stage for item in full.transitions} >= {
        "setup",
        "breakout",
        "retest",
        "ready",
        "running",
    }
    for cutoff in cutoffs:
        prefix = replay_trend_focus(
            "long",
            tuple(item for item in fifteen if item.bar.bar_end <= cutoff),
            tuple(item for item in five if item.bar.bar_end <= cutoff),
            observed_at=cutoff,
        )
        expected = tuple(
            item for item in full.transitions if item.transition_at <= cutoff
        )
        assert prefix.transitions == expected


def test_outside_reset_swing_facts_are_prefix_invariant() -> None:
    bars = tuple(
        _focus_bar(index, high=high, low=low)
        for index, (high, low) in enumerate(
            (("10", "8"), ("12", "9"), ("13", "10"), ("14", "7"), ("13", "8"), ("12", "7"), ("13", "8"))
        )
    )
    full = reduce_swings(bars, observed_at=bars[-1].bar.bar_end)

    assert full.epoch == 1
    for cutoff_index, cutoff_bar in enumerate(bars, start=1):
        prefix = reduce_swings(
            bars[:cutoff_index], observed_at=cutoff_bar.bar.bar_end
        )
        assert prefix.pivots == tuple(
            pivot for pivot in full.pivots if pivot.confirmed_at <= cutoff_bar.bar.bar_end
        )


def test_short_running_weakening_and_recovery_are_price_axis_mirrors() -> None:
    long_bars, long_pivots = _long_retest_fixture()
    continuation = tuple(
        _focus_bar(
            index,
            high="15",
            low="9",
            close={15: "10.5", 20: "14.1"}.get(index, "13"),
        )
        for index in range(14, 21)
    )
    long_bars += continuation
    long_pivots += (
        _pivot("low", pivot_index=16, confirmed_index=17, price="10"),
        _pivot("high", pivot_index=18, confirmed_index=19, price="14"),
    )
    long_five_bars, long_five_pivots = _five_minute_entry_fixture()
    short_bars = tuple(
        FocusBar(
            CanonicalBar(
                bar_end=item.bar.bar_end,
                trading_day=item.bar.trading_day,
                open=Decimal("30") - item.bar.open,
                high=Decimal("30") - item.bar.low,
                low=Decimal("30") - item.bar.high,
                close=Decimal("30") - item.bar.close,
                volume=item.bar.volume,
                turnover=None,
                open_interest=None,
            ),
            item.frequency,
            item.physical_contract,
        )
        for item in long_bars
    )
    short_pivots = tuple(
        replace(
            pivot,
            kind="low" if pivot.kind == "high" else "high",
            price=Decimal("30") - pivot.price,
        )
        for pivot in long_pivots
    )
    short_five_bars = tuple(
        FocusBar(
            CanonicalBar(
                bar_end=item.bar.bar_end,
                trading_day=item.bar.trading_day,
                open=Decimal("30") - item.bar.open,
                high=Decimal("30") - item.bar.low,
                low=Decimal("30") - item.bar.high,
                close=Decimal("30") - item.bar.close,
                volume=item.bar.volume,
                turnover=None,
                open_interest=None,
            ),
            item.frequency,
            item.physical_contract,
        )
        for item in long_five_bars
    )
    short_five_pivots = tuple(
        replace(
            pivot,
            kind="low" if pivot.kind == "high" else "high",
            price=Decimal("30") - pivot.price,
        )
        for pivot in long_five_pivots
    )

    weakened = replay_lifecycle(
        "short",
        short_bars[:16],
        short_pivots,
        bars_5m=short_five_bars,
        pivots_5m=short_five_pivots,
    )
    awaiting_rebreak = replay_lifecycle(
        "short",
        short_bars[:20],
        short_pivots,
        bars_5m=short_five_bars,
        pivots_5m=short_five_pivots,
    )
    recovered = replay_lifecycle(
        "short",
        short_bars,
        short_pivots,
        bars_5m=short_five_bars,
        pivots_5m=short_five_pivots,
    )

    assert weakened.state is not None and weakened.state.stage == "weakening"
    assert awaiting_rebreak.state is not None
    assert awaiting_rebreak.state.stage == "weakening"
    assert awaiting_rebreak.state.recovery_reference == Decimal("16")
    assert recovered.state is not None and recovered.state.stage == "running"
    assert recovered.transitions[-1].reason == "trend_recovered"


def test_physical_contract_replay_is_recomputed_without_lifecycle_inheritance() -> None:
    raw_fifteen, raw_five = _running_intraday_pages()
    bars_a = tuple(FocusBar(bar, BarFrequency.M15, "JM2609") for bar in raw_fifteen)
    five_a = tuple(FocusBar(bar, BarFrequency.M5, "JM2609") for bar in raw_five)
    bars_b = tuple(replace(item, physical_contract="JM2701") for item in bars_a)
    five_b = tuple(replace(item, physical_contract="JM2701") for item in five_a)
    observed_at = max(bars_a[-1].bar.bar_end, five_a[-1].bar.bar_end)

    result_a = replay_trend_focus("long", bars_a, five_a, observed_at=observed_at)
    result_b = replay_trend_focus("long", bars_b, five_b, observed_at=observed_at)

    assert result_a.state is not None and result_b.state is not None
    assert result_a.state.physical_contract == "JM2609"
    assert result_b.state.physical_contract == "JM2701"
    assert result_a.transitions == result_b.transitions


def test_outside_epoch_prevents_old_and_new_pivots_from_forming_one_range() -> None:
    bars = tuple(
        _focus_bar(index, high="12", low="7", close="10")
        for index in range(5)
    )
    pivots = (
        _pivot("high", pivot_index=0, confirmed_index=1, price="12", epoch=0),
        _pivot("low", pivot_index=1, confirmed_index=2, price="8", epoch=0),
        _pivot("high", pivot_index=2, confirmed_index=3, price="11", epoch=1),
        _pivot("low", pivot_index=3, confirmed_index=4, price="9", epoch=1),
    )

    assert replay_lifecycle("long", bars, pivots).state is None


def _metrics(*, volume_ratio20: Decimal | None = Decimal("1.50")) -> ResearchMetrics:
    return ResearchMetrics(
        price_change_1d=Decimal("0.03"),
        price_change_5d=Decimal("0.05"),
        daily_trend="up",
        weekly_trend="up",
        position20=Decimal("0.8"),
        distance_to_20d_high=Decimal("-0.01"),
        distance_to_20d_low=Decimal("0.2"),
        volume_ratio20=volume_ratio20,
        oi_change_1d=Decimal("0.1"),
        turnover_change_5d=Decimal("0.2"),
        atr14_percentile252=Decimal("0.80"),
    )


def _radar_snapshot(
    *,
    freshness_state: str = "current",
    metrics: ResearchMetrics | None = None,
) -> MarketRadarSnapshot:
    item = RadarItem(
        symbol="jm",
        product_name="焦煤",
        sector="black",
        metrics=metrics or _metrics(),
        turnover=Decimal("1000"),
        reason_codes=("price_move_up", "volume_expansion", "high_volatility"),
    )
    degraded = freshness_state == "degraded"
    return MarketRadarSnapshot(
        status="degraded" if degraded else "ready",
        target_as_of=date(2026, 1, 24),
        data_as_of=date(2026, 1, 23),
        freshness_state=freshness_state,
        freshness_message="数据异常" if degraded else "当前完整",
        active_count=1,
        participant_count=0 if degraded else 1,
        stale=("jm",) if degraded else (),
        unavailable=(),
        items=() if degraded else (item,),
        attention=(),
        sector_summary=(),
    )


def _page(request: SeriesPageQuery, bars: tuple[CanonicalBar, ...]) -> MarketSeriesPageResult:
    return MarketSeriesPageResult(
        request_identity={
            "series_kind": request.series_kind.value,
            "symbol": request.symbol,
            "contract": request.contract,
            "frequency": request.frequency.value,
            "before": None,
            "limit": request.limit,
        },
        bars=bars,
        canonical_coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
        has_more_before=False,
        next_before=None,
        resolved_contract_segments=(),
    )


class _FakeMarketData:
    def __init__(self, pages: dict[tuple[SeriesKind, BarFrequency], tuple[CanonicalBar, ...]]) -> None:
        self.pages = pages
        self.calls: list[SeriesPageQuery] = []

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        self.calls.append(request)
        return _page(request, self.pages[(request.series_kind, request.frequency)])


class _FakeMarketRead:
    def __init__(
        self,
        *,
        phase: str = "CLOSED",
        live_available: bool = False,
        live_contract: str | None = None,
        source: str = "none",
        bars: tuple[CanonicalBar, ...] = (),
    ) -> None:
        self.phase = phase
        self.live_available = live_available
        self.live_contract = live_contract
        self.source = source
        self.bars = bars
        self.calls = 0

    def display_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> MarketDisplaySnapshot:
        self.calls += 1
        live_phase = self.phase in {"TRADING", "BREAK"}
        state = MarketReadState(
            symbol=identity.symbol,
            series_kind=identity.series_kind.value,
            frequency=identity.frequency.value,
            operational=True,
            phase=self.phase,
            trading_day=date(2026, 1, 23),
            live_eligible=live_phase and self.live_contract == identity.contract,
            live_available=self.live_available,
            live_contract=self.live_contract,
            canonical_end=after,
            after_market={},
        )
        return MarketDisplaySnapshot(
            state=state,
            source=self.source,
            trading_day=date(2026, 1, 23) if self.source != "none" else None,
            contract=self.live_contract if self.source != "none" else None,
            bars=self.bars,
        )


def _snapshot_pages() -> dict[tuple[SeriesKind, BarFrequency], tuple[CanonicalBar, ...]]:
    daily = tuple(_bar(index, close=str(index + 1)) for index in range(23)) + (
        _bar(23, close="1"),
    )
    hourly = tuple(_bar(index, close=str(index + 1)) for index in range(23))
    fifteen = tuple(
        value.bar
        for value in (
            _focus_bar(0, high="10", low="8", close="9"),
            _focus_bar(1, high="12", low="9", close="10"),
            _focus_bar(2, high="11", low="7", close="8"),
            _focus_bar(3, high="11.5", low="8", close="9"),
            _focus_bar(4, high="11", low="7.5", close="9"),
            _focus_bar(5, high="11.2", low="8.5", close="9"),
        )
    )
    five = tuple(
        _focus_bar(index, high="10", low="8", close="9", frequency="5m").bar
        for index in range(3)
    )
    return {
        (SeriesKind.ACTUAL_DOMINANT, BarFrequency.D1): daily,
        (SeriesKind.CONTRACT, BarFrequency.H1): hourly,
        (SeriesKind.CONTRACT, BarFrequency.M15): fifteen,
        (SeriesKind.CONTRACT, BarFrequency.M5): five,
    }


def _dominants() -> dict[str, DominantContractSummary]:
    return {
        "jm": DominantContractSummary(
            symbol="jm",
            product_name="焦煤",
            sector="black",
            exchange="DCE",
            actual_contract="JM2609",
            dominant_mapping_date=date(2026, 1, 23),
        )
    }


def test_snapshot_builds_hot_long_setup_from_radar_aligned_d1_and_current_contract() -> None:
    market_data = _FakeMarketData(_snapshot_pages())
    market_read = _FakeMarketRead()
    observed_at = datetime(2026, 1, 24, tzinfo=UTC)

    result = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(),
        market_data=market_data,
        market_read=market_read,
        dominants=_dominants(),
        now=observed_at,
    )

    assert result.status == "ready"
    assert result.observed_at == observed_at
    assert len(result.long_opportunities) == 1
    item = result.long_opportunities[0]
    assert item.symbol == "jm"
    assert item.physical_contract == "JM2609"
    assert item.direction == "long"
    assert item.stage == "setup"
    assert item.hot_count == 3
    assert item.hourly_state == "continuation"
    assert item.next_level == Decimal("12")
    assert item.invalidation_level == Decimal("7")
    assert [call.limit for call in market_data.calls] == [24, 23, 2000, 2000]
    assert market_read.calls == 3


def test_global_radar_degraded_short_circuits_all_market_reads() -> None:
    market_data = _FakeMarketData({})
    market_read = _FakeMarketRead()

    result = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(freshness_state="degraded"),
        market_data=market_data,
        market_read=market_read,
        dominants=_dominants(),
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )

    assert result.status == "degraded"
    assert result.long_opportunities == ()
    assert result.short_opportunities == ()
    assert result.running_trends == ()
    assert result.weakening_trends == ()
    assert result.unavailable[0].code == "RADAR_DEGRADED"
    assert market_data.calls == []
    assert market_read.calls == 0


def test_trading_snapshot_fails_closed_when_live_is_unavailable() -> None:
    market_data = _FakeMarketData(_snapshot_pages())
    market_read = _FakeMarketRead(
        phase="TRADING",
        live_available=False,
        live_contract="JM2609",
    )

    result = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(),
        market_data=market_data,
        market_read=market_read,
        dominants=_dominants(),
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )

    assert result.long_opportunities == ()
    assert result.unavailable[0].symbol == "jm"
    assert result.unavailable[0].code == "LIVE_UNAVAILABLE"


def _running_intraday_pages() -> tuple[tuple[CanonicalBar, ...], tuple[CanonicalBar, ...]]:
    fifteen_specs = (
        ("10", "8", "9", "100"),
        ("12", "9", "10", "100"),
        ("11", "7", "8", "100"),
        ("11.5", "8", "9", "100"),
        ("11", "7.5", "9", "100"),
        ("11.2", "8.5", "9", "100"),
        ("12.5", "9", "12.1", "100"),
        ("12.6", "9.5", "12.2", "100"),
        ("12.7", "10", "12.3", "100"),
        ("13", "10.5", "12.4", "100"),
        ("12.8", "9.5", "12.5", "100"),
        ("13.5", "10", "13", "100"),
        ("13.6", "10.5", "13.1", "200"),
        ("14", "11", "13", "100"),
    )
    fifteen = tuple(
        _focus_bar(
            index,
            high=high,
            low=low,
            close=close,
            volume=volume,
        ).bar
        for index, (high, low, close, volume) in enumerate(fifteen_specs)
    )
    five_specs = (
        (36, "10", "8", "9", "100"),
        (37, "15", "12", "14", "100"),
        (38, "16", "13", "14", "100"),
        (39, "15.5", "12.5", "14", "100"),
        (40, "16.5", "13", "14", "100"),
        (41, "16.5", "13", "16.1", "200"),
    )
    five = tuple(
        _focus_bar(
            index,
            high=high,
            low=low,
            close=close,
            volume=volume,
            frequency="5m",
        ).bar
        for index, high, low, close, volume in five_specs
    )
    return fifteen, five


def test_missing_hot_metric_blocks_new_admission_but_keeps_running_tracking() -> None:
    pages = _snapshot_pages()
    pages[(SeriesKind.CONTRACT, BarFrequency.M15)], pages[
        (SeriesKind.CONTRACT, BarFrequency.M5)
    ] = _running_intraday_pages()

    result = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(metrics=_metrics(volume_ratio20=None)),
        market_data=_FakeMarketData(pages),
        market_read=_FakeMarketRead(),
        dominants=_dominants(),
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )

    assert result.long_opportunities == ()
    assert len(result.running_trends) == 1
    assert result.running_trends[0].stage == "running"
    assert result.unavailable[0].code == "HOT_METRIC_UNAVAILABLE"


def test_hourly_history_below_23_is_explicitly_unavailable() -> None:
    pages = _snapshot_pages()
    pages[(SeriesKind.CONTRACT, BarFrequency.H1)] = pages[
        (SeriesKind.CONTRACT, BarFrequency.H1)
    ][:22]

    result = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(),
        market_data=_FakeMarketData(pages),
        market_read=_FakeMarketRead(),
        dominants=_dominants(),
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )

    assert result.long_opportunities == ()
    assert result.unavailable[0].code == "HOURLY_HISTORY_INSUFFICIENT"


def test_live_contract_mismatch_is_not_replaced_by_stale_historical() -> None:
    result = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(),
        market_data=_FakeMarketData(_snapshot_pages()),
        market_read=_FakeMarketRead(
            phase="TRADING",
            live_available=True,
            live_contract="JM2701",
            source="realtime",
        ),
        dominants=_dominants(),
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )

    assert result.long_opportunities == ()
    assert result.unavailable[0].code == "LIVE_CONTRACT_MISMATCH"


def test_invalid_dominant_isolated_to_one_symbol_and_other_symbol_still_builds() -> None:
    radar = _radar_snapshot()
    jm = radar.items[0]
    rb = replace(jm, symbol="rb", product_name="螺纹钢")
    radar = replace(radar, active_count=2, participant_count=2, items=(jm, rb))
    dominants = {
        "jm": replace(_dominants()["jm"], actual_contract="RB2609"),
        "rb": DominantContractSummary(
            symbol="rb",
            product_name="螺纹钢",
            sector="black",
            exchange="SHFE",
            actual_contract="RB2609",
            dominant_mapping_date=date(2026, 1, 23),
        ),
    }

    result = build_market_trend_focus_snapshot(
        radar_snapshot=radar,
        market_data=_FakeMarketData(_snapshot_pages()),
        market_read=_FakeMarketRead(),
        dominants=dominants,
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )

    assert tuple(item.symbol for item in result.long_opportunities) == ("rb",)
    assert len(result.unavailable) == 1
    assert result.unavailable[0].symbol == "jm"
    assert result.unavailable[0].code == "PHYSICAL_CONTRACT_UNAVAILABLE"


def test_opportunity_sort_is_stage_specific_then_exact_tuple_and_caps_at_ten() -> None:
    base_snapshot = build_market_trend_focus_snapshot(
        radar_snapshot=_radar_snapshot(),
        market_data=_FakeMarketData(_snapshot_pages()),
        market_read=_FakeMarketRead(),
        dominants=_dominants(),
        now=datetime(2026, 1, 24, tzinfo=UTC),
    )
    base = base_snapshot.long_opportunities[0]
    items = tuple(
        replace(
            base,
            symbol=f"s{index:02d}",
            stage=("ready" if index == 11 else "retest" if index == 10 else "setup"),
            retest_held=index == 10,
            volume_confirmed=index % 2 == 0,
            hot_count=3 if index % 3 == 0 else 2,
        )
        for index in range(12)
    )

    result = sort_opportunities(items)

    assert len(result) == 10
    assert result[0].symbol == "s11"
    assert result[1].symbol == "s10"
    assert {item.symbol for item in result}.isdisjoint({"s05", "s07"})
