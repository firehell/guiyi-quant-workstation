"""Causal BULL/BEAR/RANGE structure and trailing-defense facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from . import n_structure_policy as _policy_contract
from .domain import BarFrequency, CanonicalBar
from .n_structure_pattern import (
    CompletedNPattern,
    NBreakEvent,
    NDirection,
    NPatternTrace,
    NRangeBandReentryEvent,
)
from .n_structure_policy import NStructurePolicy
from .n_structure_swing import (
    NStructureContractError,
    NStructureSeriesError,
    NSwingLeg,
    NSwingPivot,
    NSwingPivotKind,
    NSwingTrace,
)


class NStructureKind(StrEnum):
    UNDEFINED = "undefined"
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"


_REASON_CODES = frozenset(
    {
        "BULL_STRUCTURE_ESTABLISHED",
        "BEAR_STRUCTURE_ESTABLISHED",
        "RANGE_STRUCTURE_ESTABLISHED",
        "BULL_TRAILING_DEFENSE_ADVANCED",
        "BEAR_TRAILING_DEFENSE_ADVANCED",
        "BULL_STRUCTURE_BROKEN",
        "BEAR_STRUCTURE_BROKEN",
    }
)


@dataclass(frozen=True, slots=True)
class NStructureSnapshot:
    observed_at: datetime
    epoch: int
    kind: NStructureKind
    established_at: datetime | None
    trailing_defense: NSwingPivot | None
    completed_n_count_in_epoch: int

    def __post_init__(self) -> None:
        if (
            not _is_aware_datetime(self.observed_at)
            or type(self.epoch) is not int
            or self.epoch < 0
            or not isinstance(self.kind, NStructureKind)
            or (
                self.established_at is not None
                and not _is_aware_datetime(self.established_at)
            )
            or (
                self.trailing_defense is not None
                and not isinstance(self.trailing_defense, NSwingPivot)
            )
            or type(self.completed_n_count_in_epoch) is not int
            or self.completed_n_count_in_epoch < 0
            or (
                self.kind in (NStructureKind.BULL, NStructureKind.BEAR)
                and (
                    self.established_at is None
                    or self.trailing_defense is None
                )
            )
            or (
                self.kind in (NStructureKind.UNDEFINED, NStructureKind.RANGE)
                and self.trailing_defense is not None
            )
            or (
                self.kind is NStructureKind.UNDEFINED
                and self.established_at is not None
            )
        ):
            raise NStructureContractError()
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if self.established_at is not None:
            object.__setattr__(
                self,
                "established_at",
                self.established_at.astimezone(UTC),
            )


@dataclass(frozen=True, slots=True)
class NStructureTransition:
    transition_id: str
    transition_at: datetime
    from_kind: NStructureKind
    to_kind: NStructureKind
    reason_code: str
    trailing_defense_pivot_id: str | None

    def __post_init__(self) -> None:
        if (
            not _is_aware_datetime(self.transition_at)
            or not isinstance(self.from_kind, NStructureKind)
            or not isinstance(self.to_kind, NStructureKind)
            or self.reason_code not in _REASON_CODES
            or (
                self.trailing_defense_pivot_id is not None
                and not isinstance(self.trailing_defense_pivot_id, str)
            )
        ):
            raise NStructureContractError()
        transition_at = self.transition_at.astimezone(UTC)
        if self.transition_id != _canonical_transition_id(
            transition_at=transition_at,
            from_kind=self.from_kind,
            to_kind=self.to_kind,
            reason_code=self.reason_code,
            trailing_defense_pivot_id=self.trailing_defense_pivot_id,
        ):
            raise NStructureContractError()
        object.__setattr__(self, "transition_at", transition_at)


@dataclass(frozen=True, slots=True)
class NStructureTrace:
    snapshots: tuple[NStructureSnapshot, ...]
    transitions: tuple[NStructureTransition, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.snapshots, tuple)
            or any(
                not isinstance(snapshot, NStructureSnapshot)
                for snapshot in self.snapshots
            )
            or not isinstance(self.transitions, tuple)
            or any(
                not isinstance(transition, NStructureTransition)
                for transition in self.transitions
            )
        ):
            raise NStructureContractError()


def evaluate_n_market_structure(
    bars: Sequence[CanonicalBar],
    *,
    swings: NSwingTrace,
    patterns: NPatternTrace,
    policy: NStructurePolicy,
) -> NStructureTrace:
    """Evaluate immutable structure facts for one completed M5 segment."""

    _validate_inputs(bars, swings=swings, patterns=patterns, policy=policy)
    pivots_by_confirmation: dict[datetime, list[NSwingPivot]] = {}
    for pivot in swings.pivots:
        pivots_by_confirmation.setdefault(pivot.confirmed_at, []).append(pivot)
    patterns_by_completion: dict[datetime, list[CompletedNPattern]] = {}
    for pattern in patterns.patterns:
        patterns_by_completion.setdefault(pattern.completed_at, []).append(pattern)

    outside_resets = set(swings.ambiguous_outside_reset_at)
    snapshots: list[NStructureSnapshot] = []
    transitions: list[NStructureTransition] = []
    current_epoch = 0
    epoch_pivots: list[NSwingPivot] = []
    completed_n_count = 0
    kind = NStructureKind.UNDEFINED
    established_at: datetime | None = None
    defense: NSwingPivot | None = None
    qualified_high_id: str | None = None
    qualified_low_id: str | None = None

    for current in bars:
        broken_this_boundary = False

        # Existing defense is a path-independent price fact and is checked
        # before an outside reset or any new boundary evidence.
        if kind is NStructureKind.BULL:
            assert defense is not None
            if current.low < defense.price:
                _append_transition(
                    transitions,
                    transition_at=current.bar_end,
                    from_kind=kind,
                    to_kind=NStructureKind.RANGE,
                    reason_code="BULL_STRUCTURE_BROKEN",
                    defense=defense,
                )
                kind = NStructureKind.RANGE
                established_at = current.bar_end
                defense = None
                qualified_high_id = None
                qualified_low_id = None
                broken_this_boundary = True
        elif kind is NStructureKind.BEAR:
            assert defense is not None
            if current.high > defense.price:
                _append_transition(
                    transitions,
                    transition_at=current.bar_end,
                    from_kind=kind,
                    to_kind=NStructureKind.RANGE,
                    reason_code="BEAR_STRUCTURE_BROKEN",
                    defense=defense,
                )
                kind = NStructureKind.RANGE
                established_at = current.bar_end
                defense = None
                qualified_high_id = None
                qualified_low_id = None
                broken_this_boundary = True

        if current.bar_end in outside_resets:
            current_epoch += 1
            epoch_pivots.clear()
            completed_n_count = 0
            qualified_high_id = None
            qualified_low_id = None
        else:
            epoch_pivots.extend(pivots_by_confirmation.get(current.bar_end, ()))
            completed_here = patterns_by_completion.get(current.bar_end, ())
            completed_n_count += len(completed_here)

            if not broken_this_boundary:
                classification = _classify(
                    epoch_pivots,
                    completed_n_count=completed_n_count,
                )
                if kind in (NStructureKind.UNDEFINED, NStructureKind.RANGE):
                    if classification in (NStructureKind.BULL, NStructureKind.BEAR):
                        previous_kind = kind
                        latest_high, latest_low = _latest_high_low(epoch_pivots)
                        defense = (
                            latest_low
                            if classification is NStructureKind.BULL
                            else latest_high
                        )
                        kind = classification
                        established_at = current.bar_end
                        qualified_high_id = latest_high.pivot_id
                        qualified_low_id = latest_low.pivot_id
                        _append_transition(
                            transitions,
                            transition_at=current.bar_end,
                            from_kind=previous_kind,
                            to_kind=kind,
                            reason_code=(
                                "BULL_STRUCTURE_ESTABLISHED"
                                if kind is NStructureKind.BULL
                                else "BEAR_STRUCTURE_ESTABLISHED"
                            ),
                            defense=defense,
                        )
                        if _new_defense_broken(current, kind=kind, defense=defense):
                            _append_transition(
                                transitions,
                                transition_at=current.bar_end,
                                from_kind=kind,
                                to_kind=NStructureKind.RANGE,
                                reason_code=(
                                    "BULL_STRUCTURE_BROKEN"
                                    if kind is NStructureKind.BULL
                                    else "BEAR_STRUCTURE_BROKEN"
                                ),
                                defense=defense,
                            )
                            kind = NStructureKind.RANGE
                            established_at = current.bar_end
                            defense = None
                            qualified_high_id = None
                            qualified_low_id = None
                    elif (
                        kind is NStructureKind.UNDEFINED
                        and classification is NStructureKind.RANGE
                    ):
                        _append_transition(
                            transitions,
                            transition_at=current.bar_end,
                            from_kind=NStructureKind.UNDEFINED,
                            to_kind=NStructureKind.RANGE,
                            reason_code="RANGE_STRUCTURE_ESTABLISHED",
                            defense=None,
                        )
                        kind = NStructureKind.RANGE
                        established_at = current.bar_end
                elif classification is kind:
                    latest_high, latest_low = _latest_high_low(epoch_pivots)
                    candidate_defense = (
                        latest_low if kind is NStructureKind.BULL else latest_high
                    )
                    new_pair = (
                        latest_high.pivot_id != qualified_high_id
                        and latest_low.pivot_id != qualified_low_id
                    )
                    pair_became_known_here = (
                        candidate_defense.confirmed_at == current.bar_end
                        or bool(completed_here)
                    )
                    if new_pair and pair_became_known_here:
                        defense = candidate_defense
                        qualified_high_id = latest_high.pivot_id
                        qualified_low_id = latest_low.pivot_id
                        _append_transition(
                            transitions,
                            transition_at=current.bar_end,
                            from_kind=kind,
                            to_kind=kind,
                            reason_code=(
                                "BULL_TRAILING_DEFENSE_ADVANCED"
                                if kind is NStructureKind.BULL
                                else "BEAR_TRAILING_DEFENSE_ADVANCED"
                            ),
                            defense=defense,
                        )
                        if _new_defense_broken(current, kind=kind, defense=defense):
                            _append_transition(
                                transitions,
                                transition_at=current.bar_end,
                                from_kind=kind,
                                to_kind=NStructureKind.RANGE,
                                reason_code=(
                                    "BULL_STRUCTURE_BROKEN"
                                    if kind is NStructureKind.BULL
                                    else "BEAR_STRUCTURE_BROKEN"
                                ),
                                defense=defense,
                            )
                            kind = NStructureKind.RANGE
                            established_at = current.bar_end
                            defense = None
                            qualified_high_id = None
                            qualified_low_id = None

        snapshots.append(
            NStructureSnapshot(
                observed_at=current.bar_end,
                epoch=current_epoch,
                kind=kind,
                established_at=established_at,
                trailing_defense=defense,
                completed_n_count_in_epoch=completed_n_count,
            )
        )

    return NStructureTrace(
        snapshots=tuple(snapshots),
        transitions=tuple(transitions),
    )


def _validate_inputs(
    bars: Sequence[CanonicalBar],
    *,
    swings: NSwingTrace,
    patterns: NPatternTrace,
    policy: NStructurePolicy,
) -> None:
    if (
        not isinstance(policy, NStructurePolicy)
        or type(policy.schema_version) is not int
        or policy.schema_version != 1
        or type(policy.policy_id) is not str
        or policy.policy_id != "n_structure_5m_v1"
        or type(policy.formula_version) is not str
        or policy.formula_version != "n_structure_v1"
        or type(policy.research_only) is not bool
        or policy.research_only is not True
        or policy.source_timeframe is not BarFrequency.M5
        or not _policy_contract._matches_exact(
            policy.raw,
            _policy_contract._EXPECTED_PAYLOAD,
        )
    ):
        raise NStructureContractError()
    if (
        not isinstance(swings, NSwingTrace)
        or not isinstance(patterns, NPatternTrace)
        or not isinstance(swings.pivots, tuple)
        or not isinstance(swings.ambiguous_outside_reset_at, tuple)
        or type(swings.final_epoch) is not int
        or not isinstance(swings.final_leg, NSwingLeg)
        or not isinstance(patterns.patterns, tuple)
        or not isinstance(patterns.break_events, tuple)
        or not isinstance(patterns.range_band_reentries, tuple)
        or any(not isinstance(bar, CanonicalBar) for bar in bars)
        or any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:])
        )
        or type(patterns.incomplete_attempt_replaced_count) is not int
        or patterns.incomplete_attempt_replaced_count < 0
    ):
        raise NStructureSeriesError()

    bar_ends = {bar.bar_end for bar in bars}
    resets = swings.ambiguous_outside_reset_at
    actual_resets = tuple(
        current.bar_end
        for previous, current in zip(bars, bars[1:])
        if current.high > previous.high and current.low < previous.low
    )
    if (
        any(not _is_aware_datetime(reset_at) for reset_at in resets)
        or tuple(sorted(set(resets))) != resets
        or resets != actual_resets
        or swings.final_epoch != len(resets)
    ):
        raise NStructureSeriesError()

    pivots_by_id: dict[str, NSwingPivot] = {}
    previous_confirmation: datetime | None = None
    previous_epoch_kind: tuple[int, NSwingPivotKind] | None = None
    for pivot in swings.pivots:
        current_epoch_kind = (pivot.epoch, pivot.kind)
        if (
            not isinstance(pivot, NSwingPivot)
            or pivot.pivot_id in pivots_by_id
            or pivot.contract != swings.contract
            or pivot.segment_start_trading_day != swings.segment_start_trading_day
            or pivot.source_timeframe is not BarFrequency.M5
            or pivot.pivot_time not in bar_ends
            or pivot.confirmed_at not in bar_ends
            or pivot.confirmed_at in resets
            or (
                previous_confirmation is not None
                and pivot.confirmed_at <= previous_confirmation
            )
            or pivot.epoch != sum(reset_at <= pivot.confirmed_at for reset_at in resets)
            or pivot.epoch != sum(reset_at <= pivot.pivot_time for reset_at in resets)
            or (
                previous_epoch_kind is not None
                and previous_epoch_kind[0] == pivot.epoch
                and previous_epoch_kind[1] is pivot.kind
            )
        ):
            raise NStructureSeriesError()
        pivots_by_id[pivot.pivot_id] = pivot
        previous_confirmation = pivot.confirmed_at
        previous_epoch_kind = current_epoch_kind

    pattern_ids: set[str] = set()
    previous_completion: datetime | None = None
    for pattern in patterns.patterns:
        if (
            not isinstance(pattern, CompletedNPattern)
            or pattern.n_id in pattern_ids
            or pattern.completed_at not in bar_ends
            or pattern.completed_at in resets
            or (
                previous_completion is not None
                and pattern.completed_at <= previous_completion
            )
            or any(
                pivots_by_id.get(pivot.pivot_id) != pivot
                for pivot in (
                    pattern.origin,
                    pattern.n1_extreme,
                    pattern.n2_origin,
                )
            )
            or not _valid_pattern_shape(pattern)
            or pattern.origin.epoch
            != sum(reset_at <= pattern.completed_at for reset_at in resets)
        ):
            raise NStructureSeriesError()
        pattern_ids.add(pattern.n_id)
        previous_completion = pattern.completed_at

    if any(
        not isinstance(event, NBreakEvent)
        or event.n_id not in pattern_ids
        or event.observed_at not in bar_ends
        for event in patterns.break_events
    ) or any(
        not isinstance(event, NRangeBandReentryEvent)
        or event.n_id not in pattern_ids
        or event.observed_at not in bar_ends
        for event in patterns.range_band_reentries
    ):
        raise NStructureSeriesError()


def _valid_pattern_shape(pattern: CompletedNPattern) -> bool:
    origin = pattern.origin
    n1_extreme = pattern.n1_extreme
    n2_origin = pattern.n2_origin
    if not (origin.epoch == n1_extreme.epoch == n2_origin.epoch):
        return False
    if not (
        origin.confirmed_at < n1_extreme.confirmed_at < n2_origin.confirmed_at
        <= pattern.completed_at
    ):
        return False
    if pattern.direction is NDirection.UP:
        return (
            origin.kind is NSwingPivotKind.LOW
            and n1_extreme.kind is NSwingPivotKind.HIGH
            and n2_origin.kind is NSwingPivotKind.LOW
            and n2_origin.price >= origin.price
        )
    return (
        pattern.direction is NDirection.DOWN
        and origin.kind is NSwingPivotKind.HIGH
        and n1_extreme.kind is NSwingPivotKind.LOW
        and n2_origin.kind is NSwingPivotKind.HIGH
        and n2_origin.price <= origin.price
    )


def _classify(
    pivots: Sequence[NSwingPivot],
    *,
    completed_n_count: int,
) -> NStructureKind | None:
    highs = [pivot for pivot in pivots if pivot.kind is NSwingPivotKind.HIGH]
    lows = [pivot for pivot in pivots if pivot.kind is NSwingPivotKind.LOW]
    if completed_n_count < 2 or len(highs) < 2 or len(lows) < 2:
        return None
    previous_high, current_high = highs[-2:]
    previous_low, current_low = lows[-2:]
    if current_high.price > previous_high.price and current_low.price > previous_low.price:
        return NStructureKind.BULL
    if current_high.price < previous_high.price and current_low.price < previous_low.price:
        return NStructureKind.BEAR
    return NStructureKind.RANGE


def _latest_high_low(
    pivots: Sequence[NSwingPivot],
) -> tuple[NSwingPivot, NSwingPivot]:
    highs = [pivot for pivot in pivots if pivot.kind is NSwingPivotKind.HIGH]
    lows = [pivot for pivot in pivots if pivot.kind is NSwingPivotKind.LOW]
    return highs[-1], lows[-1]


def _new_defense_broken(
    current: CanonicalBar,
    *,
    kind: NStructureKind,
    defense: NSwingPivot,
) -> bool:
    if kind is NStructureKind.BULL:
        return current.low < defense.price
    return current.high > defense.price


def _append_transition(
    transitions: list[NStructureTransition],
    *,
    transition_at: datetime,
    from_kind: NStructureKind,
    to_kind: NStructureKind,
    reason_code: str,
    defense: NSwingPivot | None,
) -> None:
    defense_id = defense.pivot_id if defense is not None else None
    transitions.append(
        NStructureTransition(
            transition_id=_canonical_transition_id(
                transition_at=transition_at,
                from_kind=from_kind,
                to_kind=to_kind,
                reason_code=reason_code,
                trailing_defense_pivot_id=defense_id,
            ),
            transition_at=transition_at,
            from_kind=from_kind,
            to_kind=to_kind,
            reason_code=reason_code,
            trailing_defense_pivot_id=defense_id,
        )
    )


def _canonical_transition_id(
    *,
    transition_at: datetime,
    from_kind: NStructureKind,
    to_kind: NStructureKind,
    reason_code: str,
    trailing_defense_pivot_id: str | None,
) -> str:
    return "|".join(
        (
            "structure",
            transition_at.astimezone(UTC).isoformat(),
            from_kind.value,
            to_kind.value,
            reason_code,
            trailing_defense_pivot_id or "none",
        )
    )


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
