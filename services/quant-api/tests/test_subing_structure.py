from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_structure import (
    ConfirmedPivot,
    PivotKind,
    assess_pivot_breakout,
    assess_pivot_retest,
    confirmed_pivots,
)


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_START = datetime(2026, 8, 19, 1, 5, tzinfo=UTC)


def _bar(
    index: int,
    *,
    high: str,
    low: str,
    close: str | None = None,
    trading_day: date = _TRADING_DAY,
    volume: str = "100",
    open_interest: str | None = None,
) -> CanonicalBar:
    high_value = Decimal(high)
    low_value = Decimal(low)
    close_value = (
        (high_value + low_value) / Decimal(2)
        if close is None
        else Decimal(close)
    )
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=5 * index),
        trading_day=trading_day,
        open=close_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=Decimal(volume),
        turnover=None,
        open_interest=None if open_interest is None else Decimal(open_interest),
    )


def _strict_pivot_bars() -> tuple[CanonicalBar, ...]:
    values = (
        ("12", "10"),
        ("13", "11"),
        ("18", "16"),
        ("14", "12"),
        ("13", "11"),
        ("12", "10"),
        ("9", "6"),
        ("12", "10"),
        ("13", "11"),
    )
    return tuple(
        _bar(index, high=high, low=low)
        for index, (high, low) in enumerate(values)
    )


def _pivots(
    bars: tuple[CanonicalBar, ...],
    *,
    trading_day: date = _TRADING_DAY,
    source_timeframe: BarFrequency = BarFrequency.M5,
) -> tuple[ConfirmedPivot, ...]:
    return confirmed_pivots(
        bars,
        source_timeframe=source_timeframe,
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        trading_day=trading_day,
    )


def test_confirmed_pivots_require_exact_two_left_and_two_right_bars() -> None:
    bars = _strict_pivot_bars()

    pivots = _pivots(bars)

    assert tuple(pivot.kind for pivot in pivots) == (PivotKind.HIGH, PivotKind.LOW)
    assert tuple(pivot.pivot_time for pivot in pivots) == (
        bars[2].bar_end,
        bars[6].bar_end,
    )
    assert tuple(pivot.confirmed_at for pivot in pivots) == (
        bars[4].bar_end,
        bars[8].bar_end,
    )


def test_first_and_last_two_bars_are_never_confirmed_as_pivots() -> None:
    bars = (
        _bar(0, high="30", low="1"),
        _bar(1, high="25", low="2"),
        _bar(2, high="20", low="10"),
        _bar(3, high="25", low="2"),
        _bar(4, high="30", low="1"),
    )

    assert _pivots(bars) == ()


@pytest.mark.parametrize(
    ("bars", "rejected_kind"),
    (
        (
            (
                ("12", "10"),
                ("18", "11"),
                ("18", "12"),
                ("13", "11"),
                ("12", "10"),
            ),
            PivotKind.HIGH,
        ),
        (
            (
                ("12", "10"),
                ("13", "6"),
                ("14", "6"),
                ("13", "9"),
                ("12", "10"),
            ),
            PivotKind.LOW,
        ),
    ),
)
def test_equal_extreme_rejects_pivot(
    bars: tuple[tuple[str, str], ...],
    rejected_kind: PivotKind,
) -> None:
    canonical = tuple(
        _bar(index, high=high, low=low)
        for index, (high, low) in enumerate(bars)
    )

    assert all(pivot.kind is not rejected_kind for pivot in _pivots(canonical))


def test_confirmed_pivot_retains_exact_source_and_segment_identity() -> None:
    bars = _strict_pivot_bars()[:5]

    (pivot,) = _pivots(bars)

    assert pivot.source_timeframe is BarFrequency.M5
    assert pivot.contract == _CONTRACT
    assert pivot.segment_start_trading_day == _SEGMENT_START
    assert pivot.price == Decimal("18")
    assert pivot.pivot_id


def test_confirmed_pivots_reject_non_5m_source() -> None:
    with pytest.raises(ValueError, match="SUBING_PIVOT_SOURCE_TIMEFRAME_INVALID"):
        _pivots(_strict_pivot_bars(), source_timeframe=BarFrequency.M15)


