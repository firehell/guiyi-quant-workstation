"""Causal completed-N, level-break, and N1-N2 range-band facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from heapq import heappop, heappush

from .domain import BarFrequency, CanonicalBar
from .n_structure_policy import NStructurePolicy, is_exact_n_structure_policy
from .n_structure_swing import (
    NStructureContractError,
    NStructureSeriesError,
    NSwingPivot,
    NSwingPivotKind,
    NSwingTrace,
)


class NDirection(StrEnum):
    UP = "up"
    DOWN = "down"


class NBreakKind(StrEnum):
    N2_ORIGIN_BROKEN = "n2_origin_broken"
    ORIGIN_BROKEN = "origin_broken"


class NRangeBandRole(StrEnum):
    SUPPORT_REFERENCE = "support_reference"
    RESISTANCE_REFERENCE = "resistance_reference"


@dataclass(frozen=True, slots=True)
class NRangeBand:
    lower: Decimal
    upper: Decimal
    role: NRangeBandRole

    def __post_init__(self) -> None:
        if (
            not _is_positive_finite_decimal(self.lower)
            or not _is_positive_finite_decimal(self.upper)
            or self.lower > self.upper
            or not isinstance(self.role, NRangeBandRole)
        ):
            raise NStructureContractError()


@dataclass(frozen=True, slots=True)
class CompletedNPattern:
    n_id: str
    direction: NDirection
    origin: NSwingPivot
    n1_extreme: NSwingPivot
    n2_origin: NSwingPivot
    completed_at: datetime
    completion_level: Decimal
    completion_bar_close: Decimal
    completion_overshoot_bps: Decimal
    range_band: NRangeBand

    def __post_init__(self) -> None:
        if (
            not isinstance(self.n_id, str)
            or not isinstance(self.direction, NDirection)
            or not isinstance(self.origin, NSwingPivot)
            or not isinstance(self.n1_extreme, NSwingPivot)
            or not isinstance(self.n2_origin, NSwingPivot)
            or not _is_aware_datetime(self.completed_at)
            or not _is_positive_finite_decimal(self.completion_level)
            or not _is_positive_finite_decimal(self.completion_bar_close)
            or not _is_nonnegative_finite_decimal(
                self.completion_overshoot_bps
            )
            or not isinstance(self.range_band, NRangeBand)
        ):
            raise NStructureContractError()
        expected_id = _canonical_n_id(
            self.direction,
            self.origin,
            self.n1_extreme,
            self.n2_origin,
        )
        if (
            self.n_id != expected_id
            or self.completed_at.astimezone(UTC) < self.n2_origin.confirmed_at
            or self.completion_level != self.n1_extreme.price
        ):
            raise NStructureContractError()
        object.__setattr__(self, "completed_at", self.completed_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class NBreakEvent:
    event_id: str
    n_id: str
    kind: NBreakKind
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_id, str)
            or not isinstance(self.n_id, str)
            or not isinstance(self.kind, NBreakKind)
            or not _is_aware_datetime(self.observed_at)
        ):
            raise NStructureContractError()
        expected_id = _canonical_event_id(
            n_id=self.n_id,
            fact="break",
            detail=self.kind.value,
            observed_at=self.observed_at,
        )
        if self.event_id != expected_id:
            raise NStructureContractError()
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class NRangeBandReentryEvent:
    event_id: str
    n_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_id, str)
            or not isinstance(self.n_id, str)
            or not _is_aware_datetime(self.observed_at)
        ):
            raise NStructureContractError()
        expected_id = _canonical_event_id(
            n_id=self.n_id,
            fact="range_band_reentry",
            detail="first",
            observed_at=self.observed_at,
        )
        if self.event_id != expected_id:
            raise NStructureContractError()
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class NPatternTrace:
    patterns: tuple[CompletedNPattern, ...]
    break_events: tuple[NBreakEvent, ...]
    range_band_reentries: tuple[NRangeBandReentryEvent, ...]
    incomplete_attempt_replaced_count: int


@dataclass(frozen=True, slots=True)
class _IncompleteN:
    direction: NDirection
    origin: NSwingPivot
    n1_extreme: NSwingPivot
    n2_origin: NSwingPivot

    @property
    def identity(self) -> tuple[str, str, str, NDirection]:
        return (
            self.origin.pivot_id,
            self.n1_extreme.pivot_id,
            self.n2_origin.pivot_id,
            self.direction,
        )


@dataclass(slots=True)
class _ActiveAssessment:
    pattern: CompletedNPattern
    emitted_breaks: set[NBreakKind]
    sequence: int
    range_band_reentry_emitted: bool = False

    @property
    def fully_assessed(self) -> bool:
        return self.range_band_reentry_emitted and self.emitted_breaks == {
            NBreakKind.N2_ORIGIN_BROKEN,
            NBreakKind.ORIGIN_BROKEN,
        }


_PendingLevel = tuple[Decimal, int, int, str]


class _PendingAssessmentIndex:
    """Index one-shot pending facts by their strict/non-strict price levels."""

    def __init__(self) -> None:
        self._active: dict[str, _ActiveAssessment] = {}
        self._up_breaks: list[_PendingLevel] = []
        self._down_breaks: list[_PendingLevel] = []
        self._up_reentries: list[_PendingLevel] = []
        self._down_reentries: list[_PendingLevel] = []
        self._next_sequence = 0

    def add(self, pattern: CompletedNPattern) -> _ActiveAssessment:
        assessment = _ActiveAssessment(
            pattern=pattern,
            emitted_breaks=set(),
            sequence=self._next_sequence,
        )
        self._next_sequence += 1
        self._active[pattern.n_id] = assessment
        break_levels = (
            (pattern.n2_origin.price, 0),
            (pattern.origin.price, 1),
        )
        target = (
            self._up_breaks
            if pattern.direction is NDirection.UP
            else self._down_breaks
        )
        for level, priority in break_levels:
            heappush(
                target,
                (
                    -level if pattern.direction is NDirection.UP else level,
                    assessment.sequence,
                    priority,
                    pattern.n_id,
                ),
            )
        return assessment

    def activate_reentry(self, assessment: _ActiveAssessment) -> None:
        if assessment.pattern.n_id not in self._active:
            return
        pattern = assessment.pattern
        if pattern.direction is NDirection.UP:
            heappush(
                self._up_reentries,
                (
                    -pattern.range_band.upper,
                    assessment.sequence,
                    0,
                    pattern.n_id,
                ),
            )
        else:
            heappush(
                self._down_reentries,
                (
                    pattern.range_band.lower,
                    assessment.sequence,
                    0,
                    pattern.n_id,
                ),
            )

    def triggered_breaks(
        self,
        current: CanonicalBar,
    ) -> tuple[_ActiveAssessment, ...]:
        selected: dict[str, _ActiveAssessment] = {}
        while self._up_breaks and -self._up_breaks[0][0] > current.low:
            self._select(heappop(self._up_breaks)[3], selected)
        while self._down_breaks and self._down_breaks[0][0] < current.high:
            self._select(heappop(self._down_breaks)[3], selected)
        return tuple(sorted(selected.values(), key=lambda item: item.sequence))

    def triggered_reentries(
        self,
        current: CanonicalBar,
    ) -> tuple[_ActiveAssessment, ...]:
        selected: dict[str, _ActiveAssessment] = {}
        while (
            self._up_reentries
            and -self._up_reentries[0][0] >= current.low
        ):
            self._select(heappop(self._up_reentries)[3], selected)
        while (
            self._down_reentries
            and self._down_reentries[0][0] <= current.high
        ):
            self._select(heappop(self._down_reentries)[3], selected)
        return tuple(sorted(selected.values(), key=lambda item: item.sequence))

    def retire_fully_assessed(
        self,
        assessments: Sequence[_ActiveAssessment],
    ) -> None:
        for assessment in assessments:
            if assessment.fully_assessed:
                self._active.pop(assessment.pattern.n_id, None)

    def _select(
        self,
        n_id: str,
        selected: dict[str, _ActiveAssessment],
    ) -> None:
        assessment = self._active.get(n_id)
        if assessment is not None:
            selected[n_id] = assessment


def evaluate_n_patterns(
    bars: Sequence[CanonicalBar],
    swings: NSwingTrace,
    *,
    policy: NStructurePolicy,
) -> NPatternTrace:
    """Evaluate one explicit completed-5m rank-1 segment without lookahead."""

    _validate_inputs(bars, swings=swings, policy=policy)
    pivots_by_confirmation: dict[datetime, NSwingPivot] = {
        pivot.confirmed_at: pivot for pivot in swings.pivots
    }
    outside_resets = set(swings.ambiguous_outside_reset_at)

    patterns: list[CompletedNPattern] = []
    break_events: list[NBreakEvent] = []
    reentry_events: list[NRangeBandReentryEvent] = []
    pending_assessments = _PendingAssessmentIndex()
    recent_pivots: list[NSwingPivot] = []
    incomplete: _IncompleteN | None = None
    replaced_count = 0

    for current in bars:
        new_assessment: _ActiveAssessment | None = None
        # Existing immutable levels are path-independent even on an outside bar.
        triggered_breaks = pending_assessments.triggered_breaks(current)
        _record_breaks(
            current,
            triggered_breaks,
            break_events,
        )

        is_outside_reset = current.bar_end in outside_resets
        if is_outside_reset:
            incomplete = None
            recent_pivots.clear()
        else:
            confirmed_pivot = pivots_by_confirmation.get(current.bar_end)
            if confirmed_pivot is not None:
                recent_pivots.append(confirmed_pivot)
                if len(recent_pivots) > 3:
                    del recent_pivots[0]
                candidate = _legal_base(recent_pivots)
                if candidate is not None and (
                    incomplete is None
                    or candidate.identity != incomplete.identity
                ):
                    if incomplete is not None:
                        replaced_count += 1
                    incomplete = candidate

            if incomplete is not None and _completion_breached(
                current,
                incomplete,
            ):
                pattern = _complete_pattern(current, incomplete)
                patterns.append(pattern)
                new_assessment = pending_assessments.add(pattern)
                incomplete = None
                # A new N's own levels are also facts known at this boundary.
                _record_breaks(current, (new_assessment,), break_events)

        # The completion boundary itself never counts as first re-entry.
        triggered_reentries = pending_assessments.triggered_reentries(current)
        _record_range_band_reentries(
            current,
            triggered_reentries,
            reentry_events,
        )
        touched = triggered_breaks + triggered_reentries
        if new_assessment is not None:
            pending_assessments.activate_reentry(new_assessment)
            touched += (new_assessment,)
        pending_assessments.retire_fully_assessed(touched)

    return NPatternTrace(
        patterns=tuple(patterns),
        break_events=tuple(break_events),
        range_band_reentries=tuple(reentry_events),
        incomplete_attempt_replaced_count=replaced_count,
    )


def _validate_inputs(
    bars: Sequence[CanonicalBar],
    *,
    swings: NSwingTrace,
    policy: NStructurePolicy,
) -> None:
    if not is_exact_n_structure_policy(policy):
        raise NStructureContractError()
    if (
        not isinstance(swings, NSwingTrace)
        or any(not isinstance(bar, CanonicalBar) for bar in bars)
        or any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:])
        )
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
        or any(reset_at not in bar_ends for reset_at in resets)
        or swings.final_epoch != len(resets)
    ):
        raise NStructureSeriesError()

    previous_confirmation: datetime | None = None
    for pivot in swings.pivots:
        if (
            not isinstance(pivot, NSwingPivot)
            or pivot.contract != swings.contract
            or pivot.segment_start_trading_day
            != swings.segment_start_trading_day
            or pivot.source_timeframe is not BarFrequency.M5
            or pivot.pivot_time not in bar_ends
            or pivot.confirmed_at not in bar_ends
            or pivot.confirmed_at in resets
            or (
                previous_confirmation is not None
                and pivot.confirmed_at <= previous_confirmation
            )
            or pivot.epoch
            != sum(reset_at <= pivot.confirmed_at for reset_at in resets)
        ):
            raise NStructureSeriesError()
        previous_confirmation = pivot.confirmed_at


def _legal_base(pivots: Sequence[NSwingPivot]) -> _IncompleteN | None:
    if len(pivots) != 3:
        return None
    origin, n1_extreme, n2_origin = pivots
    if not (origin.epoch == n1_extreme.epoch == n2_origin.epoch):
        return None
    kinds = (origin.kind, n1_extreme.kind, n2_origin.kind)
    if kinds == (
        NSwingPivotKind.LOW,
        NSwingPivotKind.HIGH,
        NSwingPivotKind.LOW,
    ) and n2_origin.price >= origin.price:
        return _IncompleteN(
            direction=NDirection.UP,
            origin=origin,
            n1_extreme=n1_extreme,
            n2_origin=n2_origin,
        )
    if kinds == (
        NSwingPivotKind.HIGH,
        NSwingPivotKind.LOW,
        NSwingPivotKind.HIGH,
    ) and n2_origin.price <= origin.price:
        return _IncompleteN(
            direction=NDirection.DOWN,
            origin=origin,
            n1_extreme=n1_extreme,
            n2_origin=n2_origin,
        )
    return None


def _completion_breached(current: CanonicalBar, attempt: _IncompleteN) -> bool:
    if attempt.direction is NDirection.UP:
        return current.high > attempt.n1_extreme.price
    return current.low < attempt.n1_extreme.price


def _complete_pattern(
    current: CanonicalBar,
    attempt: _IncompleteN,
) -> CompletedNPattern:
    n1_price = attempt.n1_extreme.price
    if attempt.direction is NDirection.UP:
        overshoot = (current.high - n1_price) / n1_price * Decimal(10000)
        role = NRangeBandRole.SUPPORT_REFERENCE
    else:
        overshoot = (n1_price - current.low) / n1_price * Decimal(10000)
        role = NRangeBandRole.RESISTANCE_REFERENCE
    band = NRangeBand(
        lower=min(n1_price, attempt.n2_origin.price),
        upper=max(n1_price, attempt.n2_origin.price),
        role=role,
    )
    return CompletedNPattern(
        n_id=_canonical_n_id(
            attempt.direction,
            attempt.origin,
            attempt.n1_extreme,
            attempt.n2_origin,
        ),
        direction=attempt.direction,
        origin=attempt.origin,
        n1_extreme=attempt.n1_extreme,
        n2_origin=attempt.n2_origin,
        completed_at=current.bar_end,
        completion_level=n1_price,
        completion_bar_close=current.close,
        completion_overshoot_bps=overshoot,
        range_band=band,
    )


def _record_breaks(
    current: CanonicalBar,
    assessments: Sequence[_ActiveAssessment],
    events: list[NBreakEvent],
) -> None:
    for assessment in assessments:
        pattern = assessment.pattern
        if pattern.direction is NDirection.UP:
            n2_broken = current.low < pattern.n2_origin.price
            origin_broken = current.low < pattern.origin.price
        else:
            n2_broken = current.high > pattern.n2_origin.price
            origin_broken = current.high > pattern.origin.price
        for kind, breached in (
            (NBreakKind.N2_ORIGIN_BROKEN, n2_broken),
            (NBreakKind.ORIGIN_BROKEN, origin_broken),
        ):
            if breached and kind not in assessment.emitted_breaks:
                assessment.emitted_breaks.add(kind)
                events.append(
                    NBreakEvent(
                        event_id=_canonical_event_id(
                            n_id=pattern.n_id,
                            fact="break",
                            detail=kind.value,
                            observed_at=current.bar_end,
                        ),
                        n_id=pattern.n_id,
                        kind=kind,
                        observed_at=current.bar_end,
                    )
                )


def _record_range_band_reentries(
    current: CanonicalBar,
    assessments: Sequence[_ActiveAssessment],
    events: list[NRangeBandReentryEvent],
) -> None:
    for assessment in assessments:
        pattern = assessment.pattern
        if (
            assessment.range_band_reentry_emitted
            or current.bar_end <= pattern.completed_at
        ):
            continue
        if pattern.direction is NDirection.UP:
            reentered = current.low <= pattern.range_band.upper
        else:
            reentered = current.high >= pattern.range_band.lower
        if reentered:
            assessment.range_band_reentry_emitted = True
            events.append(
                NRangeBandReentryEvent(
                    event_id=_canonical_event_id(
                        n_id=pattern.n_id,
                        fact="range_band_reentry",
                        detail="first",
                        observed_at=current.bar_end,
                    ),
                    n_id=pattern.n_id,
                    observed_at=current.bar_end,
                )
            )


def _canonical_n_id(
    direction: NDirection,
    origin: NSwingPivot,
    n1_extreme: NSwingPivot,
    n2_origin: NSwingPivot,
) -> str:
    return "|".join(
        (
            "n",
            direction.value,
            origin.pivot_id,
            n1_extreme.pivot_id,
            n2_origin.pivot_id,
        )
    )


def _canonical_event_id(
    *,
    n_id: str,
    fact: str,
    detail: str,
    observed_at: datetime,
) -> str:
    return "|".join(
        (
            n_id,
            fact,
            detail,
            observed_at.astimezone(UTC).isoformat(),
        )
    )


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _is_positive_finite_decimal(value: object) -> bool:
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and value > 0
    )


def _is_nonnegative_finite_decimal(value: object) -> bool:
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and value >= 0
    )
