"""Immutable physical-series inputs and point-aligned analysis outputs."""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from itertools import accumulate
from math import isfinite
import json
from types import MappingProxyType
from typing import Literal, Mapping


FREQUENCIES = frozenset(("1m", "5m", "15m", "30m", "60m", "1d", "1w"))
RESULT_SCHEMA_VERSION = "guiyi_feature_result_v1"
STATE_SCHEMA_VERSION = "guiyi_compute_state_v1"
EMPTY_PREFIX_DIGEST = sha256(b"guiyi_compute_prefix_v1").hexdigest()
EMPTY_DEPENDENCY_HASH = sha256(b"[]").hexdigest()
InputField = Literal["open", "high", "low", "close", "volume"]
ParameterValue = str | int | float


class Status(StrEnum):
    READY = "READY"
    WARMING = "WARMING"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class SeriesIdentity:
    product: str
    physical_contract: str
    segment_id: str
    frequency: str
    source_revision: str

    def __post_init__(self) -> None:
        identifiers = (self.product, self.physical_contract, self.segment_id, self.source_revision)
        if any(not isinstance(value, str) or not value.strip() for value in identifiers):
            raise ValueError("SERIES_IDENTITY_REQUIRED")
        if self.frequency not in FREQUENCIES:
            raise ValueError("UNSUPPORTED_FREQUENCY")


def require_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")


@dataclass(frozen=True, slots=True)
class CompletedBar:
    physical_contract: str
    segment_id: str
    trading_day: date
    session_id: str
    bar_end: datetime
    confirmed_at: datetime
    available_at: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    quality_status: Literal["VALID", "MISSING", "INVALID"]

    def __post_init__(self) -> None:
        for value in (self.bar_end, self.confirmed_at, self.available_at):
            require_aware(value)
        if self.bar_end > self.confirmed_at or self.confirmed_at > self.available_at:
            raise ValueError("BAR_TIME_ORDER_INVALID")
        if not self.session_id or self.quality_status not in ("VALID", "MISSING", "INVALID"):
            raise ValueError("BAR_SESSION_OR_QUALITY_INVALID")


def extend_prefix_digest(digest: str, bar: CompletedBar) -> str:
    def timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    raw = [
        bar.physical_contract, bar.segment_id, bar.trading_day.isoformat(), bar.session_id,
        timestamp(bar.bar_end), timestamp(bar.confirmed_at), timestamp(bar.available_at), bar.quality_status,
        [float(value).hex() if value is not None else None
         for value in (bar.open, bar.high, bar.low, bar.close, bar.volume)],
    ]
    return sha256(bytes.fromhex(digest) + json.dumps(raw, separators=(",", ":")).encode()).hexdigest()



@dataclass(frozen=True, slots=True)
class BarSeries:
    identity: SeriesIdentity
    bars: tuple[CompletedBar, ...]
    _prefix_digests: tuple[str, ...] = field(init=False, repr=False, compare=False)
    _prefix_available_at: tuple[datetime, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        bars = tuple(self.bars)
        previous = None
        digests = [EMPTY_PREFIX_DIGEST]
        for bar in bars:
            if (bar.physical_contract, bar.segment_id) != (
                self.identity.physical_contract, self.identity.segment_id
            ):
                raise ValueError("BAR_OWNER_CHANGED")
            if previous is not None and bar.bar_end <= previous:
                raise ValueError("BAR_END_NOT_ASCENDING")
            previous = bar.bar_end
            digests.append(extend_prefix_digest(digests[-1], bar))
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "_prefix_digests", tuple(digests))
        object.__setattr__(
            self, "_prefix_available_at", tuple(accumulate((bar.available_at for bar in bars), max))
        )

    def available_count(self, as_of: datetime) -> int:
        require_aware(as_of)
        return bisect_right(self._prefix_available_at, as_of)

    def prefix_digest(self, count: int) -> str:
        if not 0 <= count <= len(self.bars):
            raise ValueError("PREFIX_SIZE_INVALID")
        return self._prefix_digests[count]

    def point_availability(self, count: int) -> tuple[datetime, ...]:
        """A later Bar can only be used after the required earlier prefix is available."""
        return self._prefix_available_at[:count]


@dataclass(frozen=True, slots=True)
class FeatureIdentity:
    source: SeriesIdentity
    feature_id: str
    formula_version: str
    parameters_hash: str
    backend_version: str
    as_of: datetime
    first_bar_end: datetime | None
    last_bar_end: datetime | None
    bar_count: int
    input_digest: str
    dependency_hash: str = EMPTY_DEPENDENCY_HASH
    result_schema_version: str = RESULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class FeaturePoint:
    bar_end: datetime
    available_at: datetime
    status: Status
    values: Mapping[str, ParameterValue] | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if self.values is not None:
            object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class FeatureMarker:
    kind: str
    occurred_at: datetime
    confirmed_at: datetime
    available_at: datetime
    price: float
    confirmation_bar_end: datetime
    classification: str | None = None
    retrospective: bool = False

    def __post_init__(self) -> None:
        for value in (self.occurred_at, self.confirmation_bar_end, self.confirmed_at, self.available_at):
            require_aware(value)
        if (
            not self.occurred_at <= self.confirmation_bar_end <= self.confirmed_at <= self.available_at
            or not isfinite(self.price)
        ):
            raise ValueError("FEATURE_MARKER_INVALID")


@dataclass(frozen=True, slots=True)
class FeatureResult:
    identity: FeatureIdentity
    parameters: Mapping[str, ParameterValue]
    points: tuple[FeaturePoint, ...]
    markers: tuple[FeatureMarker, ...] = ()
    output_schema_version: str = "aligned_points_v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    @property
    def status(self) -> Status:
        return self.points[-1].status if self.points else Status.WARMING


def hash_parameters(parameters: Mapping[str, ParameterValue]) -> str:
    raw = json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(raw.encode()).hexdigest()[:16]
