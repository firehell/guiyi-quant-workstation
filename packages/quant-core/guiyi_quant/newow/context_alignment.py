"""Current-Canonical, completed-only multi-period context alignment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime

from .product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductFrequency,
    ProductIdentity,
    StrategyAction,
    StrategyFrame,
    StrategyHint,
    StrategyReplay,
)
from .product_identity import utc_timestamp


CURRENT_CANONICAL_CUTOFF_RECOMPUTE = "current_canonical_cutoff_recompute"
_ACTIVE = EvidenceStatus.ACTIVE_CODE_VERIFIED
_FREQUENCIES = (
    ProductFrequency.WEEKLY,
    ProductFrequency.DAILY,
    ProductFrequency.HOURLY,
)


def _ready() -> FeatureStatus:
    return FeatureStatus(FeatureRuntimeStatus.READY, _ACTIVE)


def _unavailable(reason_code: str) -> FeatureStatus:
    return FeatureStatus(FeatureRuntimeStatus.UNAVAILABLE, _ACTIVE, reason_code)


@dataclass(frozen=True, slots=True)
class ContextSlot:
    """One independently cut off frequency; never borrows another owner."""

    frequency: ProductFrequency
    as_of: datetime
    availability: FeatureStatus
    confirmation_status: FeatureStatus
    identity: ProductIdentity | None = None
    frame: StrategyFrame | None = None
    bar_end: datetime | None = None
    source_identity: str | None = None
    physical_contract: str | None = None
    segment_id: str | None = None
    formula_versions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            frequency = ProductFrequency(self.frequency)
            as_of = utc_timestamp(self.as_of)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_CONTEXT_INVALID_SLOT") from error
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "as_of", as_of)
        if not isinstance(self.availability, FeatureStatus) or not isinstance(
            self.confirmation_status, FeatureStatus
        ):
            raise ValueError("NEWOW_CONTEXT_INVALID_SLOT")

        formulas = tuple(self.formula_versions)
        object.__setattr__(self, "formula_versions", formulas)
        if self.frame is None:
            if any(
                value is not None
                for value in (
                    self.bar_end,
                    self.source_identity,
                    self.physical_contract,
                    self.segment_id,
                )
            ):
                raise ValueError("NEWOW_CONTEXT_INVALID_SLOT")
            if self.identity is None and formulas:
                raise ValueError("NEWOW_CONTEXT_INVALID_SLOT")
            if self.identity is not None and (
                self.identity.frequency is not frequency
                or formulas != self.identity.formula_versions
            ):
                raise ValueError("NEWOW_CONTEXT_INVALID_SLOT")
            return

        if not isinstance(self.identity, ProductIdentity) or not isinstance(
            self.frame, StrategyFrame
        ):
            raise ValueError("NEWOW_CONTEXT_INVALID_SLOT")
        bar = self.frame.bar.bar
        if (
            self.identity.frequency is not frequency
            or self.frame.bar.frequency is not frequency
            or bar.product != self.identity.product
            or bar.series_kind != self.identity.series_kind
            or self.bar_end != bar.bar_end
            or self.source_identity != bar.source_identity
            or self.physical_contract != bar.physical_contract
            or self.segment_id != bar.segment_id
            or formulas != self.identity.formula_versions
            or self.availability != self.frame.availability
            or bar.bar_end > as_of
            or bar.observation_eligible is not True
        ):
            raise ValueError("NEWOW_CONTEXT_INVALID_SLOT")

    @property
    def status(self) -> FeatureRuntimeStatus:
        return self.availability.status

    @property
    def reason_code(self) -> str | None:
        return self.availability.reason_code


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Three-frequency snapshot rebuilt from today's Canonical contents."""

    as_of: datetime
    weekly: ContextSlot
    daily: ContextSlot
    hourly: ContextSlot
    missing_frequencies: tuple[ProductFrequency, ...]
    recompute_mode: str = CURRENT_CANONICAL_CUTOFF_RECOMPUTE
    historical_database_knowledge_reconstructed: bool = False

    def __post_init__(self) -> None:
        try:
            as_of = utc_timestamp(self.as_of)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_CONTEXT_INVALID_SNAPSHOT") from error
        object.__setattr__(self, "as_of", as_of)
        slots = (self.weekly, self.daily, self.hourly)
        if (
            not all(isinstance(slot, ContextSlot) for slot in slots)
            or tuple(slot.frequency for slot in slots) != _FREQUENCIES
            or any(slot.as_of != as_of for slot in slots)
            or self.recompute_mode != CURRENT_CANONICAL_CUTOFF_RECOMPUTE
            or self.historical_database_knowledge_reconstructed is not False
        ):
            raise ValueError("NEWOW_CONTEXT_INVALID_SNAPSHOT")
        missing = tuple(ProductFrequency(value) for value in self.missing_frequencies)
        if len(set(missing)) != len(missing) or any(
            frequency not in _FREQUENCIES for frequency in missing
        ):
            raise ValueError("NEWOW_CONTEXT_INVALID_SNAPSHOT")
        object.__setattr__(self, "missing_frequencies", missing)

    @property
    def slots(self) -> tuple[ContextSlot, ContextSlot, ContextSlot]:
        return self.weekly, self.daily, self.hourly

    @property
    def metadata(self) -> tuple[tuple[str, str | bool], ...]:
        return (
            ("recompute_mode", self.recompute_mode),
            (
                "historical_database_knowledge_reconstructed",
                self.historical_database_knowledge_reconstructed,
            ),
        )


