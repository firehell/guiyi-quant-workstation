"""Immutable, pure Newow product facts. No formula, pairing or account execution."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from .models import NewowDailyBar
from .product_identity import build_hint_id, build_signal_id, utc_timestamp


class ProductStrategy(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    MAIN_RISE = "main_rise"


class ProductFrequency(StrEnum):
    WEEKLY = "1w"
    DAILY = "1d"
    HOURLY = "60m"


class ActionKind(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"


class MainState(StrEnum):
    BUILD = "BUILD"
    HOLD = "HOLD"
    CLEAR = "CLEAR"
    FLAT = "FLAT"
    UNAVAILABLE = "UNAVAILABLE"


class TradeEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    WARMUP_ONLY = "WARMUP_ONLY"
    NO_ELIGIBLE_ENTRY = "NO_ELIGIBLE_ENTRY"


class FeatureRuntimeStatus(StrEnum):
    READY = "ready"
    WARMING = "warming"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    EVIDENCE_REQUIRED = "evidence_required"


class EvidenceStatus(StrEnum):
    ACTIVE_CODE_VERIFIED = "ACTIVE_CODE_VERIFIED"
    RESEARCH_EVIDENCE_ONLY = "RESEARCH_EVIDENCE_ONLY"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_PRODUCT_EMPTY_IDENTITY")


def _price(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("NEWOW_PRODUCT_INVALID_PRICE")


def _metric(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("NEWOW_PRODUCT_INVALID_METRIC")


def _day(value: date) -> None:
    if type(value) is not date:
        raise ValueError("NEWOW_PRODUCT_INVALID_TRADING_DAY")


def _strings(values: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ValueError("NEWOW_PRODUCT_INVALID_IDENTITIES")
    result = tuple(values)
    for value in result:
        _text(value)
    return result


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    product: str
    strategy: ProductStrategy
    frequency: ProductFrequency
    formula_versions: tuple[str, ...]
    series_kind: str = "actual_dominant"
    profile_id: str = ""

    def __post_init__(self) -> None:
        _text(self.product)
        if (
            self.product != self.product.lower()
            or self.series_kind != "actual_dominant"
        ):
            raise ValueError("NEWOW_PRODUCT_INVALID_IDENTITY")
        object.__setattr__(self, "strategy", ProductStrategy(self.strategy))
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        formulas = tuple(sorted(set(_strings(self.formula_versions))))
        if not formulas:
            raise ValueError("NEWOW_PRODUCT_EMPTY_FORMULAS")
        object.__setattr__(self, "formula_versions", formulas)
        expected = f"newow_product_{self.strategy}_{self.frequency}_v1"
        if self.profile_id and self.profile_id != expected:
            raise ValueError("NEWOW_PRODUCT_INVALID_PROFILE")
        object.__setattr__(self, "profile_id", expected)


@dataclass(frozen=True, slots=True)
class ProductBar:
    """Wrap validated OHLC facts; frequency here is the product input authority.

    The legacy payload retains its D1-only type tag for kernel compatibility.
    This wrapper does not aggregate, infer completion or change legacy APIs.
    """

    bar: NewowDailyBar
    frequency: ProductFrequency
    series_kind: str = "actual_dominant"

    def __post_init__(self) -> None:
        if not isinstance(self.bar, NewowDailyBar) or self.bar.completed is not True:
            raise ValueError("NEWOW_PRODUCT_INVALID_BAR")
        _day(self.bar.trading_day)
        if type(self.bar.observation_eligible) is not bool:
            raise ValueError("NEWOW_PRODUCT_INVALID_OBSERVATION_ELIGIBILITY")
        for value in (
            self.bar.product,
            self.bar.physical_contract,
            self.bar.segment_id,
            self.bar.source_identity,
        ):
            _text(value)
        if type(self.bar.volume) is not int or (
            self.bar.open_interest is not None
            and type(self.bar.open_interest) is not int
        ):
            raise ValueError("NEWOW_PRODUCT_INVALID_VOLUME_OR_OI")
        if self.series_kind != "actual_dominant":
            raise ValueError("NEWOW_PRODUCT_INVALID_SERIES")
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(
            self, "bar", replace(self.bar, bar_end=utc_timestamp(self.bar.bar_end))
        )


@dataclass(frozen=True, slots=True)
class OwnerBoundary:
    product: str
    old_contract: str
    new_contract: str
    old_segment_id: str
    new_segment_id: str
    effective_trading_day: date
    effective_at: datetime
    source_identity: str

    def __post_init__(self) -> None:
        for value in (
            self.product,
            self.old_contract,
            self.new_contract,
            self.old_segment_id,
            self.new_segment_id,
            self.source_identity,
        ):
            _text(value)
        if (
            self.product != self.product.lower()
            or self.old_contract != self.old_contract.upper()
            or self.new_contract != self.new_contract.upper()
            or self.old_segment_id == self.new_segment_id
        ):
            raise ValueError("NEWOW_PRODUCT_INVALID_OWNER_BOUNDARY")
        _day(self.effective_trading_day)
        object.__setattr__(self, "effective_at", utc_timestamp(self.effective_at))


@dataclass(frozen=True, slots=True)
class FeatureStatus:
    status: FeatureRuntimeStatus
    evidence_status: EvidenceStatus
    reason_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FeatureRuntimeStatus(self.status))
        object.__setattr__(
            self, "evidence_status", EvidenceStatus(self.evidence_status)
        )
        if self.status != FeatureRuntimeStatus.READY:
            _text(self.reason_code)


@dataclass(frozen=True, slots=True)
class StrategyAction:
    identity: ProductIdentity
    physical_contract: str
    segment_id: str
    bar_end: datetime
    trading_day: date
    kind: ActionKind
    reference_price: Decimal
    anchor_price: Decimal | None = None
    sequence: int = 0
    related_build_id: str | None = None
    source_marker_id: str | None = None
    source_related_marker_ids: tuple[str, ...] = ()
    trade_eligibility: TradeEligibility = TradeEligibility.ELIGIBLE
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProductIdentity):
            raise ValueError("NEWOW_PRODUCT_INVALID_IDENTITY")
        _day(self.trading_day)
        _price(self.reference_price)
        if self.anchor_price is not None:
            _price(self.anchor_price)
        for value in (self.related_build_id, self.source_marker_id):
            if value is not None:
                _text(value)
        object.__setattr__(self, "bar_end", utc_timestamp(self.bar_end))
        object.__setattr__(self, "kind", ActionKind(self.kind))
        object.__setattr__(
            self, "trade_eligibility", TradeEligibility(self.trade_eligibility)
        )
        object.__setattr__(
            self, "source_related_marker_ids", _strings(self.source_related_marker_ids)
        )
        object.__setattr__(
            self,
            "signal_id",
            build_signal_id(
                self.identity,
                self.physical_contract,
                self.segment_id,
                self.bar_end,
                self.kind,
                self.sequence,
            ),
        )


@dataclass(frozen=True, slots=True)
class StrategyHint:
    identity: ProductIdentity
    physical_contract: str
    segment_id: str
    bar_end: datetime
    trading_day: date
    kind: str
    known_at: datetime
    anchor_price: Decimal | None = None
    sequence: int | None = None
    source_marker_id: str | None = None
    source_related_marker_ids: tuple[str, ...] = ()
    quantity_effect: str = "none"
    retrospective: bool = False
    hint_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProductIdentity):
            raise ValueError("NEWOW_PRODUCT_INVALID_IDENTITY")
        _day(self.trading_day)
        if self.anchor_price is not None:
            _price(self.anchor_price)
        if self.source_marker_id is not None:
            _text(self.source_marker_id)
        object.__setattr__(self, "bar_end", utc_timestamp(self.bar_end))
        object.__setattr__(self, "known_at", utc_timestamp(self.known_at))
        if (
            self.quantity_effect != "none"
            or self.retrospective is not False
            or self.known_at < self.bar_end
        ):
            raise ValueError("NEWOW_PRODUCT_INVALID_HINT")
        object.__setattr__(
            self, "source_related_marker_ids", _strings(self.source_related_marker_ids)
        )
        object.__setattr__(
            self,
            "hint_id",
            build_hint_id(
                self.identity,
                self.physical_contract,
                self.segment_id,
                self.bar_end,
                self.kind,
                self.sequence,
            ),
        )


_Event = TypeVar("_Event", StrategyAction, StrategyHint)


def _unique(events: tuple[_Event, ...], expected: type[_Event]) -> tuple[_Event, ...]:
    result: dict[str, _Event] = {}
    for event in events:
        if not isinstance(event, expected):
            raise ValueError("NEWOW_PRODUCT_INVALID_EVENT_TYPE")
        key = event.signal_id if isinstance(event, StrategyAction) else event.hint_id
        if key in result and result[key] != event:
            raise ValueError("NEWOW_PRODUCT_ID_CONTENT_CONFLICT")
        result[key] = event
    return tuple(result.values())


def _ordered_actions(actions: tuple[StrategyAction, ...]) -> None:
    seen_segments: set[str] = set()
    current_segment: str | None = None
    current_contract: str | None = None
    previous: StrategyAction | None = None
    for action in actions:
        if action.segment_id != current_segment:
            if action.segment_id in seen_segments:
                raise ValueError("NEWOW_PRODUCT_ACTION_ORDER")
            if current_segment is not None:
                seen_segments.add(current_segment)
            current_segment = action.segment_id
            current_contract = action.physical_contract
            previous = None
        elif action.physical_contract != current_contract:
            raise ValueError("NEWOW_PRODUCT_ACTION_ORDER")
        if previous is not None and (
            previous.bar_end,
            previous.sequence,
        ) >= (action.bar_end, action.sequence):
            raise ValueError("NEWOW_PRODUCT_ACTION_ORDER")
        if (
            previous is not None
            and previous.bar_end == action.bar_end
            and previous.identity.strategy == ProductStrategy.OSCILLATION
            and (previous.kind, action.kind) != (ActionKind.CLEAR, ActionKind.BUILD)
        ):
            raise ValueError("NEWOW_PRODUCT_OSCILLATION_SAME_BAR_ORDER")
        previous = action


@dataclass(frozen=True, slots=True)
class StrategyFrame:
    bar: ProductBar
    main_state: MainState
    main_values: tuple[tuple[str, Decimal | None], ...]
    availability: FeatureStatus
    actions: tuple[StrategyAction, ...] = ()
    hints: tuple[StrategyHint, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.bar, ProductBar) or not isinstance(
            self.availability, FeatureStatus
        ):
            raise ValueError("NEWOW_PRODUCT_INVALID_FRAME")
        object.__setattr__(self, "main_state", MainState(self.main_state))
        values = tuple((key, value) for key, value in self.main_values)
        for key, value in values:
            _text(key)
            if value is not None:
                _metric(value)
        if len({key for key, _ in values}) != len(values):
            raise ValueError("NEWOW_PRODUCT_DUPLICATE_MAIN_VALUE")
        object.__setattr__(self, "main_values", values)
        object.__setattr__(self, "actions", _unique(self.actions, StrategyAction))
        object.__setattr__(self, "hints", _unique(self.hints, StrategyHint))
        _ordered_actions(self.actions)
        events: tuple[StrategyAction | StrategyHint, ...] = (*self.actions, *self.hints)
        for event in events:
            bar = self.bar.bar
            if (
                event.identity.product != bar.product
                or event.identity.frequency != self.bar.frequency
                or event.physical_contract != bar.physical_contract
                or event.segment_id != bar.segment_id
                or event.bar_end != bar.bar_end
                or event.trading_day != bar.trading_day
            ):
                raise ValueError("NEWOW_PRODUCT_FRAME_EVENT_MISMATCH")
            if (
                isinstance(event, StrategyAction)
                and not bar.observation_eligible
                and event.trade_eligibility == TradeEligibility.ELIGIBLE
            ):
                raise ValueError("NEWOW_PRODUCT_WARMUP_ACTION_ELIGIBLE")


@dataclass(frozen=True, slots=True)
class StrategyReplay:
    identity: ProductIdentity
    frames: tuple[StrategyFrame, ...]
    actions: tuple[StrategyAction, ...]
    hints: tuple[StrategyHint, ...]
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProductIdentity):
            raise ValueError("NEWOW_PRODUCT_INVALID_IDENTITY")
        object.__setattr__(self, "frames", tuple(self.frames))
        object.__setattr__(self, "actions", _unique(self.actions, StrategyAction))
        object.__setattr__(self, "hints", _unique(self.hints, StrategyHint))
        object.__setattr__(self, "diagnostics", _strings(self.diagnostics))
        seen_segments: set[str] = set()
        current_segment: str | None = None
        current_contract: str | None = None
        previous: datetime | None = None
        for frame in self.frames:
            if not isinstance(frame, StrategyFrame):
                raise ValueError("NEWOW_PRODUCT_INVALID_FRAME")
            bar = frame.bar.bar
            if (
                bar.product != self.identity.product
                or frame.bar.frequency != self.identity.frequency
            ):
                raise ValueError("NEWOW_PRODUCT_FRAME_ORDER_OR_IDENTITY")
            if bar.segment_id != current_segment:
                if bar.segment_id in seen_segments:
                    raise ValueError("NEWOW_PRODUCT_FRAME_ORDER_OR_IDENTITY")
                if current_segment is not None:
                    seen_segments.add(current_segment)
                current_segment = bar.segment_id
                current_contract = bar.physical_contract
                previous = None
            elif bar.physical_contract != current_contract:
                raise ValueError("NEWOW_PRODUCT_FRAME_ORDER_OR_IDENTITY")
            if previous is not None and bar.bar_end <= previous:
                raise ValueError("NEWOW_PRODUCT_FRAME_ORDER_OR_IDENTITY")
            previous = bar.bar_end
        frame_actions = tuple(
            action for frame in self.frames for action in frame.actions
        )
        frame_hints = tuple(hint for frame in self.frames for hint in frame.hints)
        _unique((*self.actions, *frame_actions), StrategyAction)
        _unique((*self.hints, *frame_hints), StrategyHint)
        events: tuple[StrategyAction | StrategyHint, ...] = (
            *self.actions,
            *self.hints,
            *frame_actions,
            *frame_hints,
        )
        for event in events:
            if event.identity != self.identity:
                raise ValueError("NEWOW_PRODUCT_REPLAY_IDENTITY_MISMATCH")
        if self.actions != frame_actions or self.hints != frame_hints:
            raise ValueError("NEWOW_PRODUCT_REPLAY_FRAME_MISMATCH")
        _ordered_actions(self.actions)

    @property
    def main_values(
        self,
    ) -> tuple[
        tuple[
            datetime,
            MainState,
            tuple[tuple[str, Decimal | None], ...],
            tuple[StrategyAction, ...],
        ],
        ...,
    ]:
        return tuple(
            (frame.bar.bar.bar_end, frame.main_state, frame.main_values, frame.actions)
            for frame in self.frames
        )
