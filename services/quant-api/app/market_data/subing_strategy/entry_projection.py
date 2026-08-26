"""Project causal Lifecycle confirmations onto completed 15m boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from ..domain import CanonicalBar
from ..subing_lifecycle import (
    ConfirmationSource,
    LifecycleStage,
    SubingLifecycleSnapshot,
    SubingLifecycleTrace,
    SubingLifecycleTransition,
    SubingOpportunityKey,
)
from ..subing_research import SubingDirection
from ..subing_structure import ConfirmedPivot, PivotKind
from .contracts import subing_opportunity_key_id
from .direction_context import SubingStrategyContextIdentityError


_TERMINAL_CANCELLATION_STAGES = frozenset(
    {LifecycleStage.EXIT_RISK, LifecycleStage.CLOSED}
)
def _is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


@dataclass(frozen=True, slots=True)
class SubingStrategyEntryCandidate:
    opportunity_key: SubingOpportunityKey
    opportunity_id: str
    direction: SubingDirection
    confirmation_source: ConfirmationSource
    confirmed_at: datetime
    decision_bar_end: datetime
    bound_reference_pivot: ConfirmedPivot | None

    def __post_init__(self) -> None:
        pivot = self.bound_reference_pivot
        expected_pivot_kind = (
            PivotKind.LOW
            if self.direction is SubingDirection.LONG
            else PivotKind.HIGH
        )
        if (
            not isinstance(self.opportunity_key, SubingOpportunityKey)
            or self.opportunity_id
            != subing_opportunity_key_id(self.opportunity_key)
            or self.direction is not self.opportunity_key.direction
            or not isinstance(self.confirmation_source, ConfirmationSource)
            or not _is_aware(self.confirmed_at)
            or not _is_aware(self.decision_bar_end)
            or self.confirmed_at > self.decision_bar_end
            or (
                pivot is not None
                and (
                    not isinstance(pivot, ConfirmedPivot)
                    or pivot.kind is not expected_pivot_kind
                    or pivot.contract != self.opportunity_key.contract
                    or pivot.segment_start_trading_day
                    != self.opportunity_key.segment_start_trading_day
                )
            )
        ):
            raise SubingStrategyContextIdentityError()
        object.__setattr__(self, "confirmed_at", self.confirmed_at.astimezone(UTC))
        object.__setattr__(
            self,
            "decision_bar_end",
            self.decision_bar_end.astimezone(UTC),
        )


def project_lifecycle_entries(
    trace: SubingLifecycleTrace,
    bars_15m: Sequence[CanonicalBar],
) -> Mapping[datetime, tuple[SubingStrategyEntryCandidate, ...]]:
    """Return the first causal entry confirmation in each 15m window."""
    bars = tuple(bars_15m)
    _validate_projection_identity(trace, bars)
    projected: dict[datetime, tuple[SubingStrategyEntryCandidate, ...]] = {}
    consumed: set[SubingOpportunityKey] = set()
    previous = datetime.min.replace(tzinfo=UTC)
    entry_transitions = tuple(
        transition
        for transition in trace.transitions
        if transition.to_stage is LifecycleStage.ENTRY_CONFIRMED
    )
    confirmation_matches_by_transition: dict[
        str,
        list[SubingLifecycleSnapshot],
    ] = {}
    for snapshot in trace.snapshots:
        if snapshot.latest_transition is None:
            continue
        confirmation_matches_by_transition.setdefault(
            snapshot.latest_transition.transition_id,
            [],
        ).append(snapshot)

    transition_cursor = 0
    snapshot_cursor = 0
    latest_by_opportunity: dict[SubingOpportunityKey, SubingLifecycleSnapshot] = {}
    for bar in bars:
        current = bar.bar_end
        while snapshot_cursor < len(trace.snapshots):
            snapshot = trace.snapshots[snapshot_cursor]
            if snapshot.observed_at is None or snapshot.observed_at > current:
                break
            if snapshot.opportunity_key is not None:
                latest_by_opportunity[snapshot.opportunity_key] = snapshot
            snapshot_cursor += 1
        candidates: list[SubingStrategyEntryCandidate] = []
        while transition_cursor < len(entry_transitions):
            transition = entry_transitions[transition_cursor]
            if transition.transition_at > current:
                break
            transition_cursor += 1
            key = transition.opportunity_key
            if key in consumed or transition.transition_at <= previous:
                continue
            consumed.add(key)
            confirmation_matches = tuple(
                snapshot
                for snapshot in confirmation_matches_by_transition.get(
                    transition.transition_id,
                    (),
                )
                if snapshot.latest_transition is not None
                and snapshot.latest_transition.transition_id
                == transition.transition_id
                and snapshot.observed_at == transition.transition_at
                and snapshot.opportunity_key == key
            )
            if len(confirmation_matches) != 1:
                raise SubingStrategyContextIdentityError()
            confirmation_snapshot = confirmation_matches[0]
            latest = latest_by_opportunity.get(key)
            if latest is None:
                raise SubingStrategyContextIdentityError()
            if latest.stage in _TERMINAL_CANCELLATION_STAGES:
                continue
            candidates.append(
                _candidate_from_confirmation(
                    transition,
                    confirmation_snapshot,
                    decision_bar_end=current,
                )
            )
        projected[current] = tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    candidate.confirmed_at,
                    candidate.opportunity_id,
                ),
            )
        )
        previous = current
    return MappingProxyType(projected)


def _validate_projection_identity(
    trace: SubingLifecycleTrace,
    bars: tuple[CanonicalBar, ...],
) -> None:
    if (
        not isinstance(trace, SubingLifecycleTrace)
        or not isinstance(trace.symbol, str)
        or not isinstance(trace.contract, str)
        or trace.segment_start_trading_day is None
        or any(not isinstance(bar, CanonicalBar) for bar in bars)
        or any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:]))
        or any(bar.trading_day < trace.segment_start_trading_day for bar in bars)
    ):
        raise SubingStrategyContextIdentityError()
    for transition in trace.transitions:
        if not _key_matches_trace(transition.opportunity_key, trace):
            raise SubingStrategyContextIdentityError()
    for snapshot in trace.snapshots:
        if (
            snapshot.opportunity_key is not None
            and not _key_matches_trace(snapshot.opportunity_key, trace)
        ):
            raise SubingStrategyContextIdentityError()


def _key_matches_trace(
    key: SubingOpportunityKey,
    trace: SubingLifecycleTrace,
) -> bool:
    return (
        key.symbol == trace.symbol
        and key.contract == trace.contract
        and key.segment_start_trading_day == trace.segment_start_trading_day
        and key.policy_id == trace.policy_id
    )


def _candidate_from_confirmation(
    transition: SubingLifecycleTransition,
    snapshot: SubingLifecycleSnapshot,
    *,
    decision_bar_end: datetime,
) -> SubingStrategyEntryCandidate:
    if (
        snapshot.stage is not LifecycleStage.ENTRY_CONFIRMED
        or snapshot.confirmation_source is None
        or snapshot.confirmed_at != transition.transition_at
    ):
        raise SubingStrategyContextIdentityError()
    return SubingStrategyEntryCandidate(
        opportunity_key=transition.opportunity_key,
        opportunity_id=subing_opportunity_key_id(transition.opportunity_key),
        direction=transition.opportunity_key.direction,
        confirmation_source=snapshot.confirmation_source,
        confirmed_at=transition.transition_at,
        decision_bar_end=decision_bar_end,
        bound_reference_pivot=_directional_structure_pivot(
            snapshot.bound_reference_pivot,
            key=transition.opportunity_key,
        ),
    )


def _directional_structure_pivot(
    pivot: ConfirmedPivot | None,
    *,
    key: SubingOpportunityKey,
) -> ConfirmedPivot | None:
    if pivot is None:
        return None
    if (
        not isinstance(pivot, ConfirmedPivot)
        or pivot.contract != key.contract
        or pivot.segment_start_trading_day != key.segment_start_trading_day
    ):
        raise SubingStrategyContextIdentityError()
    expected_kind = (
        PivotKind.LOW if key.direction is SubingDirection.LONG else PivotKind.HIGH
    )
    return pivot if pivot.kind is expected_kind else None
