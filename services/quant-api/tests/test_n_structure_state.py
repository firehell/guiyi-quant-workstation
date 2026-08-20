from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.n_structure_pattern import (
    CompletedNPattern,
    NDirection,
    NPatternTrace,
    NRangeBand,
    NRangeBandRole,
)
from app.market_data.n_structure_policy import (
    NStructurePolicy,
    load_n_structure_policy,
)
from app.market_data.n_structure_state import (
    NStructureKind,
    evaluate_n_market_structure,
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


def _bar(index: int, *, high: str = "15", low: str = "12") -> CanonicalBar:
    high_value = Decimal(high)
    low_value = Decimal(low)
    midpoint = (high_value + low_value) / Decimal(2)
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=5 * index),
        trading_day=_TRADING_DAY,
        open=midpoint,
        high=high_value,
        low=low_value,
        close=midpoint,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _bars(count: int, *, high: str = "15", low: str = "12") -> list[CanonicalBar]:
    return [_bar(index, high=high, low=low) for index in range(count)]


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


def _pattern(
    direction: NDirection,
    origin: NSwingPivot,
    n1_extreme: NSwingPivot,
    n2_origin: NSwingPivot,
    *,
    completed_index: int,
) -> CompletedNPattern:
    role = (
        NRangeBandRole.SUPPORT_REFERENCE
        if direction is NDirection.UP
        else NRangeBandRole.RESISTANCE_REFERENCE
    )
    return CompletedNPattern(
        n_id="|".join(
            (
                "n",
                direction.value,
                origin.pivot_id,
                n1_extreme.pivot_id,
                n2_origin.pivot_id,
            )
        ),
        direction=direction,
        origin=origin,
        n1_extreme=n1_extreme,
        n2_origin=n2_origin,
        completed_at=_START + timedelta(minutes=5 * completed_index),
        completion_level=n1_extreme.price,
        completion_bar_close=n1_extreme.price,
        completion_overshoot_bps=Decimal("0"),
        range_band=NRangeBand(
            lower=min(n1_extreme.price, n2_origin.price),
            upper=max(n1_extreme.price, n2_origin.price),
            role=role,
        ),
    )


def _bull_evidence(
    *,
    epoch: int = 0,
    offset: int = 0,
    lows: tuple[str, str, str] = ("10", "11", "12"),
    highs: tuple[str, str] = ("12", "14"),
) -> tuple[tuple[NSwingPivot, ...], tuple[CompletedNPattern, ...]]:
    pivots = (
        _pivot(offset, confirmed_index=offset + 1, kind=NSwingPivotKind.LOW, price=lows[0], epoch=epoch),
        _pivot(offset + 2, confirmed_index=offset + 3, kind=NSwingPivotKind.HIGH, price=highs[0], epoch=epoch),
        _pivot(offset + 4, confirmed_index=offset + 5, kind=NSwingPivotKind.LOW, price=lows[1], epoch=epoch),
        _pivot(offset + 6, confirmed_index=offset + 7, kind=NSwingPivotKind.HIGH, price=highs[1], epoch=epoch),
        _pivot(offset + 8, confirmed_index=offset + 9, kind=NSwingPivotKind.LOW, price=lows[2], epoch=epoch),
    )
    patterns = (
        _pattern(NDirection.UP, *pivots[:3], completed_index=offset + 6),
        _pattern(NDirection.UP, *pivots[2:], completed_index=offset + 10),
    )
    return pivots, patterns


def _bear_evidence(
    *,
    epoch: int = 0,
    offset: int = 0,
    highs: tuple[str, str, str] = ("14", "13", "12"),
    lows: tuple[str, str] = ("12", "10"),
) -> tuple[tuple[NSwingPivot, ...], tuple[CompletedNPattern, ...]]:
    pivots = (
        _pivot(offset, confirmed_index=offset + 1, kind=NSwingPivotKind.HIGH, price=highs[0], epoch=epoch),
        _pivot(offset + 2, confirmed_index=offset + 3, kind=NSwingPivotKind.LOW, price=lows[0], epoch=epoch),
        _pivot(offset + 4, confirmed_index=offset + 5, kind=NSwingPivotKind.HIGH, price=highs[1], epoch=epoch),
        _pivot(offset + 6, confirmed_index=offset + 7, kind=NSwingPivotKind.LOW, price=lows[1], epoch=epoch),
        _pivot(offset + 8, confirmed_index=offset + 9, kind=NSwingPivotKind.HIGH, price=highs[2], epoch=epoch),
    )
    patterns = (
        _pattern(NDirection.DOWN, *pivots[:3], completed_index=offset + 6),
        _pattern(NDirection.DOWN, *pivots[2:], completed_index=offset + 10),
    )
    return pivots, patterns


