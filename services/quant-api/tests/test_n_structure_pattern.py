from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.n_structure_pattern import (
    NBreakKind,
    NDirection,
    NRangeBandRole,
    evaluate_n_patterns,
)
from app.market_data.n_structure_policy import (
    NStructurePolicy,
    load_n_structure_policy,
)
from app.market_data.n_structure_swing import (
    NSwingLeg,
    NSwingPivot,
    NSwingPivotKind,
    NSwingTrace,
)


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_START = datetime(2026, 8, 19, 1, 5, tzinfo=UTC)


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _bar(
    index: int,
    *,
    high: str,
    low: str,
    close: str | None = None,
) -> CanonicalBar:
    high_value = Decimal(high)
    low_value = Decimal(low)
    close_value = (
        Decimal(close)
        if close is not None
        else (high_value + low_value) / Decimal(2)
    )
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=5 * index),
        trading_day=_TRADING_DAY,
        open=close_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _pivot(
    pivot_index: int,
    *,
    confirmed_index: int,
    kind: NSwingPivotKind,
    price: str,
    epoch: int = 0,
) -> NSwingPivot:
    pivot_time = _START + timedelta(minutes=5 * pivot_index)
    return NSwingPivot(
        pivot_id=":".join(
            (
                _CONTRACT,
                _SEGMENT_START.isoformat(),
                BarFrequency.M5.value,
                str(epoch),
                kind.value,
                pivot_time.isoformat(),
            )
        ),
        epoch=epoch,
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_time,
        confirmed_at=_START + timedelta(minutes=5 * confirmed_index),
        price=Decimal(price),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )


def _swing(
    pivots: tuple[NSwingPivot, ...],
    *,
    resets: tuple[int, ...] = (),
) -> NSwingTrace:
    reset_times = tuple(
        _START + timedelta(minutes=5 * index) for index in resets
    )
    return NSwingTrace(
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        pivots=pivots,
        ambiguous_outside_reset_at=reset_times,
        final_epoch=len(reset_times),
        final_leg=NSwingLeg.UNRESOLVED,
    )


def _evaluate(
    bars: tuple[CanonicalBar, ...],
    pivots: tuple[NSwingPivot, ...],
    *,
    resets: tuple[int, ...] = (),
    policy: NStructurePolicy | None = None,
):
    return evaluate_n_patterns(
        bars,
        _swing(pivots, resets=resets),
        policy=policy if policy is not None else load_n_structure_policy(),
    )


def _prefix_swing(trace: NSwingTrace, boundary: datetime) -> NSwingTrace:
    resets = tuple(
        reset_at
        for reset_at in trace.ambiguous_outside_reset_at
        if reset_at <= boundary
    )
    return NSwingTrace(
        contract=trace.contract,
        segment_start_trading_day=trace.segment_start_trading_day,
        pivots=tuple(
            pivot for pivot in trace.pivots if pivot.confirmed_at <= boundary
        ),
        ambiguous_outside_reset_at=resets,
        final_epoch=len(resets),
        final_leg=NSwingLeg.UNRESOLVED,
    )


def _assert_prefix_invariant(
    bars: tuple[CanonicalBar, ...],
    pivots: tuple[NSwingPivot, ...],
    *,
    resets: tuple[int, ...] = (),
) -> None:
    swing = _swing(pivots, resets=resets)
    policy = load_n_structure_policy()
    full = evaluate_n_patterns(bars, swing, policy=policy)
    replacement_counts: list[int] = []

    for length in range(1, len(bars) + 1):
        boundary = bars[length - 1].bar_end
        prefix = evaluate_n_patterns(
            bars[:length],
            _prefix_swing(swing, boundary),
            policy=policy,
        )
        assert prefix.patterns == tuple(
            pattern
            for pattern in full.patterns
            if pattern.completed_at <= boundary
        )
        assert prefix.break_events == tuple(
            event
            for event in full.break_events
            if event.observed_at <= boundary
        )
        assert prefix.range_band_reentries == tuple(
            event
            for event in full.range_band_reentries
            if event.observed_at <= boundary
        )
        replacement_counts.append(prefix.incomplete_attempt_replaced_count)

    assert replacement_counts == sorted(replacement_counts)
    assert replacement_counts[-1] == full.incomplete_attempt_replaced_count


