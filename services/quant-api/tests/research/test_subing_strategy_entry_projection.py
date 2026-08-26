from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_lifecycle import (
    ConfirmationSource,
    LifecycleStage,
    SubingLifecycleTrace,
)
from app.market_data.subing_research import MacdCross, SubingDirection
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyContextIdentityError,
)
from app.market_data.subing_strategy.entry_projection import (
    SubingStrategyEntryCandidate,
    project_lifecycle_entries,
)
from app.market_data.subing_structure import PivotKind

from .subing_lifecycle_fixtures import (
    _bar,
    _evaluate,
    _factor,
    _long_pivot_prefix,
)


def _decision_bars() -> tuple[CanonicalBar, ...]:
    return tuple(_bar(minutes) for minutes in (15, 30, 45, 60))


def _trace_for_source(source: ConfirmationSource) -> SubingLifecycleTrace:
    if source is ConfirmationSource.FORMAL_V1:
        boundary = _bar(15)
        return _evaluate(
            (boundary,),
            factors_5m=(
                _factor(
                    boundary,
                    BarFrequency.M5,
                    cross=MacdCross.GOLDEN,
                    volume_ratio=Decimal("3"),
                ),
            ),
            bars_15m=(boundary,),
        )
    if source is ConfirmationSource.MOMENTUM_HOLD:
        bars = tuple(_bar(minutes) for minutes in (5, 10, 15, 20))
        return _evaluate(
            bars,
            factors_5m=tuple(
                _factor(
                    bar,
                    BarFrequency.M5,
                    cross=(MacdCross.GOLDEN if index == 1 else MacdCross.NONE),
                )
                for index, bar in enumerate(bars)
            ),
            bars_15m=(_bar(0),),
        )
    if source is ConfirmationSource.PIVOT_BREAK_HOLD:
        bars = (
            *_long_pivot_prefix(),
            _bar(35, close="112", high="113", low="111"),
            _bar(40, close="113", high="114", low="112"),
        )
        return _evaluate(bars, bars_15m=(_bar(15), _bar(30)))
    bars = (
        *_long_pivot_prefix(),
        _bar(35, close="111", high="112", low="109"),
        _bar(40, close="114", high="114", low="111"),
        _bar(45, close="116", high="117", low="113"),
    )
    return _evaluate(bars, bars_15m=(_bar(15), _bar(30), _bar(45)))


def _confirmed_at(trace: SubingLifecycleTrace) -> datetime:
    return next(
        transition.transition_at
        for transition in trace.transitions
        if transition.to_stage is LifecycleStage.ENTRY_CONFIRMED
    )


def _all_candidates(
    projected: MappingProxyType[datetime, tuple[SubingStrategyEntryCandidate, ...]],
) -> tuple[SubingStrategyEntryCandidate, ...]:
    return tuple(candidate for candidates in projected.values() for candidate in candidates)


@pytest.mark.parametrize("source", tuple(ConfirmationSource))
def test_projects_each_allowed_source_once(source: ConfirmationSource) -> None:
    trace = _trace_for_source(source)

    projected = project_lifecycle_entries(trace, _decision_bars())
    candidates = _all_candidates(projected)

    assert len(candidates) == 1
    assert candidates[0].confirmation_source is source
    assert candidates[0].confirmed_at == _confirmed_at(trace)
    assert candidates[0].decision_bar_end >= candidates[0].confirmed_at


def test_confirmation_equal_to_boundary_belongs_to_that_boundary() -> None:
    trace = _trace_for_source(ConfirmationSource.FORMAL_V1)
    boundary = _decision_bars()[0]

    projected = project_lifecycle_entries(trace, _decision_bars())

    assert projected[boundary.bar_end][0].confirmed_at == boundary.bar_end