def _range_evidence() -> tuple[tuple[NSwingPivot, ...], tuple[CompletedNPattern, ...]]:
    return _bull_evidence(lows=("10", "10", "10"), highs=("12", "12"))


def _swing(
    pivots: tuple[NSwingPivot, ...],
    *,
    reset_indices: tuple[int, ...] = (),
) -> NSwingTrace:
    return NSwingTrace(
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        pivots=pivots,
        ambiguous_outside_reset_at=tuple(
            _START + timedelta(minutes=5 * index) for index in reset_indices
        ),
        final_epoch=len(reset_indices),
        final_leg=NSwingLeg.UNRESOLVED,
    )


def _patterns(patterns: tuple[CompletedNPattern, ...]) -> NPatternTrace:
    return NPatternTrace(
        patterns=patterns,
        break_events=(),
        range_band_reentries=(),
        incomplete_attempt_replaced_count=0,
    )


def _evaluate(
    bars: list[CanonicalBar] | tuple[CanonicalBar, ...],
    pivots: tuple[NSwingPivot, ...],
    patterns: tuple[CompletedNPattern, ...],
    *,
    reset_indices: tuple[int, ...] = (),
    policy: NStructurePolicy | None = None,
):
    return evaluate_n_market_structure(
        tuple(bars),
        swings=_swing(pivots, reset_indices=reset_indices),
        patterns=_patterns(patterns),
        policy=policy if policy is not None else load_n_structure_policy(),
    )


def _prefix_swing(trace: NSwingTrace, boundary: datetime) -> NSwingTrace:
    resets = tuple(reset for reset in trace.ambiguous_outside_reset_at if reset <= boundary)
    return NSwingTrace(
        contract=trace.contract,
        segment_start_trading_day=trace.segment_start_trading_day,
        pivots=tuple(pivot for pivot in trace.pivots if pivot.confirmed_at <= boundary),
        ambiguous_outside_reset_at=resets,
        final_epoch=len(resets),
        final_leg=NSwingLeg.UNRESOLVED,
    )


def _prefix_patterns(trace: NPatternTrace, boundary: datetime) -> NPatternTrace:
    return NPatternTrace(
        patterns=tuple(pattern for pattern in trace.patterns if pattern.completed_at <= boundary),
        break_events=tuple(event for event in trace.break_events if event.observed_at <= boundary),
        range_band_reentries=tuple(
            event for event in trace.range_band_reentries if event.observed_at <= boundary
        ),
        incomplete_attempt_replaced_count=trace.incomplete_attempt_replaced_count,
    )


def _assert_prefix_invariant(
    bars: list[CanonicalBar],
    pivots: tuple[NSwingPivot, ...],
    patterns: tuple[CompletedNPattern, ...],
    *,
    reset_indices: tuple[int, ...] = (),
) -> None:
    swings = _swing(pivots, reset_indices=reset_indices)
    pattern_trace = _patterns(patterns)
    policy = load_n_structure_policy()
    full = evaluate_n_market_structure(
        tuple(bars), swings=swings, patterns=pattern_trace, policy=policy
    )

    for length in range(1, len(bars) + 1):
        boundary = bars[length - 1].bar_end
        prefix = evaluate_n_market_structure(
            tuple(bars[:length]),
            swings=_prefix_swing(swings, boundary),
            patterns=_prefix_patterns(pattern_trace, boundary),
            policy=policy,
        )
        assert prefix.snapshots == tuple(
            snapshot for snapshot in full.snapshots if snapshot.observed_at <= boundary
        )
        assert prefix.transitions == tuple(
            transition for transition in full.transitions if transition.transition_at <= boundary
        )