def _up_pivots(
    *,
    origin: str = "10",
    n1: str = "12",
    n2: str = "10",
    epoch: int = 0,
) -> tuple[NSwingPivot, ...]:
    return (
        _pivot(
            0,
            confirmed_index=1,
            kind=NSwingPivotKind.LOW,
            price=origin,
            epoch=epoch,
        ),
        _pivot(
            1,
            confirmed_index=2,
            kind=NSwingPivotKind.HIGH,
            price=n1,
            epoch=epoch,
        ),
        _pivot(
            2,
            confirmed_index=3,
            kind=NSwingPivotKind.LOW,
            price=n2,
            epoch=epoch,
        ),
    )


def _down_pivots(
    *,
    origin: str = "12",
    n1: str = "10",
    n2: str = "12",
    epoch: int = 0,
) -> tuple[NSwingPivot, ...]:
    return (
        _pivot(
            0,
            confirmed_index=1,
            kind=NSwingPivotKind.HIGH,
            price=origin,
            epoch=epoch,
        ),
        _pivot(
            1,
            confirmed_index=2,
            kind=NSwingPivotKind.LOW,
            price=n1,
            epoch=epoch,
        ),
        _pivot(
            2,
            confirmed_index=3,
            kind=NSwingPivotKind.HIGH,
            price=n2,
            epoch=epoch,
        ),
    )


@pytest.mark.parametrize(
    ("direction", "origin", "n1", "n2", "expected_count"),
    (
        (NDirection.UP, "10", "12", "10", 1),
        (NDirection.UP, "10", "12", "9", 0),
        (NDirection.DOWN, "12", "10", "12", 1),
        (NDirection.DOWN, "12", "10", "13", 0),
    ),
)
def test_same_epoch_base_matrix_allows_origin_equality_only_on_valid_side(
    direction: NDirection,
    origin: str,
    n1: str,
    n2: str,
    expected_count: int,
) -> None:
    if direction is NDirection.UP:
        pivots = _up_pivots(origin=origin, n1=n1, n2=n2)
        bars = (
            _bar(0, high="11", low=origin),
            _bar(1, high=n1, low="10"),
            _bar(2, high="11", low=n2),
            _bar(3, high=n1, low="10"),
            _bar(4, high="13", low="10", close="12.5"),
        )
    else:
        pivots = _down_pivots(origin=origin, n1=n1, n2=n2)
        bars = (
            _bar(0, high=origin, low="11"),
            _bar(1, high="12", low=n1),
            _bar(2, high=n2, low="11"),
            _bar(3, high="12", low=n1),
            _bar(4, high="12", low="9", close="9.5"),
        )

    trace = _evaluate(bars, pivots)

    assert len(trace.patterns) == expected_count
    if expected_count:
        assert trace.patterns[0].direction is direction
    _assert_prefix_invariant(bars, pivots)


def test_base_cannot_connect_pivots_across_outside_epoch_barrier() -> None:
    pivots = (
        _up_pivots()[:2]
        + (
            _pivot(
                3,
                confirmed_index=4,
                kind=NSwingPivotKind.LOW,
                price="10",
                epoch=1,
            ),
        )
    )
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="10"),
        _bar(3, high="13", low="9"),
        _bar(4, high="12", low="10"),
        _bar(5, high="14", low="10"),
    )

    trace = _evaluate(bars, pivots, resets=(3,))

    assert trace.patterns == ()
    assert trace.incomplete_attempt_replaced_count == 0
    _assert_prefix_invariant(bars, pivots, resets=(3,))


