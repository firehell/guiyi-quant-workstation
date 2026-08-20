from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.n_structure_pattern import (
    CompletedNPattern,
    NPatternTrace,
    NRangeBand,
    NRangeBandRole,
    evaluate_n_patterns,
)
from app.market_data.n_structure_policy import (
    NStructurePolicy,
    load_n_structure_policy,
)
from app.market_data.n_structure_state import (
    NStructureKind,
    NStructureTrace,
    evaluate_n_market_structure,
)
from app.market_data.n_structure_swing import (
    NStructureSeriesError,
    NSwingPivot,
    NSwingTrace,
    reduce_n_swings,
)


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_START = datetime(2026, 8, 19, 1, 5, tzinfo=UTC)

_BULL_VALUES = (
    ("10", "9"),
    ("9", "8.5"),
    ("8.5", "8"),
    ("9.5", "8.2"),
    ("12", "9"),
    ("11", "8.8"),
    ("13", "9"),
    ("14", "10"),
    ("13", "9.5"),
    ("15", "10"),
)

_BULL_LATE_PAIR_VALUES = _BULL_VALUES + (
    ("14", "9.8"),
    ("14.5", "10"),
    ("14.8", "10.2"),
    ("14", "9.9"),
    ("14.5", "10.1"),
    ("16", "10.2"),
    ("15", "10.1"),
)

# Real Task 2/3 producer fixture whose final boundary knows both a new BEAR
# establishment and a strict crossing of the newly selected defense.
_SAME_BOUNDARY_ESTABLISHMENT_VALUES = (
    ("103.5", "97.5"),
    ("106", "94"),
    ("101.5", "93.5"),
    ("100", "96"),
    ("102", "98"),
    ("102.5", "94.5"),
    ("99", "91"),
    ("100", "92"),
    ("97", "89"),
    ("101", "93"),
    ("106", "94"),
    ("106.5", "94.5"),
    ("102.5", "94.5"),
    ("99", "95"),
    ("95", "89"),
    ("100.5", "90.5"),
    ("100", "92"),
    ("99", "95"),
    ("99", "87"),
    ("93", "89"),
    ("97.5", "89.5"),
    ("102", "92"),
    ("97.5", "91.5"),
    ("101.5", "93.5"),
    ("101", "89"),
    ("106", "94"),
)


