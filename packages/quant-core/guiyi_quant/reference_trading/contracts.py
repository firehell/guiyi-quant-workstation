"""Pure, versioned contracts for unified reference-trading projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
from typing import Self


class RecordingMode(StrEnum):
    HISTORICAL_REPLAY = "historical_replay"
    FORWARD_OBSERVATION = "forward_observation"


class ActionKind(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE = "CLOSE"
    HINT = "HINT"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class ReturnPolicy(StrEnum):
    RATIO_MINUS_ONE = "ratio_minus_one"
    DELTA_OVER_ENTRY = "delta_over_entry"


class TradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ROLLOVER_INTERRUPTED = "ROLLOVER_INTERRUPTED"
    DATA_INTERRUPTED = "DATA_INTERRUPTED"
    OBSERVATION_INTERRUPTED = "OBSERVATION_INTERRUPTED"


class BoundaryReason(StrEnum):
    ROLLOVER = "ROLLOVER"
    DATA_INTERRUPTED = "DATA_INTERRUPTED"
    OBSERVATION_INTERRUPTED = "OBSERVATION_INTERRUPTED"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _day(value: object, name: str) -> date:
    if type(value) is not date:
        raise ValueError(f"{name} must be a date")
    return value


def _price(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"{name} must be finite and positive")
    return value


@dataclass(frozen=True, slots=True)
class StreamIdentity:
    strategy_code: str
    formula_versions: tuple[str, ...]
    profile_id: str
    reference_model_version: str
    futures_adaptation_version: str
    product: str
    frequency: str
    series_kind: str
    recording_mode: RecordingMode
    observation_policy_version: str | None

    def __post_init__(self) -> None:
        for name in (
            "strategy_code", "profile_id", "reference_model_version", "futures_adaptation_version",
            "product", "frequency", "series_kind",
        ):
            _text(getattr(self, name), name)
        if isinstance(self.formula_versions, str):
            raise TypeError("formula_versions must be a tuple of versions")
        formulas = tuple(self.formula_versions)
        if not formulas:
            raise ValueError("formula_versions must not be empty")
        for formula in formulas:
            _text(formula, "formula_version")
        object.__setattr__(self, "formula_versions", formulas)
        mode = RecordingMode(self.recording_mode)
        object.__setattr__(self, "recording_mode", mode)
        if mode is RecordingMode.FORWARD_OBSERVATION:
            _text(self.observation_policy_version, "observation_policy_version")
        elif self.observation_policy_version is not None:
            raise ValueError("historical_replay must not set observation_policy_version")

    @property
    def stream_id(self) -> str:
        payload = {
            "formula_versions": self.formula_versions,
            "frequency": self.frequency,
            "futures_adaptation_version": self.futures_adaptation_version,
            "observation_policy_version": self.observation_policy_version,
            "product": self.product,
            "profile_id": self.profile_id,
            "recording_mode": self.recording_mode.value,
            "reference_model_version": self.reference_model_version,
            "series_kind": self.series_kind,
            "strategy_code": self.strategy_code,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"reference-stream:{sha256(encoded.encode()).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ReferenceAction:
    stream: StreamIdentity
    source_action_id: str
    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    bar_end: datetime
    trading_day: date
    sequence: int
    kind: ActionKind
    reference_price: Decimal
    entry_action_id: str | None = None
    reference_price_type: str = "strategy_reference"

    def __post_init__(self) -> None:
        if not isinstance(self.stream, StreamIdentity):
            raise TypeError("stream must be StreamIdentity")
        for name in (
            "source_action_id", "physical_contract", "owner_segment_id", "calculation_segment_id", "reference_price_type",
        ):
            _text(getattr(self, name), name)
        _instant(self.bar_end, "bar_end")
        _day(self.trading_day, "trading_day")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        kind = ActionKind(self.kind)
        object.__setattr__(self, "kind", kind)
        _price(self.reference_price, "reference_price")
        if kind is ActionKind.CLOSE:
            _text(self.entry_action_id, "entry_action_id")
        elif self.entry_action_id is not None:
            raise ValueError("only CLOSE may set entry_action_id")


@dataclass(frozen=True, slots=True)
class ReferenceBoundary:
    stream: StreamIdentity
    reason: BoundaryReason
    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    bar_end: datetime
    trading_day: date

    def __post_init__(self) -> None:
        if not isinstance(self.stream, StreamIdentity):
            raise TypeError("stream must be StreamIdentity")
        object.__setattr__(self, "reason", BoundaryReason(self.reason))
        for name in ("physical_contract", "owner_segment_id", "calculation_segment_id"):
            _text(getattr(self, name), name)
        _instant(self.bar_end, "bar_end")
        _day(self.trading_day, "trading_day")
        if self.reason is BoundaryReason.OBSERVATION_INTERRUPTED and self.stream.recording_mode is not RecordingMode.FORWARD_OBSERVATION:
            raise ValueError("OBSERVATION_INTERRUPTED requires forward_observation")


@dataclass(frozen=True, slots=True)
class CompletedReferenceBar:
    """Authoritative completed mark, including the owner identity that produced it."""

    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    bar_end: datetime
    trading_day: date
    reference_price: Decimal

    def __post_init__(self) -> None:
        for name in ("physical_contract", "owner_segment_id", "calculation_segment_id"):
            _text(getattr(self, name), name)
        _instant(self.bar_end, "bar_end")
        _day(self.trading_day, "trading_day")
        _price(self.reference_price, "reference_price")


@dataclass(frozen=True, slots=True)
class ReferenceTrade:
    reference_trade_id: str
    stream: StreamIdentity
    side: Side
    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    entry_action_id: str
    entry_bar_end: datetime
    entry_trading_day: date
    entry_reference_price: Decimal
    status: TradeStatus = TradeStatus.OPEN
    exit_action_id: str | None = None
    exit_bar_end: datetime | None = None
    exit_trading_day: date | None = None
    exit_reference_price: Decimal | None = None
    reference_return: Decimal | None = None
    holding_bars: int = 0
    mark_bar_end: datetime | None = None
    mark_trading_day: date | None = None
    mark_reference_price: Decimal | None = None
    mark_return: Decimal | None = None

    def __post_init__(self) -> None:
        _text(self.reference_trade_id, "reference_trade_id")
        if not isinstance(self.stream, StreamIdentity):
            raise TypeError("stream must be StreamIdentity")
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "status", TradeStatus(self.status))
        for name in ("physical_contract", "owner_segment_id", "calculation_segment_id", "entry_action_id"):
            _text(getattr(self, name), name)
        _instant(self.entry_bar_end, "entry_bar_end")
        _day(self.entry_trading_day, "entry_trading_day")
        _price(self.entry_reference_price, "entry_reference_price")
        if type(self.holding_bars) is not int or self.holding_bars < 0:
            raise ValueError("holding_bars must be non-negative")
        exit_values = (self.exit_action_id, self.exit_bar_end, self.exit_trading_day, self.exit_reference_price, self.reference_return)
        if self.status is TradeStatus.CLOSED:
            if any(value is None for value in exit_values):
                raise ValueError("closed trade requires complete exit")
            _text(self.exit_action_id, "exit_action_id")
            _instant(self.exit_bar_end, "exit_bar_end")
            _day(self.exit_trading_day, "exit_trading_day")
            _price(self.exit_reference_price, "exit_reference_price")
            if not isinstance(self.reference_return, Decimal) or not self.reference_return.is_finite():
                raise ValueError("reference_return must be finite Decimal")
        elif any(value is not None for value in exit_values):
            raise ValueError("non-closed trade must not carry an exit")
        marks = (self.mark_bar_end, self.mark_trading_day, self.mark_reference_price, self.mark_return)
        if any(value is not None for value in marks):
            if self.status is not TradeStatus.OPEN or any(value is None for value in marks):
                raise ValueError("only OPEN trade may carry a complete mark")
            _instant(self.mark_bar_end, "mark_bar_end")
            _day(self.mark_trading_day, "mark_trading_day")
            _price(self.mark_reference_price, "mark_reference_price")
            if not isinstance(self.mark_return, Decimal) or not self.mark_return.is_finite():
                raise ValueError("mark_return must be finite Decimal")


@dataclass(frozen=True, slots=True)
class ReferenceMark:
    reference_trade_id: str
    bar_end: datetime
    trading_day: date
    reference_price: Decimal
    holding_bars: int
    reference_return: Decimal

    def __post_init__(self) -> None:
        _text(self.reference_trade_id, "reference_trade_id")
        _instant(self.bar_end, "bar_end")
        _day(self.trading_day, "trading_day")
        _price(self.reference_price, "reference_price")
        if type(self.holding_bars) is not int or self.holding_bars < 0:
            raise ValueError("holding_bars must be non-negative")
        if not isinstance(self.reference_return, Decimal) or not self.reference_return.is_finite():
            raise ValueError("reference_return must be finite Decimal")


@dataclass(frozen=True, slots=True)
class ReferenceState:
    stream: StreamIdentity
    recording_start: datetime | None = None
    computed_through: datetime | None = None
    open_trade: ReferenceTrade | None = None
    last_input_hash: str | None = None
    last_event_key: tuple[datetime, int, int] | None = None

    @classmethod
    def flat(cls, stream: StreamIdentity, *, recording_start: datetime | None = None) -> Self:
        return cls(stream=stream, recording_start=recording_start)

    def __post_init__(self) -> None:
        if not isinstance(self.stream, StreamIdentity):
            raise TypeError("stream must be StreamIdentity")
        if self.recording_start is not None:
            _instant(self.recording_start, "recording_start")
        if self.stream.recording_mode is RecordingMode.FORWARD_OBSERVATION and self.recording_start is None:
            raise ValueError("forward_observation requires recording_start")
        if self.computed_through is not None:
            _instant(self.computed_through, "computed_through")
            if self.recording_start is not None and self.computed_through < self.recording_start:
                raise ValueError("computed_through must not precede recording_start")
        if self.open_trade is not None:
            if not isinstance(self.open_trade, ReferenceTrade) or self.open_trade.status is not TradeStatus.OPEN:
                raise ValueError("open_trade must be an OPEN ReferenceTrade")
            if self.open_trade.stream != self.stream:
                raise ValueError("open_trade must belong to stream")
            if self.recording_start is not None and self.open_trade.entry_bar_end < self.recording_start:
                raise ValueError("open_trade entry must not precede recording_start")
        if self.last_input_hash is not None:
            _text(self.last_input_hash, "last_input_hash")
        if self.last_event_key is not None:
            if (
                not isinstance(self.last_event_key, tuple) or len(self.last_event_key) != 3
                or not isinstance(self.last_event_key[1], int) or not isinstance(self.last_event_key[2], int)
            ):
                raise ValueError("last_event_key must be (instant, kind, sequence)")
            _instant(self.last_event_key[0], "last_event_key instant")
            if self.recording_start is not None and self.last_event_key[0] < self.recording_start:
                raise ValueError("last_event_key must not precede recording_start")


@dataclass(frozen=True, slots=True)
class ReferenceTransition:
    state: ReferenceState
    changed_trades: tuple[ReferenceTrade, ...]
    marks: tuple[ReferenceMark, ...]
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.state, ReferenceState):
            raise TypeError("state must be ReferenceState")
        object.__setattr__(self, "changed_trades", tuple(self.changed_trades))
        object.__setattr__(self, "marks", tuple(self.marks))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not all(isinstance(trade, ReferenceTrade) for trade in self.changed_trades):
            raise TypeError("changed_trades must contain ReferenceTrade")
        if not all(isinstance(mark, ReferenceMark) for mark in self.marks):
            raise TypeError("marks must contain ReferenceMark")
        for diagnostic in self.diagnostics:
            _text(diagnostic, "diagnostic")