def test_first_strict_non_outside_n1_breach_completes_and_equal_does_not() -> None:
    pivots = _up_pivots()
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="10"),
        _bar(3, high="12", low="10"),
        _bar(4, high="12", low="10"),
        _bar(5, high="13", low="10", close="12.5"),
        _bar(6, high="15", low="10", close="14"),
    )

    equal_prefix = _evaluate(bars[:5], pivots)
    full = _evaluate(bars, pivots)

    assert equal_prefix.patterns == ()
    assert len(full.patterns) == 1
    assert full.patterns[0].completed_at == bars[5].bar_end
    assert full.patterns[0].completion_level == Decimal("12")
    assert full.patterns[0].completion_bar_close == Decimal("12.5")
    _assert_prefix_invariant(bars, pivots)


def test_down_completion_uses_first_strict_low_breach() -> None:
    pivots = _down_pivots()
    bars = (
        _bar(0, high="12", low="11"),
        _bar(1, high="12", low="10"),
        _bar(2, high="12", low="11"),
        _bar(3, high="12", low="10"),
        _bar(4, high="12", low="10"),
        _bar(5, high="12", low="9", close="9.5"),
    )

    trace = _evaluate(bars, pivots)

    assert len(trace.patterns) == 1
    assert trace.patterns[0].direction is NDirection.DOWN
    assert trace.patterns[0].completed_at == bars[5].bar_end
    _assert_prefix_invariant(bars, pivots)


def test_outside_boundary_cannot_complete_and_discards_incomplete_attempt() -> None:
    pivots = _up_pivots()
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="10"),
        _bar(3, high="12", low="10"),
        _bar(4, high="13", low="9"),
        _bar(5, high="14", low="10"),
    )

    trace = _evaluate(bars, pivots, resets=(4,))

    assert trace.patterns == ()
    assert trace.incomplete_attempt_replaced_count == 0
    _assert_prefix_invariant(bars, pivots, resets=(4,))


@pytest.mark.parametrize(
    ("direction", "pivots", "completion_bar", "expected"),
    (
        (
            NDirection.UP,
            _up_pivots(n1="100", n2="10"),
            _bar(4, high="101", low="10", close="100"),
            Decimal("100"),
        ),
        (
            NDirection.DOWN,
            _down_pivots(origin="120", n1="100", n2="120"),
            _bar(4, high="120", low="99", close="100"),
            Decimal("100"),
        ),
    ),
)
def test_completion_overshoot_uses_exact_decimal_formula(
    direction: NDirection,
    pivots: tuple[NSwingPivot, ...],
    completion_bar: CanonicalBar,
    expected: Decimal,
) -> None:
    if direction is NDirection.UP:
        bars = (
            _bar(0, high="90", low="10"),
            _bar(1, high="100", low="10"),
            _bar(2, high="90", low="10"),
            _bar(3, high="100", low="10"),
            completion_bar,
        )
    else:
        bars = (
            _bar(0, high="120", low="110"),
            _bar(1, high="120", low="100"),
            _bar(2, high="120", low="110"),
            _bar(3, high="120", low="100"),
            completion_bar,
        )

    trace = _evaluate(bars, pivots)

    assert trace.patterns[0].completion_overshoot_bps == expected
    assert isinstance(trace.patterns[0].completion_overshoot_bps, Decimal)
    _assert_prefix_invariant(bars, pivots)


@pytest.mark.parametrize(
    ("completion_low", "expected_kinds"),
    (
        ("10.5", (NBreakKind.N2_ORIGIN_BROKEN,)),
        (
            "9",
            (
                NBreakKind.N2_ORIGIN_BROKEN,
                NBreakKind.ORIGIN_BROKEN,
            ),
        ),
    ),
)
def test_same_boundary_completion_records_n2_then_origin_break_facts(
    completion_low: str,
    expected_kinds: tuple[NBreakKind, ...],
) -> None:
    pivots = _up_pivots(origin="10", n1="12", n2="11")
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="11"),
        _bar(3, high="12", low="11"),
        _bar(4, high="12", low=completion_low),
        _bar(5, high="13", low=completion_low, close="12"),
    )

    trace = _evaluate(bars, pivots)

    assert len(trace.patterns) == 1
    assert trace.patterns[0].completed_at == bars[5].bar_end
    assert tuple(event.kind for event in trace.break_events) == expected_kinds
    assert {event.observed_at for event in trace.break_events} == {
        bars[5].bar_end
    }
    assert all(
        field.name != "intrabar_order"
        for field in fields(type(trace.break_events[0]))
    )
    _assert_prefix_invariant(bars, pivots)