def _normalize_inputs(
    frames_by_frequency: Mapping[ProductFrequency | str, StrategyReplay],
) -> dict[ProductFrequency, StrategyReplay]:
    if not isinstance(frames_by_frequency, Mapping):
        raise ValueError("NEWOW_CONTEXT_INVALID_INPUT")
    normalized: dict[ProductFrequency, StrategyReplay] = {}
    for raw_frequency, replay in frames_by_frequency.items():
        try:
            frequency = ProductFrequency(raw_frequency)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_CONTEXT_INVALID_FREQUENCY") from error
        if frequency in normalized:
            raise ValueError("NEWOW_CONTEXT_DUPLICATE_FREQUENCY")
        if not isinstance(replay, StrategyReplay):
            raise ValueError("NEWOW_CONTEXT_INVALID_REPLAY")
        normalized[frequency] = replay
    return normalized


def _validate_replay(
    frequency: ProductFrequency,
    replay: StrategyReplay,
) -> tuple[StrategyFrame, ...]:
    if not isinstance(replay.identity, ProductIdentity):
        raise ValueError("NEWOW_CONTEXT_IDENTITY_MISMATCH")
    if replay.identity.frequency is not frequency:
        raise ValueError("NEWOW_CONTEXT_FREQUENCY_MISMATCH")
    try:
        frames = tuple(replay.frames)
    except TypeError as error:
        raise ValueError("NEWOW_CONTEXT_INVALID_REPLAY") from error

    seen_segments: set[str] = set()
    seen_facts: dict[tuple[str, str, datetime], StrategyFrame] = {}
    current_segment: str | None = None
    current_contract: str | None = None
    previous_bar_end: datetime | None = None
    previous_trading_day: date | None = None
    frame_hints: list[StrategyHint] = []
    frame_actions: list[StrategyAction] = []
    for frame in frames:
        if not isinstance(frame, StrategyFrame):
            raise ValueError("NEWOW_CONTEXT_INVALID_REPLAY")
        product_bar = frame.bar
        bar = product_bar.bar
        try:
            bar_end = utc_timestamp(bar.bar_end)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_CONTEXT_INVALID_TIMESTAMP") from error
        if (
            product_bar.frequency is not frequency
            or bar.product != replay.identity.product
            or product_bar.series_kind != replay.identity.series_kind
            or bar.series_kind != replay.identity.series_kind
            or bar.completed is not True
            or type(bar.observation_eligible) is not bool
        ):
            raise ValueError("NEWOW_CONTEXT_IDENTITY_MISMATCH")

        fact_identity = (bar.physical_contract, bar.segment_id, bar_end)
        duplicate = seen_facts.get(fact_identity)
        if duplicate is not None:
            if duplicate == frame:
                raise ValueError("NEWOW_CONTEXT_DUPLICATE_FACT")
            raise ValueError("NEWOW_CONTEXT_CONFLICTING_FACT")
        seen_facts[fact_identity] = frame

        if bar.segment_id != current_segment:
            if bar.segment_id in seen_segments:
                raise ValueError("NEWOW_CONTEXT_INPUT_ORDER")
            if current_segment is not None:
                seen_segments.add(current_segment)
            current_segment = bar.segment_id
            current_contract = bar.physical_contract
            previous_bar_end = None
            previous_trading_day = None
        elif bar.physical_contract != current_contract:
            raise ValueError("NEWOW_CONTEXT_IDENTITY_MISMATCH")
        if (
            previous_bar_end is not None
            and previous_trading_day is not None
            and (bar_end <= previous_bar_end or bar.trading_day < previous_trading_day)
        ):
            raise ValueError("NEWOW_CONTEXT_INPUT_ORDER")
        previous_bar_end = bar_end
        previous_trading_day = bar.trading_day

        if any(action.identity != replay.identity for action in frame.actions) or any(
            hint.identity != replay.identity for hint in frame.hints
        ):
            raise ValueError("NEWOW_CONTEXT_IDENTITY_MISMATCH")
        for hint in frame.hints:
            try:
                known_at = utc_timestamp(hint.known_at)
            except (TypeError, ValueError) as error:
                raise ValueError("NEWOW_CONTEXT_INVALID_TIMESTAMP") from error
            if known_at < bar_end:
                raise ValueError("NEWOW_CONTEXT_FUTURE_KNOWLEDGE")
        frame_actions.extend(frame.actions)
        frame_hints.extend(frame.hints)

    if tuple(frame_actions) != tuple(replay.actions) or tuple(frame_hints) != tuple(
        replay.hints
    ):
        raise ValueError("NEWOW_CONTEXT_REPLAY_FRAME_MISMATCH")
    return frames


