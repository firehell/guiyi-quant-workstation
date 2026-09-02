from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


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


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))


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
class NewowCupHandleOverlay:
    candidate_id: str
    direction: CupHandleDirection
    state: CupHandleState
    left_rim: datetime | None
    bottom: datetime | None
    right_rim: datetime | None
    handle_start: datetime | None
    handle_extreme: datetime | None
    pivot_price: Decimal | None
    confirmed_at: datetime | None
    first_seen_at: datetime | None
    score: float | None
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    hard_failures: tuple[str, ...] = ()
    volume_facts: Mapping[str, float] = field(default_factory=dict)
    formula_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_breakdown", _freeze_mapping(self.score_breakdown))
        object.__setattr__(self, "hard_failures", tuple(self.hard_failures))
        object.__setattr__(self, "volume_facts", _freeze_mapping(self.volume_facts))


@dataclass(frozen=True, slots=True)
class NewowTrendFrame:
    bar: NewowDailyBar
    trend_band: NewowTrendBandPoint
    markers: tuple[NewowMainMarker, ...]
    cup_handle: NewowCupHandleOverlay | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "markers", tuple(self.markers))