def test_confirmed_pivots_select_references_within_one_trading_day() -> None:
    next_trading_day = date(2026, 8, 20)
    first_day = _strict_pivot_bars()[:5]
    second_day = tuple(
        _bar(
            index + len(first_day),
            high=high,
            low=low,
            trading_day=next_trading_day,
        )
        for index, (high, low) in enumerate(
            (("22", "20"), ("23", "21"), ("28", "26"), ("24", "22"), ("23", "21"))
        )
    )

    pivots = _pivots(first_day + second_day, trading_day=next_trading_day)

    assert len(pivots) == 1
    assert pivots[0].pivot_time == second_day[2].bar_end
    assert pivots[0].price == Decimal("28")


def test_confirmed_pivots_are_prefix_invariant() -> None:
    bars = _strict_pivot_bars()
    prefix = bars[:8]

    before = _pivots(prefix)
    after = _pivots(bars)

    assert tuple(
        pivot for pivot in after if pivot.confirmed_at <= prefix[-1].bar_end
    ) == before


def test_pivot_confirmed_at_current_boundary_cannot_break_out_same_boundary() -> None:
    previous = _bar(0, high="100", low="98", close="99")
    current = _bar(1, high="102", low="99", close="101")
    just_confirmed = ConfirmedPivot(
        pivot_id="current-boundary-pivot",
        kind=PivotKind.HIGH,
        source_timeframe=BarFrequency.M5,
        pivot_time=previous.bar_end - timedelta(minutes=10),
        confirmed_at=current.bar_end,
        price=Decimal("100"),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )
    previously_confirmed = ConfirmedPivot(
        pivot_id="previous-boundary-pivot",
        kind=PivotKind.HIGH,
        source_timeframe=BarFrequency.M5,
        pivot_time=previous.bar_end - timedelta(minutes=15),
        confirmed_at=previous.bar_end,
        price=Decimal("100"),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )

    current_boundary = assess_pivot_breakout(
        previous,
        current,
        pivot=just_confirmed,
        direction=SubingDirection.LONG,
    )
    older_boundary = assess_pivot_breakout(
        previous,
        current,
        pivot=previously_confirmed,
        direction=SubingDirection.LONG,
    )

    assert current_boundary.crossed_on_close is False
    assert older_boundary.crossed_on_close is True


def _confirmed_pivot(
    *,
    kind: PivotKind,
    price: str = "100",
) -> ConfirmedPivot:
    return ConfirmedPivot(
        pivot_id=f"confirmed-{kind.value}-pivot",
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=_START - timedelta(minutes=15),
        confirmed_at=_START - timedelta(minutes=5),
        price=Decimal(price),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )


def test_long_breakout_requires_previous_close_at_or_below_and_current_close_above() -> None:
    pivot = _confirmed_pivot(kind=PivotKind.HIGH)
    actual_cross = assess_pivot_breakout(
        _bar(0, high="100", low="98", close="100"),
        _bar(1, high="102", low="99", close="101"),
        pivot=pivot,
        direction=SubingDirection.LONG,
    )
    already_above = assess_pivot_breakout(
        _bar(0, high="102", low="100", close="101"),
        _bar(1, high="103", low="101", close="102"),
        pivot=pivot,
        direction=SubingDirection.LONG,
    )

    assert actual_cross.crossed_on_close is True
    assert already_above.crossed_on_close is False


def test_short_breakout_mirrors_exact_close_cross() -> None:
    pivot = _confirmed_pivot(kind=PivotKind.LOW)
    actual_cross = assess_pivot_breakout(
        _bar(0, high="102", low="100", close="100"),
        _bar(1, high="101", low="98", close="99"),
        pivot=pivot,
        direction=SubingDirection.SHORT,
    )
    already_below = assess_pivot_breakout(
        _bar(0, high="100", low="98", close="99"),
        _bar(1, high="99", low="97", close="98"),
        pivot=pivot,
        direction=SubingDirection.SHORT,
    )

    assert actual_cross.crossed_on_close is True
    assert already_below.crossed_on_close is False


@pytest.mark.parametrize(
    ("direction", "kind", "previous", "current"),
    (
        (
            SubingDirection.LONG,
            PivotKind.HIGH,
            ("100", "98", "99"),
            ("101", "98", "99.5"),
        ),
        (
            SubingDirection.SHORT,
            PivotKind.LOW,
            ("102", "100", "101"),
            ("102", "99", "100.5"),
        ),
    ),
)
def test_intrabar_touch_without_close_cross_is_evidence_only(
    direction: SubingDirection,
    kind: PivotKind,
    previous: tuple[str, str, str],
    current: tuple[str, str, str],
) -> None:
    result = assess_pivot_breakout(
        _bar(0, high=previous[0], low=previous[1], close=previous[2]),
        _bar(1, high=current[0], low=current[1], close=current[2]),
        pivot=_confirmed_pivot(kind=kind),
        direction=direction,
    )

    assert result.intrabar_touched is True
    assert result.close_beyond_level is False
    assert result.crossed_on_close is False