def test_less_than_two_completed_n_stays_undefined() -> None:
    pivots, patterns = _bull_evidence()
    bars = _bars(10)

    trace = _evaluate(bars, pivots, patterns[:1])

    assert trace.transitions == ()
    assert trace.snapshots[-1].kind is NStructureKind.UNDEFINED
    assert trace.snapshots[-1].completed_n_count_in_epoch == 1
    assert trace.snapshots[-1].trailing_defense is None


@pytest.mark.parametrize(
    ("evidence", "expected"),
    (
        (_bull_evidence(), NStructureKind.BULL),
        (_bear_evidence(), NStructureKind.BEAR),
        (_range_evidence(), NStructureKind.RANGE),
    ),
)
def test_two_same_epoch_n_use_exact_strict_classification_matrix(
    evidence: tuple[tuple[NSwingPivot, ...], tuple[CompletedNPattern, ...]],
    expected: NStructureKind,
) -> None:
    pivots, patterns = evidence
    bars = _bars(11, high="12", low="12") if expected is NStructureKind.BEAR else _bars(11)

    trace = _evaluate(bars, pivots, patterns)

    assert trace.snapshots[-1].kind is expected
    assert trace.transitions[-1].to_kind is expected
    if expected is NStructureKind.BULL:
        assert trace.snapshots[-1].trailing_defense == pivots[-1]
    elif expected is NStructureKind.BEAR:
        assert trace.snapshots[-1].trailing_defense == pivots[-1]
    else:
        assert trace.snapshots[-1].trailing_defense is None


def test_bull_defense_advances_only_after_new_hh_hl_pair() -> None:
    base_pivots, patterns = _bull_evidence()
    lower_high = _pivot(11, confirmed_index=12, kind=NSwingPivotKind.HIGH, price="13")
    lone_higher_low = _pivot(13, confirmed_index=14, kind=NSwingPivotKind.LOW, price="13")
    new_higher_high = _pivot(15, confirmed_index=16, kind=NSwingPivotKind.HIGH, price="16")
    bars = _bars(17)

    before_pair = _evaluate(bars[:15], base_pivots + (lower_high, lone_higher_low), patterns)
    after_later_high = _evaluate(
        bars,
        base_pivots + (lower_high, lone_higher_low, new_higher_high),
        patterns,
    )

    assert before_pair.snapshots[-1].trailing_defense == base_pivots[-1]
    assert after_later_high.snapshots[-1].trailing_defense == base_pivots[-1]
    assert all(
        transition.reason_code != "BULL_TRAILING_DEFENSE_ADVANCED"
        for transition in after_later_high.transitions
    )


@pytest.mark.parametrize("direction", (NStructureKind.BULL, NStructureKind.BEAR))
def test_directional_defense_advances_on_new_same_epoch_qualifying_pair(
    direction: NStructureKind,
) -> None:
    if direction is NStructureKind.BULL:
        pivots, patterns = _bull_evidence()
        new_high = _pivot(11, confirmed_index=12, kind=NSwingPivotKind.HIGH, price="16")
        new_defense = _pivot(13, confirmed_index=14, kind=NSwingPivotKind.LOW, price="13")
        bars = _bars(15)
        bars[14] = _bar(14, high="15", low="13")
        reason = "BULL_TRAILING_DEFENSE_ADVANCED"
    else:
        pivots, patterns = _bear_evidence()
        new_low = _pivot(11, confirmed_index=12, kind=NSwingPivotKind.LOW, price="8")
        new_defense = _pivot(13, confirmed_index=14, kind=NSwingPivotKind.HIGH, price="11")
        pivots = pivots + (new_low, new_defense)
        bars = _bars(15, high="11", low="9")
        reason = "BEAR_TRAILING_DEFENSE_ADVANCED"
        new_high = None

    all_pivots = pivots + ((new_high, new_defense) if new_high is not None else ())
    trace = _evaluate(bars, all_pivots, patterns)

    assert trace.snapshots[-1].trailing_defense == new_defense
    assert trace.transitions[-1].reason_code == reason
    assert trace.transitions[-1].from_kind is direction
    assert trace.transitions[-1].to_kind is direction


