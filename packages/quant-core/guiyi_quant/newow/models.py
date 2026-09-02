from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Iterator, Mapping


class TrendBandState(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    YELLOW = "YELLOW"
    BLUE = "BLUE"


class TrendTransition(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"


class NewowMarkerType(StrEnum):
    BUILD = "BUILD"
    CLEAR = "CLEAR"
    ESCAPE_D1 = "NEWOW_ESCAPE_D1"
    ESCAPE_D2 = "NEWOW_ESCAPE_D2"
    ESCAPE_D3 = "NEWOW_ESCAPE_D3"
    CUP_HANDLE_READY = "CUP_HANDLE_READY"
    CUP_HANDLE_BREAKOUT = "CUP_HANDLE_BREAKOUT"
    CUP_HANDLE_WEAKENED = "CUP_HANDLE_WEAKENED"
    CUP_HANDLE_INVALIDATED = "CUP_HANDLE_INVALIDATED"
    CUP_HANDLE_EXPIRED = "CUP_HANDLE_EXPIRED"


class EscapeSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    BEAR_CONFIRMATION = "BEAR_CONFIRMATION"


class CupHandleDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class CupHandleState(StrEnum):
    NONE = "NONE"
    FORMING = "FORMING"
    READY = "READY"
    BREAKOUT = "BREAKOUT"
    WEAKENED = "WEAKENED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class CupPivotKind(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class _FrozenMapping(Mapping[str, object]):
    """Small pickle-safe immutable mapping for frozen public facts."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __reduce__(self) -> tuple[object, tuple[dict[str, object]]]:
        return (_FrozenMapping, (dict(self._values),))

    def __deepcopy__(self, memo: dict[int, object]) -> _FrozenMapping:
        return self


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _FrozenMapping({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return _FrozenMapping({str(key): _freeze_value(value) for key, value in values.items()})


@dataclass(frozen=True, slots=True)
class NewowDailyBar:
    """A completed actual-dominant D1 bar supplied by the application layer.

    ``observation_eligible`` is the upstream rank-1 formal-output eligibility
    flag. The pure core preserves it and does not query ``MainContractMap``.
    """

    product: str
    physical_contract: str
    segment_id: str
    trading_day: date
    bar_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int | None
    source_identity: str
    observation_eligible: bool
    completed: bool
    series_kind: str = "actual_dominant"
    frequency: str = "1d"

    def __post_init__(self) -> None:
        if not self.completed:
            raise ValueError("NEWOW_BAR_NOT_COMPLETED")
        if self.series_kind != "actual_dominant":
            raise ValueError("NEWOW_BAR_INVALID_SERIES_KIND")
        if self.frequency != "1d":
            raise ValueError("NEWOW_BAR_INVALID_FREQUENCY")
        if not self.product or self.product != self.product.lower():
            raise ValueError("NEWOW_BAR_INVALID_PRODUCT")
        if not self.physical_contract or self.physical_contract != self.physical_contract.upper():
            raise ValueError("NEWOW_BAR_INVALID_PHYSICAL_CONTRACT")
        if not self.segment_id or not self.source_identity:
            raise ValueError("NEWOW_BAR_EMPTY_IDENTITY")
        if self.bar_end.tzinfo is None or self.bar_end.utcoffset() is None:
            raise ValueError("NEWOW_BAR_NAIVE_TIMESTAMP")
        if not all(isinstance(value, Decimal) for value in self._prices):
            raise ValueError("NEWOW_BAR_PRICE_MUST_BE_DECIMAL")
        if not all(value.is_finite() for value in self._prices):
            raise ValueError("NEWOW_BAR_INVALID_OHLC")
        if any(value <= 0 for value in self._prices):
            raise ValueError("NEWOW_BAR_NONPOSITIVE_PRICE")
        if self.low > self.high or not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ValueError("NEWOW_BAR_INVALID_OHLC")
        if self.volume < 0 or (self.open_interest is not None and self.open_interest < 0):
            raise ValueError("NEWOW_BAR_NEGATIVE_VOLUME_OR_OI")

    @property
    def _prices(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return (self.open, self.high, self.low, self.close)


@dataclass(frozen=True, slots=True)
class NewowTrendBandPoint:
    bar_end: datetime
    b_value: float | None
    c_value: float | None
    state: TrendBandState
    state_before: TrendBandState | None
    transition: TrendTransition | None = None


@dataclass(frozen=True, slots=True)
class NewowMainMarker:
    marker_id: str
    marker_type: NewowMarkerType
    bar_end: datetime
    price: Decimal
    label: str
    color_token: str
    priority: int
    related_marker_ids: tuple[str, ...]
    trigger_facts: Mapping[str, object] = field(default_factory=dict)
    formula_version: str = ""
    severity: EscapeSeverity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "related_marker_ids", tuple(self.related_marker_ids))
        object.__setattr__(self, "trigger_facts", _freeze_mapping(self.trigger_facts))


@dataclass(frozen=True, slots=True)
class CupPivot:
    kind: CupPivotKind
    price: Decimal
    pivot_at: datetime
    confirmed_at: datetime
    pivot_index: int
    confirmed_index: int
    atr_at_pivot: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, CupPivotKind)
            or not isinstance(self.price, Decimal)
            or not isinstance(self.pivot_at, datetime)
            or self.pivot_at.tzinfo is None
            or self.pivot_at.utcoffset() is None
            or not isinstance(self.confirmed_at, datetime)
            or self.confirmed_at.tzinfo is None
            or self.confirmed_at.utcoffset() is None
            or type(self.pivot_index) is not int
            or type(self.confirmed_index) is not int
            or not self.price.is_finite()
            or self.price <= 0
            or isinstance(self.atr_at_pivot, bool)
            or not isinstance(self.atr_at_pivot, (int, float))
            or not isfinite(self.atr_at_pivot)
            or self.atr_at_pivot <= 0
            or self.confirmed_at < self.pivot_at
            or self.confirmed_index < self.pivot_index
            or (
                self.confirmed_index == self.pivot_index
                and self.confirmed_at != self.pivot_at
            )
            or self.pivot_index < 0
        ):
            raise ValueError("NEWOW_CUP_PIVOT_INVALID")


@dataclass(frozen=True, slots=True)
class NewowCupHandleOverlay:
    candidate_id: str
    direction: CupHandleDirection
    state: CupHandleState
    left_rim: CupPivot
    bottom: CupPivot
    right_rim: CupPivot
    handle_start_at: datetime
    handle_extreme: CupPivot | None
    pivot_price: Decimal | None
    pivot_frozen_at: datetime | None
    confirmed_at: datetime
    first_seen_at: datetime
    state_changed_at: datetime
    score: float
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    hard_failures: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    volume_facts: Mapping[str, float] = field(default_factory=dict)
    formula_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_breakdown", _freeze_mapping(self.score_breakdown))
        object.__setattr__(self, "hard_failures", tuple(self.hard_failures))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "volume_facts", _freeze_mapping(self.volume_facts))
        if (
            not self.candidate_id
            or not self.formula_version
            or not isinstance(self.direction, CupHandleDirection)
            or not isinstance(self.state, CupHandleState)
            or self.state == CupHandleState.NONE
            or not isfinite(self.score)
            or not 0 <= self.score <= 100
            or self.hard_failures
        ):
            raise ValueError("NEWOW_CUP_OVERLAY_INVALID")
        expected_rim_kind = (
            CupPivotKind.HIGH
            if self.direction == CupHandleDirection.BULLISH
            else CupPivotKind.LOW
        )
        if (
            self.left_rim.kind != expected_rim_kind
            or self.right_rim.kind != expected_rim_kind
            or self.bottom.kind == expected_rim_kind
            or not (
                self.left_rim.pivot_index
                < self.bottom.pivot_index
                < self.right_rim.pivot_index
            )
        ):
            raise ValueError("NEWOW_CUP_OVERLAY_INVALID")
        if self.handle_extreme is not None and (
            self.handle_extreme.kind != self.bottom.kind
            or self.handle_extreme.pivot_index <= self.right_rim.pivot_index
        ):
            raise ValueError("NEWOW_CUP_OVERLAY_INVALID")
        if self.state in {
            CupHandleState.READY,
            CupHandleState.BREAKOUT,
            CupHandleState.WEAKENED,
            CupHandleState.INVALIDATED,
            CupHandleState.EXPIRED,
        } and (self.handle_extreme is None or self.pivot_price is None or self.pivot_frozen_at is None):
            raise ValueError("NEWOW_CUP_OVERLAY_INVALID")
        if self.pivot_price is not None and (
            not self.pivot_price.is_finite() or self.pivot_price <= 0
        ):
            raise ValueError("NEWOW_CUP_OVERLAY_INVALID")


@dataclass(frozen=True, slots=True)
class NewowTrendFrame:
    bar: NewowDailyBar
    trend_band: NewowTrendBandPoint
    markers: tuple[NewowMainMarker, ...]
    cup_handle: NewowCupHandleOverlay | None
    rollover_started: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "markers", tuple(self.markers))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