def test_down_same_boundary_completion_records_n2_then_origin_break_facts() -> None:
    pivots = _down_pivots(origin="12", n1="10", n2="11")
    bars = (
        _bar(0, high="12", low="11"),
        _bar(1, high="11", low="10"),
        _bar(2, high="11", low="10"),
        _bar(3, high="11", low="10"),
        _bar(4, high="13", low="10"),
        _bar(5, high="13", low="9", close="10"),
    )

    trace = _evaluate(bars, pivots)

    assert len(trace.patterns) == 1
    assert trace.patterns[0].direction is NDirection.DOWN
    assert trace.patterns[0].completed_at == bars[5].bar_end
    assert [event.kind for event in trace.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN,
        NBreakKind.ORIGIN_BROKEN,
    ]
    assert {event.observed_at for event in trace.break_events} == {
        bars[5].bar_end
    }
    _assert_prefix_invariant(bars, pivots)


def test_outside_boundary_still_records_existing_n_level_break_facts() -> None:
    pivots = _up_pivots(origin="10", n1="12", n2="11")
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="11"),
        _bar(3, high="12", low="11"),
        _bar(4, high="13", low="11", close="12.5"),
        _bar(5, high="14", low="9"),
    )

    trace = _evaluate(bars, pivots, resets=(5,))

    assert [event.kind for event in trace.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN,
        NBreakKind.ORIGIN_BROKEN,
    ]
    assert {event.observed_at for event in trace.break_events} == {
        bars[5].bar_end
    }
    _assert_prefix_invariant(bars, pivots, resets=(5,))


def test_equal_levels_do_not_break_and_each_kind_emits_only_once() -> None:
    pivots = _up_pivots(origin="10", n1="12", n2="11")
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="11"),
        _bar(3, high="12", low="11"),
        _bar(4, high="13", low="11", close="12.5"),
        _bar(5, high="13", low="11"),
        _bar(6, high="13", low="10"),
        _bar(7, high="13", low="9"),
        _bar(8, high="13", low="8"),
    )

    at_equal_n2 = _evaluate(bars[:6], pivots)
    at_equal_origin = _evaluate(bars[:7], pivots)
    full = _evaluate(bars, pivots)

    assert at_equal_n2.break_events == ()
    assert [event.kind for event in at_equal_origin.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN
    ]
    assert [event.kind for event in full.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN,
        NBreakKind.ORIGIN_BROKEN,
    ]
    assert len({event.event_id for event in full.break_events}) == 2
    _assert_prefix_invariant(bars, pivots)


def test_down_equal_levels_do_not_break_and_each_kind_emits_only_once() -> None:
    pivots = _down_pivots(origin="13", n1="10", n2="12")
    bars = (
        _bar(0, high="13", low="11"),
        _bar(1, high="12", low="10"),
        _bar(2, high="12", low="11"),
        _bar(3, high="12", low="10"),
        _bar(4, high="10", low="9", close="9.5"),
        _bar(5, high="12", low="9"),
        _bar(6, high="13", low="9"),
        _bar(7, high="14", low="9"),
        _bar(8, high="15", low="9"),
    )

    at_equal_n2 = _evaluate(bars[:6], pivots)
    at_equal_origin = _evaluate(bars[:7], pivots)
    full = _evaluate(bars, pivots)

    assert at_equal_n2.break_events == ()
    assert [event.kind for event in at_equal_origin.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN
    ]
    assert [event.kind for event in full.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN,
        NBreakKind.ORIGIN_BROKEN,
    ]
    assert len({event.event_id for event in full.break_events}) == 2
    _assert_prefix_invariant(bars, pivots)