@pytest.mark.parametrize("direction", (NStructureKind.BULL, NStructureKind.BEAR))
def test_strict_existing_defense_breaks_to_range_equal_does_not(
    direction: NStructureKind,
) -> None:
    if direction is NStructureKind.BULL:
        pivots, patterns = _bull_evidence()
        bars = _bars(13)
        bars[11] = _bar(11, high="15", low="12")
        bars[12] = _bar(12, high="15", low="11")
        reason = "BULL_STRUCTURE_BROKEN"
    else:
        pivots, patterns = _bear_evidence()
        bars = _bars(13, high="12", low="9")
        bars[11] = _bar(11, high="12", low="9")
        bars[12] = _bar(12, high="13", low="9")
        reason = "BEAR_STRUCTURE_BROKEN"

    equal = _evaluate(bars[:12], pivots, patterns)
    broken = _evaluate(bars, pivots, patterns)

    assert equal.snapshots[-1].kind is direction
    assert broken.snapshots[-1].kind is NStructureKind.RANGE
    assert broken.snapshots[-1].trailing_defense is None
    assert broken.transitions[-1].reason_code == reason
    assert broken.transitions[-1].to_kind is NStructureKind.RANGE


def test_outside_checks_existing_defense_before_reset_and_can_break() -> None:
    pivots, patterns = _bull_evidence(lows=("8", "9", "10"))
    bars = _bars(12, high="15", low="10")
    bars[10] = _bar(10, high="15", low="11")
    bars[11] = _bar(11, high="16", low="9")

    trace = _evaluate(bars, pivots, patterns, reset_indices=(11,))

    assert trace.transitions[-1].reason_code == "BULL_STRUCTURE_BROKEN"
    assert trace.snapshots[-1].kind is NStructureKind.RANGE
    assert trace.snapshots[-1].epoch == 1


def test_outside_without_break_preserves_direction_but_resets_evidence_epoch() -> None:
    pivots, patterns = _bull_evidence(lows=("8", "9", "10"))
    bars = _bars(12, high="15", low="10")
    bars[10] = _bar(10, high="15", low="11")
    bars[11] = _bar(11, high="16", low="10")

    trace = _evaluate(bars, pivots, patterns, reset_indices=(11,))

    snapshot = trace.snapshots[-1]
    assert snapshot.kind is NStructureKind.BULL
    assert snapshot.epoch == 1
    assert snapshot.completed_n_count_in_epoch == 0
    assert snapshot.trailing_defense == pivots[-1]


def test_opposite_post_reset_evidence_cannot_reverse_unbroken_structure() -> None:
    bull_pivots, bull_patterns = _bull_evidence(lows=("3", "4", "5"))
    bear_pivots, bear_patterns = _bear_evidence(
        epoch=1,
        offset=12,
        highs=("14", "13", "12"),
        lows=("11", "9"),
    )
    bars = _bars(23, high="15", low="8")
    bars[10] = _bar(10, high="15", low="7")
    bars[11] = _bar(11, high="16", low="6")

    trace = _evaluate(
        bars,
        bull_pivots + bear_pivots,
        bull_patterns + bear_patterns,
        reset_indices=(11,),
    )

    assert trace.snapshots[-1].kind is NStructureKind.BULL
    assert trace.snapshots[-1].trailing_defense == bull_pivots[-1]
    assert all(transition.to_kind is not NStructureKind.BEAR for transition in trace.transitions)


def test_range_reestablishes_only_from_two_completed_n_in_current_epoch() -> None:
    range_pivots, range_patterns = _range_evidence()
    bull_pivots, bull_patterns = _bull_evidence(epoch=1, offset=12)
    bars = _bars(23)
    bars[10] = _bar(10, high="15", low="13")
    bars[11] = _bar(11, high="16", low="12")

    one_new_n = _evaluate(
        bars[:22],
        range_pivots + bull_pivots,
        range_patterns + bull_patterns[:1],
        reset_indices=(11,),
    )
    full = _evaluate(
        bars,
        range_pivots + bull_pivots,
        range_patterns + bull_patterns,
        reset_indices=(11,),
    )

    assert one_new_n.snapshots[-1].kind is NStructureKind.RANGE
    assert one_new_n.snapshots[-1].completed_n_count_in_epoch == 1
    assert full.snapshots[-1].kind is NStructureKind.BULL
    assert full.snapshots[-1].epoch == 1
    assert full.snapshots[-1].trailing_defense == bull_pivots[-1]