def _slot(
    frequency: ProductFrequency,
    replay: StrategyReplay | None,
    as_of: datetime,
) -> ContextSlot:
    if replay is None:
        unavailable = _unavailable("NEWOW_CONTEXT_MISSING_FREQUENCY")
        return ContextSlot(
            frequency=frequency,
            as_of=as_of,
            availability=unavailable,
            confirmation_status=unavailable,
        )

    frames = _validate_replay(frequency, replay)
    eligible = tuple(
        frame
        for frame in frames
        if frame.bar.bar.observation_eligible is True and frame.bar.bar.bar_end <= as_of
    )
    if not eligible:
        unavailable = _unavailable("NEWOW_CONTEXT_NO_ELIGIBLE_FRAME")
        return ContextSlot(
            frequency=frequency,
            as_of=as_of,
            availability=unavailable,
            confirmation_status=unavailable,
            identity=replay.identity,
            formula_versions=replay.identity.formula_versions,
        )

    selected = max(eligible, key=lambda frame: frame.bar.bar.bar_end)
    visible_hints = tuple(hint for hint in selected.hints if hint.known_at <= as_of)
    confirmation_status = (
        _ready()
        if len(visible_hints) == len(selected.hints)
        else _unavailable("NEWOW_CONTEXT_CONFIRMATION_AFTER_AS_OF")
    )
    visible_frame = (
        selected
        if visible_hints == selected.hints
        else replace(selected, hints=visible_hints)
    )
    bar = visible_frame.bar.bar
    return ContextSlot(
        frequency=frequency,
        as_of=as_of,
        availability=visible_frame.availability,
        confirmation_status=confirmation_status,
        identity=replay.identity,
        frame=visible_frame,
        bar_end=bar.bar_end,
        source_identity=bar.source_identity,
        physical_contract=bar.physical_contract,
        segment_id=bar.segment_id,
        formula_versions=replay.identity.formula_versions,
    )


def align_completed_context(
    frames_by_frequency: Mapping[ProductFrequency | str, StrategyReplay],
    as_of: datetime,
) -> ContextSnapshot:
    """Align independent completed contexts without claiming PIT reconstruction."""

    try:
        cutoff = utc_timestamp(as_of)
    except (TypeError, ValueError) as error:
        raise ValueError("NEWOW_CONTEXT_INVALID_AS_OF") from error
    inputs = _normalize_inputs(frames_by_frequency)

    common_identity: tuple[object, ...] | None = None
    for replay in inputs.values():
        identity = replay.identity
        if not isinstance(identity, ProductIdentity):
            raise ValueError("NEWOW_CONTEXT_IDENTITY_MISMATCH")
        current = (
            identity.product,
            identity.strategy,
            identity.series_kind,
            identity.formula_versions,
        )
        if common_identity is None:
            common_identity = current
        elif current != common_identity:
            raise ValueError("NEWOW_CONTEXT_IDENTITY_MISMATCH")

    missing = tuple(frequency for frequency in _FREQUENCIES if frequency not in inputs)
    slots = {
        frequency: _slot(frequency, inputs.get(frequency), cutoff)
        for frequency in _FREQUENCIES
    }
    return ContextSnapshot(
        as_of=cutoff,
        weekly=slots[ProductFrequency.WEEKLY],
        daily=slots[ProductFrequency.DAILY],
        hourly=slots[ProductFrequency.HOURLY],
        missing_frequencies=missing,
    )