def test_completed_identity_is_frozen_and_future_extremes_never_rewrite_it() -> None:
    pivots = _up_pivots(origin="10", n1="12", n2="11")
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="11"),
        _bar(3, high="12", low="11"),
        _bar(4, high="13", low="11", close="12.5"),
        _bar(5, high="30", low="11", close="20"),
    )

    completed = _evaluate(bars[:5], pivots).patterns[0]
    extended = _evaluate(bars, pivots).patterns[0]

    assert extended == completed
    with pytest.raises(FrozenInstanceError):
        extended.completed_at = bars[5].bar_end  # type: ignore[misc]
    _assert_prefix_invariant(bars, pivots)


@pytest.mark.parametrize(
    ("direction", "pivots", "bars", "expected_lower", "expected_upper", "role"),
    (
        (
            NDirection.UP,
            _up_pivots(origin="9", n1="12", n2="10"),
            (
                _bar(0, high="11", low="9"),
                _bar(1, high="12", low="10"),
                _bar(2, high="11", low="10"),
                _bar(3, high="12", low="10"),
                _bar(4, high="13", low="12"),
                _bar(5, high="13", low="12"),
                _bar(6, high="13", low="11"),
            ),
            Decimal("10"),
            Decimal("12"),
            NRangeBandRole.SUPPORT_REFERENCE,
        ),
        (
            NDirection.DOWN,
            _down_pivots(origin="13", n1="10", n2="12"),
            (
                _bar(0, high="13", low="11"),
                _bar(1, high="12", low="10"),
                _bar(2, high="12", low="11"),
                _bar(3, high="12", low="10"),
                _bar(4, high="10", low="9"),
                _bar(5, high="10", low="9"),
                _bar(6, high="11", low="9"),
            ),
            Decimal("10"),
            Decimal("12"),
            NRangeBandRole.RESISTANCE_REFERENCE,
        ),
    ),
)
def test_range_band_exact_span_role_and_first_later_touch_only(
    direction: NDirection,
    pivots: tuple[NSwingPivot, ...],
    bars: tuple[CanonicalBar, ...],
    expected_lower: Decimal,
    expected_upper: Decimal,
    role: NRangeBandRole,
) -> None:
    completion = _evaluate(bars[:5], pivots)
    first_touch = _evaluate(bars[:6], pivots)
    full = _evaluate(bars, pivots)

    pattern = full.patterns[0]
    assert pattern.direction is direction
    assert pattern.range_band.lower == expected_lower
    assert pattern.range_band.upper == expected_upper
    assert pattern.range_band.role is role
    assert completion.range_band_reentries == ()
    assert len(first_touch.range_band_reentries) == 1
    assert first_touch.range_band_reentries[0].observed_at == bars[5].bar_end
    assert full.range_band_reentries == first_touch.range_band_reentries
    forbidden = {"strong", "medium", "weak", "strength"}
    assert forbidden.isdisjoint(
        field.name.lower() for field in fields(type(pattern.range_band))
    )
    _assert_prefix_invariant(bars, pivots)


def test_later_range_reentry_can_coexist_with_both_break_kinds() -> None:
    pivots = _up_pivots(origin="10", n1="12", n2="11")
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="11"),
        _bar(3, high="12", low="11"),
        _bar(4, high="13", low="12"),
        _bar(5, high="13", low="9"),
    )

    trace = _evaluate(bars, pivots)

    assert [event.observed_at for event in trace.break_events] == [
        bars[5].bar_end,
        bars[5].bar_end,
    ]
    assert [event.kind for event in trace.break_events] == [
        NBreakKind.N2_ORIGIN_BROKEN,
        NBreakKind.ORIGIN_BROKEN,
    ]
    assert [
        event.observed_at for event in trace.range_band_reentries
    ] == [bars[5].bar_end]
    _assert_prefix_invariant(bars, pivots)