def _bars(values: tuple[tuple[str, str], ...]) -> tuple[CanonicalBar, ...]:
    result: list[CanonicalBar] = []
    for index, (high, low) in enumerate(values):
        high_value = Decimal(high)
        low_value = Decimal(low)
        midpoint = (high_value + low_value) / Decimal(2)
        result.append(
            CanonicalBar(
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
        )
    return tuple(result)


def _mirror(values: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    center = Decimal("30")
    return tuple(
        (str(center - Decimal(low)), str(center - Decimal(high)))
        for high, low in values
    )


def _range_values() -> tuple[tuple[str, str], ...]:
    values = list(_BULL_VALUES)
    values[8] = ("13", "8.8")
    values[9] = ("15", "9")
    return tuple(values)


def _range_reset_one_n_values() -> tuple[tuple[str, str], ...]:
    return _range_values() + (
        ("16", "8"),
        ("13", "7.5"),
        ("12", "7"),
        ("13", "7.2"),
        ("15", "8"),
        ("14", "7.5"),
        ("16", "8"),
    )


def _range_reset_two_n_values() -> tuple[tuple[str, str], ...]:
    return _range_reset_one_n_values() + (
        ("17", "9"),
        ("16", "8.5"),
        ("18", "9"),
    )


def _producer(
    bars: tuple[CanonicalBar, ...],
    *,
    policy: NStructurePolicy | None = None,
) -> tuple[NSwingTrace, NPatternTrace, NStructurePolicy]:
    exact_policy = policy if policy is not None else load_n_structure_policy()
    segment_end = max((bar.trading_day for bar in bars), default=_SEGMENT_START)
    swings = reduce_n_swings(
        bars,
        source_timeframe=BarFrequency.M5,
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        segment_end_trading_day=segment_end,
    )
    patterns = evaluate_n_patterns(bars, swings, policy=exact_policy)
    return swings, patterns, exact_policy


def _evaluate(bars: tuple[CanonicalBar, ...]) -> NStructureTrace:
    swings, patterns, policy = _producer(bars)
    return evaluate_n_market_structure(
        bars,
        swings=swings,
        patterns=patterns,
        policy=policy,
    )


def _replace_pivot_in_patterns(
    trace: NPatternTrace,
    *,
    old: NSwingPivot,
    new: NSwingPivot,
) -> NPatternTrace:
    replacements: list[CompletedNPattern] = []
    for pattern in trace.patterns:
        changes: dict[str, object] = {}
        if pattern.origin == old:
            changes["origin"] = new
        if pattern.n1_extreme == old:
            changes["n1_extreme"] = new
        if pattern.n2_origin == old:
            changes["n2_origin"] = new
        replacements.append(replace(pattern, **changes))
    return replace(trace, patterns=tuple(replacements))


def _assert_series_invalid(callable_: object) -> None:
    assert callable(callable_)
    with pytest.raises(NStructureSeriesError) as captured:
        callable_()
    assert captured.value.code == "N_STRUCTURE_SERIES_INVALID"
    assert str(captured.value) == "N_STRUCTURE_SERIES_INVALID"


def _assert_prefix_invariant(values: tuple[tuple[str, str], ...]) -> None:
    bars = _bars(values)
    full = _evaluate(bars)
    for length in range(1, len(bars) + 1):
        boundary = bars[length - 1].bar_end
        prefix = _evaluate(bars[:length])
        assert prefix.snapshots == tuple(
            snapshot
            for snapshot in full.snapshots
            if snapshot.observed_at <= boundary
        )
        assert prefix.transitions == tuple(
            transition
            for transition in full.transitions
            if transition.transition_at <= boundary
        )


def test_real_task2_task3_task4_producer_chain_establishes_bull() -> None:
    bars = _bars(_BULL_VALUES)
    swings, patterns, policy = _producer(bars)

    trace = evaluate_n_market_structure(
        bars,
        swings=swings,
        patterns=patterns,
        policy=policy,
    )

    assert len(patterns.patterns) == 2
    assert trace.snapshots[-1].kind is NStructureKind.BULL
    assert trace.snapshots[-1].trailing_defense == swings.pivots[-1]
    assert trace.snapshots[-1].completed_n_count_in_epoch == 2


def test_less_than_two_completed_n_stays_undefined() -> None:
    trace = _evaluate(_bars(_BULL_VALUES[:7]))

    assert trace.transitions == ()
    assert trace.snapshots[-1].kind is NStructureKind.UNDEFINED
    assert trace.snapshots[-1].completed_n_count_in_epoch == 1


@pytest.mark.parametrize(
    ("values", "expected"),
    (
        (_BULL_VALUES, NStructureKind.BULL),
        (_mirror(_BULL_VALUES), NStructureKind.BEAR),
        (_range_values(), NStructureKind.RANGE),
    ),
)
def test_exact_strict_classification_matrix(
    values: tuple[tuple[str, str], ...],
    expected: NStructureKind,
) -> None:
    trace = _evaluate(_bars(values))

    assert trace.snapshots[-1].kind is expected
    assert trace.transitions[-1].to_kind is expected


def test_range_outside_reset_returns_to_undefined_with_zero_current_evidence() -> None:
    values = _range_reset_one_n_values()
    trace = _evaluate(_bars(values[:11]))

    snapshot = trace.snapshots[-1]
    assert snapshot.epoch == 1
    assert snapshot.kind is NStructureKind.UNDEFINED
    assert snapshot.established_at is None
    assert snapshot.completed_n_count_in_epoch == 0
    assert trace.transitions[-1].from_kind is NStructureKind.RANGE
    assert trace.transitions[-1].to_kind is NStructureKind.UNDEFINED
    assert trace.transitions[-1].reason_code == "RANGE_EVIDENCE_EPOCH_RESET"


def test_new_epoch_one_completed_n_remains_undefined() -> None:
    trace = _evaluate(_bars(_range_reset_one_n_values()))

    snapshot = trace.snapshots[-1]
    assert snapshot.epoch == 1
    assert snapshot.kind is NStructureKind.UNDEFINED
    assert snapshot.established_at is None
    assert snapshot.completed_n_count_in_epoch == 1


def test_range_reestablishes_only_after_two_n_in_current_epoch() -> None:
    one_n = _evaluate(_bars(_range_reset_one_n_values()))
    two_n = _evaluate(_bars(_range_reset_two_n_values()))

    assert one_n.snapshots[-1].kind is NStructureKind.UNDEFINED
    assert two_n.snapshots[-1].kind is NStructureKind.BULL
    assert two_n.snapshots[-1].epoch == 1
    assert two_n.snapshots[-1].completed_n_count_in_epoch == 2


def test_outside_without_break_preserves_unbroken_bull_only() -> None:
    values = _BULL_VALUES + (("16", "9.5"),)
    trace = _evaluate(_bars(values))

    snapshot = trace.snapshots[-1]
    assert snapshot.epoch == 1
    assert snapshot.kind is NStructureKind.BULL
    assert snapshot.trailing_defense is not None
    assert snapshot.trailing_defense.price == Decimal("9.5")
    assert snapshot.completed_n_count_in_epoch == 0


def test_outside_breaks_existing_bull_before_epoch_reset() -> None:
    values = _BULL_VALUES + (("16", "9.4"),)
    trace = _evaluate(_bars(values))

    assert trace.snapshots[-1].epoch == 1
    assert trace.snapshots[-1].kind is NStructureKind.RANGE
    assert trace.transitions[-1].reason_code == "BULL_STRUCTURE_BROKEN"


@pytest.mark.parametrize(
    ("values", "kind", "reason", "before", "after"),
    (
        (
            _BULL_LATE_PAIR_VALUES,
            NStructureKind.BULL,
            "BULL_TRAILING_DEFENSE_ADVANCED",
            Decimal("9.8"),
            Decimal("9.9"),
        ),
        (
            _mirror(_BULL_LATE_PAIR_VALUES),
            NStructureKind.BEAR,
            "BEAR_TRAILING_DEFENSE_ADVANCED",
            Decimal("20.2"),
            Decimal("20.1"),
        ),
    ),
)
def test_non_defense_pivot_can_complete_new_qualifying_pair(
    values: tuple[tuple[str, str], ...],
    kind: NStructureKind,
    reason: str,
    before: Decimal,
    after: Decimal,
) -> None:
    before_confirmation = _evaluate(_bars(values[:-1]))
    after_confirmation = _evaluate(_bars(values))

    assert before_confirmation.snapshots[-1].kind is kind
    assert before_confirmation.snapshots[-1].trailing_defense is not None
    assert before_confirmation.snapshots[-1].trailing_defense.price == before
    assert after_confirmation.snapshots[-1].kind is kind
    assert after_confirmation.snapshots[-1].trailing_defense is not None
    assert after_confirmation.snapshots[-1].trailing_defense.price == after
    assert after_confirmation.transitions[-1].reason_code == reason


@pytest.mark.parametrize(
    ("values", "kind", "reason"),
    (
        (
            _BULL_VALUES + (("14", "9.5"), ("14", "9.4")),
            NStructureKind.BULL,
            "BULL_STRUCTURE_BROKEN",
        ),
        (
            _mirror(_BULL_VALUES + (("14", "9.5"), ("14", "9.4"))),
            NStructureKind.BEAR,
            "BEAR_STRUCTURE_BROKEN",
        ),
    ),
)
def test_existing_defense_break_is_strict_and_equal_does_not_break(
    values: tuple[tuple[str, str], ...],
    kind: NStructureKind,
    reason: str,
) -> None:
    equal = _evaluate(_bars(values[:-1]))
    broken = _evaluate(_bars(values))

    assert equal.snapshots[-1].kind is kind
    assert broken.snapshots[-1].kind is NStructureKind.RANGE
    assert broken.transitions[-1].reason_code == reason


def test_same_boundary_initial_establishment_then_new_defense_breaks() -> None:
    bars = _bars(_SAME_BOUNDARY_ESTABLISHMENT_VALUES)
    trace = _evaluate(bars)
    transitions = tuple(
        transition
        for transition in trace.transitions
        if transition.transition_at == bars[-1].bar_end
    )

    assert tuple(transition.reason_code for transition in transitions) == (
        "BEAR_STRUCTURE_ESTABLISHED",
        "BEAR_STRUCTURE_BROKEN",
    )
    assert tuple(transition.to_kind for transition in transitions) == (
        NStructureKind.BEAR,
        NStructureKind.RANGE,
    )
    assert trace.snapshots[-1].kind is NStructureKind.RANGE


def test_same_boundary_defense_advance_then_new_defense_breaks() -> None:
    values = _BULL_LATE_PAIR_VALUES[:-1] + (("15", "9.85"),)
    bars = _bars(values)
    trace = _evaluate(bars)
    transitions = tuple(
        transition
        for transition in trace.transitions
        if transition.transition_at == bars[-1].bar_end
    )

    assert tuple(transition.reason_code for transition in transitions) == (
        "BULL_TRAILING_DEFENSE_ADVANCED",
        "BULL_STRUCTURE_BROKEN",
    )
    assert tuple(transition.to_kind for transition in transitions) == (
        NStructureKind.BULL,
        NStructureKind.RANGE,
    )
    assert trace.snapshots[-1].kind is NStructureKind.RANGE


def test_tampered_pivot_price_fails_exact_trace_validation() -> None:
    bars = _bars(_BULL_VALUES)
    swings, patterns, policy = _producer(bars)
    original = swings.pivots[-1]
    tampered = replace(original, price=original.price + Decimal("0.1"))
    supplied_swings = replace(swings, pivots=swings.pivots[:-1] + (tampered,))
    supplied_patterns = _replace_pivot_in_patterns(
        patterns,
        old=original,
        new=tampered,
    )

    _assert_series_invalid(
        lambda: evaluate_n_market_structure(
            bars,
            swings=supplied_swings,
            patterns=supplied_patterns,
            policy=policy,
        )
    )


def test_tampered_pivot_confirmation_fails_exact_trace_validation() -> None:
    bars = _bars(_BULL_VALUES)
    swings, patterns, policy = _producer(bars)
    original = swings.pivots[0]
    tampered = replace(original, confirmed_at=bars[4].bar_end)
    supplied_swings = replace(swings, pivots=(tampered,) + swings.pivots[1:])
    supplied_patterns = _replace_pivot_in_patterns(
        patterns,
        old=original,
        new=tampered,
    )

    _assert_series_invalid(
        lambda: evaluate_n_market_structure(
            bars,
            swings=supplied_swings,
            patterns=supplied_patterns,
            policy=policy,
        )
    )


def test_tampered_completion_close_overshoot_or_band_fails_exact_trace() -> None:
    bars = _bars(_BULL_VALUES)
    swings, patterns, policy = _producer(bars)
    original = patterns.patterns[0]
    changed_band = NRangeBand(
        lower=original.range_band.lower,
        upper=original.range_band.upper,
        role=NRangeBandRole.RESISTANCE_REFERENCE,
    )
    tampered_patterns = (
        replace(original, completion_bar_close=Decimal("1")),
        replace(
            original,
            completion_overshoot_bps=original.completion_overshoot_bps
            + Decimal("1"),
        ),
        replace(original, range_band=changed_band),
    )

    for tampered in tampered_patterns:
        supplied = replace(patterns, patterns=(tampered,) + patterns.patterns[1:])
        _assert_series_invalid(
            lambda supplied=supplied: evaluate_n_market_structure(
                bars,
                swings=swings,
                patterns=supplied,
                policy=policy,
            )
        )


def test_illegal_trace_tuple_elements_fail_with_stable_series_error() -> None:
    bars = _bars(_BULL_VALUES)
    swings, patterns, policy = _producer(bars)
    invalid_inputs = (
        (replace(swings, pivots=(object(),)), patterns),  # type: ignore[arg-type]
        (swings, replace(patterns, patterns=(object(),))),  # type: ignore[arg-type]
    )

    for supplied_swings, supplied_patterns in invalid_inputs:
        _assert_series_invalid(
            lambda supplied_swings=supplied_swings,
            supplied_patterns=supplied_patterns: evaluate_n_market_structure(
                bars,
                swings=supplied_swings,
                patterns=supplied_patterns,
                policy=policy,
            )
        )


def test_exact_policy_and_unsorted_series_fail_closed() -> None:
    bars = _bars(_BULL_VALUES)
    swings, patterns, policy = _producer(bars)

    with pytest.raises(ValueError, match="N_STRUCTURE_CONTRACT_INVALID"):
        evaluate_n_market_structure(
            bars,
            swings=swings,
            patterns=patterns,
            policy=replace(policy, research_only=False),
        )
    with pytest.raises(NStructureSeriesError):
        evaluate_n_market_structure(
            tuple(reversed(bars)),
            swings=swings,
            patterns=patterns,
            policy=policy,
        )


@pytest.mark.parametrize(
    "values",
    (
        _BULL_VALUES,
        _range_reset_two_n_values(),
        _SAME_BOUNDARY_ESTABLISHMENT_VALUES,
        _BULL_LATE_PAIR_VALUES[:-1] + (("15", "9.85"),),
    ),
)
def test_structure_facts_are_prefix_invariant(
    values: tuple[tuple[str, str], ...],
) -> None:
    _assert_prefix_invariant(values)


def test_structure_snapshots_are_frozen() -> None:
    trace = _evaluate(_bars(_BULL_VALUES))

    with pytest.raises(FrozenInstanceError):
        trace.snapshots[-1].kind = NStructureKind.BEAR  # type: ignore[misc]