def test_breakout_records_decimal_volume_ratio_and_open_interest_delta() -> None:
    result = assess_pivot_breakout(
        _bar(
            0,
            high="100",
            low="98",
            close="99",
            volume="80",
            open_interest="1000.5",
        ),
        _bar(
            1,
            high="102",
            low="99",
            close="101",
            volume="120",
            open_interest="1003.75",
        ),
        pivot=_confirmed_pivot(kind=PivotKind.HIGH),
        direction=SubingDirection.LONG,
    )

    assert result.volume_ratio_prev == Decimal("1.5")
    assert result.open_interest_delta == Decimal("3.25")


@pytest.mark.parametrize(
    ("previous_open_interest", "current_open_interest"),
    ((None, "1003"), ("1000", None), (None, None)),
)
def test_breakout_keeps_open_interest_delta_unavailable_unless_both_exist(
    previous_open_interest: str | None,
    current_open_interest: str | None,
) -> None:
    result = assess_pivot_breakout(
        _bar(
            0,
            high="100",
            low="98",
            close="99",
            open_interest=previous_open_interest,
        ),
        _bar(
            1,
            high="102",
            low="99",
            close="101",
            open_interest=current_open_interest,
        ),
        pivot=_confirmed_pivot(kind=PivotKind.HIGH),
        direction=SubingDirection.LONG,
    )

    assert result.open_interest_delta is None


def test_breakout_keeps_volume_ratio_unavailable_when_previous_volume_is_zero() -> None:
    result = assess_pivot_breakout(
        _bar(0, high="100", low="98", close="99", volume="0"),
        _bar(1, high="102", low="99", close="101", volume="120"),
        pivot=_confirmed_pivot(kind=PivotKind.HIGH),
        direction=SubingDirection.LONG,
    )

    assert result.volume_ratio_prev is None


@pytest.mark.parametrize(
    ("direction", "kind", "bar"),
    (
        (SubingDirection.LONG, PivotKind.HIGH, ("102", "99", "100")),
        (SubingDirection.SHORT, PivotKind.LOW, ("101", "98", "100")),
    ),
)
def test_retest_touch_that_closes_on_preserved_side_is_legal(
    direction: SubingDirection,
    kind: PivotKind,
    bar: tuple[str, str, str],
) -> None:
    result = assess_pivot_retest(
        _bar(1, high=bar[0], low=bar[1], close=bar[2]),
        pivot=_confirmed_pivot(kind=kind),
        direction=direction,
    )

    assert result.touched_reference is True
    assert result.close_preserved_side is True
    assert result.hard_invalidated is False


@pytest.mark.parametrize(
    ("direction", "kind", "bar"),
    (
        (SubingDirection.LONG, PivotKind.HIGH, ("101", "99", "99.99")),
        (SubingDirection.SHORT, PivotKind.LOW, ("100.01", "99", "100.01")),
    ),
)
def test_retest_close_through_reference_is_hard_invalidated_without_tolerance(
    direction: SubingDirection,
    kind: PivotKind,
    bar: tuple[str, str, str],
) -> None:
    result = assess_pivot_retest(
        _bar(1, high=bar[0], low=bar[1], close=bar[2]),
        pivot=_confirmed_pivot(kind=kind),
        direction=direction,
    )

    assert result.touched_reference is True
    assert result.close_preserved_side is False
    assert result.hard_invalidated is True


@pytest.mark.parametrize(
    ("direction", "kind", "bar"),
    (
        (SubingDirection.LONG, PivotKind.HIGH, ("103", "101", "102")),
        (SubingDirection.SHORT, PivotKind.LOW, ("99", "97", "98")),
    ),
)
def test_bar_that_does_not_touch_reference_is_not_a_retest(
    direction: SubingDirection,
    kind: PivotKind,
    bar: tuple[str, str, str],
) -> None:
    result = assess_pivot_retest(
        _bar(1, high=bar[0], low=bar[1], close=bar[2]),
        pivot=_confirmed_pivot(kind=kind),
        direction=direction,
    )

    assert result.touched_reference is False
    assert result.close_preserved_side is True
    assert result.hard_invalidated is False