def test_new_legal_same_epoch_base_replaces_incomplete_attempt_once() -> None:
    pivots = _up_pivots(origin="10", n1="12", n2="11") + (
        _pivot(
            3,
            confirmed_index=4,
            kind=NSwingPivotKind.HIGH,
            price="12",
        ),
    )
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="11"),
        _bar(3, high="12", low="11"),
        _bar(4, high="12", low="11"),
        _bar(5, high="12", low="10"),
    )

    trace = _evaluate(bars, pivots)

    assert trace.incomplete_attempt_replaced_count == 1
    assert len(trace.patterns) == 1
    assert trace.patterns[0].direction is NDirection.DOWN
    assert trace.patterns[0].origin == pivots[1]
    assert trace.patterns[0].n1_extreme == pivots[2]
    assert trace.patterns[0].n2_origin == pivots[3]
    assert trace.patterns[0].completed_at == bars[5].bar_end
    _assert_prefix_invariant(bars, pivots)


def test_outside_reset_discards_attempt_without_counting_replacement() -> None:
    pivots = _up_pivots()
    bars = (
        _bar(0, high="11", low="10"),
        _bar(1, high="12", low="10"),
        _bar(2, high="11", low="10"),
        _bar(3, high="12", low="10"),
        _bar(4, high="13", low="9"),
        _bar(5, high="14", low="10"),
    )

    trace = _evaluate(bars, pivots, resets=(4,))

    assert trace.patterns == ()
    assert trace.incomplete_attempt_replaced_count == 0
    _assert_prefix_invariant(bars, pivots, resets=(4,))


def test_pattern_requires_exact_m5_research_only_policy() -> None:
    policy = load_n_structure_policy()
    bars = (_bar(0, high="11", low="10"),)
    swing = _swing(())

    for drifted in (
        replace(policy, policy_id="n_structure_5m_v2"),
        replace(policy, research_only=False),
        replace(policy, source_timeframe=BarFrequency.M15),
    ):
        with pytest.raises(
            ValueError,
            match="N_STRUCTURE_CONTRACT_INVALID",
        ):
            evaluate_n_patterns(bars, swing, policy=drifted)


def test_pattern_rejects_exact_policy_scalar_and_nested_raw_drift() -> None:
    policy = load_n_structure_policy()
    bars = (_bar(0, high="11", low="10"),)
    swing = _swing(())

    nested_value_drift = _thaw_json(policy.raw)
    assert isinstance(nested_value_drift, dict)
    nested_value_drift["n_pattern"]["completion"] = "close_breach"  # type: ignore[index]
    missing_nested_key = _thaw_json(policy.raw)
    assert isinstance(missing_nested_key, dict)
    del missing_nested_key["range_band"]["reentry_starts"]  # type: ignore[index]
    extra_nested_key = _thaw_json(policy.raw)
    assert isinstance(extra_nested_key, dict)
    extra_nested_key["n_pattern"]["unexpected"] = True  # type: ignore[index]

    for drifted in (
        replace(policy, schema_version=True),
        replace(policy, raw=nested_value_drift),
        replace(policy, raw=missing_nested_key),
        replace(policy, raw=extra_nested_key),
    ):
        with pytest.raises(
            ValueError,
            match="N_STRUCTURE_CONTRACT_INVALID",
        ):
            evaluate_n_patterns(bars, swing, policy=drifted)


@pytest.mark.parametrize(
    ("bars", "resets"),
    (
        (
            (
                _bar(0, high="11", low="10"),
                _bar(1, high="12", low="9"),
            ),
            (),
        ),
        (
            (
                _bar(0, high="11", low="10"),
                _bar(1, high="12", low="10"),
            ),
            (1,),
        ),
    ),
)
def test_pattern_requires_exact_outside_trace_identity(
    bars: tuple[CanonicalBar, ...],
    resets: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        _evaluate(bars, (), resets=resets)


def test_pattern_rejects_unsorted_bars_or_foreign_swing_identity() -> None:
    b0 = _bar(0, high="11", low="10")
    b1 = _bar(1, high="12", low="10")

    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        evaluate_n_patterns(
            (b1, b0),
            _swing(()),
            policy=load_n_structure_policy(),
        )

    foreign = replace(_swing((_up_pivots()[0],)), contract="AG2612")
    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        evaluate_n_patterns(
            (b0, b1),
            foreign,
            policy=load_n_structure_policy(),
        )