def test_same_boundary_initial_establishment_then_new_defense_breaks_to_range() -> None:
    pivots, patterns = _bull_evidence()
    bars = _bars(11)
    bars[10] = _bar(10, high="15", low="11")

    trace = _evaluate(bars, pivots, patterns)

    same_boundary = tuple(
        transition for transition in trace.transitions if transition.transition_at == bars[10].bar_end
    )
    assert tuple(transition.reason_code for transition in same_boundary) == (
        "BULL_STRUCTURE_ESTABLISHED",
        "BULL_STRUCTURE_BROKEN",
    )
    assert tuple(transition.to_kind for transition in same_boundary) == (
        NStructureKind.BULL,
        NStructureKind.RANGE,
    )
    assert trace.snapshots[-1].kind is NStructureKind.RANGE
    _assert_prefix_invariant(bars, pivots, patterns)


def test_same_boundary_defense_advance_then_new_defense_breaks_to_range() -> None:
    pivots, patterns = _bull_evidence()
    new_high = _pivot(11, confirmed_index=12, kind=NSwingPivotKind.HIGH, price="16")
    new_defense = _pivot(13, confirmed_index=14, kind=NSwingPivotKind.LOW, price="13")
    bars = _bars(15)
    bars[14] = _bar(14, high="15", low="12")

    trace = _evaluate(bars, pivots + (new_high, new_defense), patterns)

    same_boundary = tuple(
        transition for transition in trace.transitions if transition.transition_at == bars[14].bar_end
    )
    assert tuple(transition.reason_code for transition in same_boundary) == (
        "BULL_TRAILING_DEFENSE_ADVANCED",
        "BULL_STRUCTURE_BROKEN",
    )
    assert tuple(transition.to_kind for transition in same_boundary) == (
        NStructureKind.BULL,
        NStructureKind.RANGE,
    )
    assert same_boundary[0].trailing_defense_pivot_id == new_defense.pivot_id
    assert trace.snapshots[-1].kind is NStructureKind.RANGE
    _assert_prefix_invariant(bars, pivots + (new_high, new_defense), patterns)


def test_exact_policy_series_and_trace_inputs_fail_closed() -> None:
    pivots, patterns = _bull_evidence()
    bars = _bars(11)
    policy = load_n_structure_policy()

    with pytest.raises(ValueError, match="N_STRUCTURE_CONTRACT_INVALID"):
        _evaluate(bars, pivots, patterns, policy=replace(policy, research_only=False))

    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        _evaluate(list(reversed(bars)), pivots, patterns)

    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        evaluate_n_market_structure(
            tuple(bars),
            swings=_swing(pivots[:-1]),
            patterns=_patterns(patterns),
            policy=policy,
        )

    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        evaluate_n_market_structure(
            tuple(bars),
            swings=_swing(pivots),
            patterns=replace(_patterns(patterns), patterns=list(patterns)),  # type: ignore[arg-type]
            policy=policy,
        )

    reset_bars = _bars(12)
    reset_bars[9] = _bar(9, high="15", low="13")
    reset_bars[10] = _bar(10, high="16", low="12")
    post_reset_completion = replace(patterns[1], completed_at=reset_bars[11].bar_end)
    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        evaluate_n_market_structure(
            tuple(reset_bars),
            swings=_swing(pivots, reset_indices=(10,)),
            patterns=_patterns((patterns[0], post_reset_completion)),
            policy=policy,
        )


def test_structure_trace_is_frozen_and_prefix_invariant() -> None:
    pivots, patterns = _bull_evidence()
    new_high = _pivot(11, confirmed_index=12, kind=NSwingPivotKind.HIGH, price="16")
    new_defense = _pivot(13, confirmed_index=14, kind=NSwingPivotKind.LOW, price="13")
    bars = _bars(16)
    bars[15] = _bar(15, high="15", low="12")

    trace = _evaluate(bars, pivots + (new_high, new_defense), patterns)

    with pytest.raises(FrozenInstanceError):
        trace.snapshots[-1].kind = NStructureKind.BEAR  # type: ignore[misc]
    _assert_prefix_invariant(bars, pivots + (new_high, new_defense), patterns)