@pytest.mark.parametrize("terminal_stage", (LifecycleStage.EXIT_RISK, LifecycleStage.CLOSED))
def test_window_terminal_risk_or_close_cancels_candidate(
    terminal_stage: LifecycleStage,
) -> None:
    bars = tuple(_bar(minutes) for minutes in (5, 10, 15, 20, 25, 30))
    factors_5m = tuple(
        _factor(
            bar,
            BarFrequency.M5,
            direction=(
                SubingDirection.SHORT
                if terminal_stage is LifecycleStage.CLOSED and index == 5
                else SubingDirection.LONG
            ),
            cross=(MacdCross.GOLDEN if index == 1 else MacdCross.NONE),
        )
        for index, bar in enumerate(bars)
    )
    final_anchor = (
        _factor(
            _bar(30),
            BarFrequency.M15,
            direction=SubingDirection.SHORT,
        )
        if terminal_stage is LifecycleStage.CLOSED
        else _factor(_bar(30), BarFrequency.M15, ema21="101")
    )
    trace = _evaluate(
        bars,
        factors_5m=factors_5m,
        bars_15m=(_bar(0), _bar(30)),
        factors_15m=(
            _factor(_bar(0), BarFrequency.M15),
            final_anchor,
        ),
    )
    assert _confirmed_at(trace) == _bar(20).bar_end
    assert trace.current_snapshot.stage is terminal_stage

    projected = project_lifecycle_entries(trace, _decision_bars())

    assert projected[_bar(30).bar_end] == ()


def test_first_confirmation_for_opportunity_wins_despite_later_snapshots() -> None:
    trace = _trace_for_source(ConfirmationSource.MOMENTUM_HOLD)

    projected = project_lifecycle_entries(trace, _decision_bars())

    candidates = _all_candidates(projected)
    assert len(candidates) == 1
    assert candidates[0].confirmed_at == _confirmed_at(trace)


@pytest.mark.parametrize("identity_fault", ("missing", "duplicate"))
def test_confirmation_snapshot_is_bound_uniquely_by_transition_id(
    identity_fault: str,
) -> None:
    trace = _trace_for_source(ConfirmationSource.FORMAL_V1)
    confirmation = next(
        snapshot
        for snapshot in trace.snapshots
        if snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    )
    if identity_fault == "missing":
        object.__setattr__(confirmation, "latest_transition", None)
    else:
        object.__setattr__(trace, "snapshots", (*trace.snapshots, confirmation))

    with pytest.raises(SubingStrategyContextIdentityError):
        project_lifecycle_entries(trace, _decision_bars())


@pytest.mark.parametrize("pivot_fault", ("missing", "wrong_kind"))
def test_pivot_confirmation_requires_bound_directional_pivot(
    pivot_fault: str,
) -> None:
    trace = _trace_for_source(ConfirmationSource.PIVOT_BREAK_HOLD)
    confirmation = next(
        snapshot
        for snapshot in trace.snapshots
        if snapshot.stage is LifecycleStage.ENTRY_CONFIRMED
    )
    assert confirmation.bound_reference_pivot is not None
    if pivot_fault == "missing":
        object.__setattr__(confirmation, "bound_reference_pivot", None)
    else:
        object.__setattr__(confirmation.bound_reference_pivot, "kind", PivotKind.LOW)

    with pytest.raises(SubingStrategyContextIdentityError):
        project_lifecycle_entries(trace, _decision_bars())


def test_trace_segment_identity_must_match_every_opportunity() -> None:
    trace = _trace_for_source(ConfirmationSource.FORMAL_V1)
    object.__setattr__(trace, "contract", "JM2705")

    with pytest.raises(SubingStrategyContextIdentityError):
        project_lifecycle_entries(trace, _decision_bars())


def test_future_confirmation_is_not_projected_to_earlier_boundary() -> None:
    trace = _trace_for_source(ConfirmationSource.PIVOT_BREAK_HOLD)

    projected = project_lifecycle_entries(trace, _decision_bars()[:2])

    assert all(not candidates for candidates in projected.values())


def test_appending_later_snapshots_does_not_change_prior_projection() -> None:
    prefix = _trace_for_source(ConfirmationSource.MOMENTUM_HOLD)
    later_bar = _bar(25)
    extended = _evaluate(
        tuple(_bar(minutes) for minutes in (5, 10, 15, 20, 25)),
        factors_5m=tuple(
            _factor(
                _bar(minutes),
                BarFrequency.M5,
                cross=(MacdCross.GOLDEN if index == 1 else MacdCross.NONE),
            )
            for index, minutes in enumerate((5, 10, 15, 20, 25))
        ),
        bars_15m=(_bar(0),),
    )
    assert extended.current_snapshot.observed_at == later_bar.bar_end

    prefix_projection = project_lifecycle_entries(prefix, _decision_bars()[:2])
    extended_projection = project_lifecycle_entries(extended, _decision_bars())

    for boundary, candidates in prefix_projection.items():
        assert extended_projection[boundary] == candidates
