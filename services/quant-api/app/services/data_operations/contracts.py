"""Validated request/result contracts for unified data CLI operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.data_core.bar_schema import CANONICAL_BAR_SCHEMA_VERSION
from app.data_core.contracts import (
    DERIVED_FREQUENCIES,
    DIRECT_FREQUENCIES,
    BarFrequency,
    DatasetKind,
)


ResultSchemaVersion = 2
DEFAULT_PROVIDER = "rqdata"
DEFAULT_ADJUSTMENT = "none"
DEFAULT_SCHEMA_VERSION = CANONICAL_BAR_SCHEMA_VERSION
MAX_BATCH_TARGETS = 500
MAX_BATCH_BYTES = 1_048_576


class DirectFrequency(StrEnum):
    M1 = "1m"
    D1 = "1d"
    W1 = "1w"


class DerivedFrequency(StrEnum):
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "60m"


class AuditScope(StrEnum):
    CATALOG = "catalog"
    COVERAGE = "coverage"
    SCHEMA = "schema"
    PHYSICAL = "physical"
    GAP = "gap"
    ALL = "all"


class MetadataSyncScope(StrEnum):
    INSTRUMENTS = "instruments"
    CONTRACTS = "contracts"
    CALENDAR = "calendar"
    SESSIONS = "sessions"
    MAIN_CONTRACT_MAP = "main-contract-map"
    ALL = "all"


class CommandStatus(StrEnum):
    PLANNED = "planned"
    PASSED = "passed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    ERROR = "error"


class DataOperationsError(ValueError):
    error_code = "DATA_OPERATIONS_ERROR"

    def __init__(
        self,
        *,
        code: str | None = None,
        facts: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code or self.error_code
        self.facts = MappingProxyType(dict(facts or {}))
        super().__init__(self.code)


class CliArgumentInvalid(DataOperationsError):
    error_code = "CLI_ARGUMENT_INVALID"


@dataclass(frozen=True, slots=True)
class PublicError:
    code: str
    type: str

    def as_payload(self) -> dict[str, str]:
        return {"code": self.code, "type": self.type}


@dataclass(frozen=True, slots=True)
class EffectSummary:
    calls_rqdata: bool = False
    writes_provider_raw: bool = False
    writes_staging: bool = False
    writes_canonical: bool = False
    writes_postgresql: bool = False
    writes_live_observation: bool = False
    writes_historical_active: bool = False
    sends_notification: bool = False
    creates_order: bool = False
    auto_order: bool = False

    def __post_init__(self) -> None:
        if self.auto_order is not False or self.creates_order is not False:
            raise DataOperationsError(
                code="AUTO_ORDER_INVARIANT",
                facts={"auto_order": self.auto_order, "creates_order": self.creates_order},
            )

    def as_payload(self) -> dict[str, bool]:
        return asdict(self)

    @property
    def any_mutating(self) -> bool:
        return any(
            (
                self.calls_rqdata,
                self.writes_provider_raw,
                self.writes_staging,
                self.writes_canonical,
                self.writes_postgresql,
                self.writes_live_observation,
                self.writes_historical_active,
                self.sends_notification,
                self.creates_order,
            )
        )


def empty_effects() -> EffectSummary:
    return EffectSummary()


@dataclass(frozen=True, slots=True)
class DataTarget:
    provider: str
    dataset_kind: DatasetKind
    symbol: str
    contract_or_series: str
    frequency: BarFrequency
    adjustment: str
    schema_version: str
    start: datetime
    end: datetime

    def identity_tuple(self) -> tuple[object, ...]:
        return (
            self.provider,
            self.dataset_kind.value,
            self.symbol,
            self.contract_or_series,
            self.frequency.value,
            self.adjustment,
            self.schema_version,
            self.start,
            self.end,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "dataset_kind": self.dataset_kind.value,
            "symbol": self.symbol,
            "contract_or_series": self.contract_or_series,
            "frequency": self.frequency.value,
            "adjustment": self.adjustment,
            "schema_version": self.schema_version,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class TargetResult:
    target: DataTarget
    status: CommandStatus
    detail: Mapping[str, Any] = field(default_factory=dict)
    error: PublicError | None = None

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target": self.target.as_payload(),
            "status": self.status.value,
            "detail": dict(self.detail),
        }
        if self.error is not None:
            payload["error"] = self.error.as_payload()
        return payload


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    status: CommandStatus
    readonly: bool
    effects: EffectSummary
    targets: Sequence[TargetResult] = ()
    error: PublicError | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = ResultSchemaVersion

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "command": self.command,
            "status": self.status.value,
            "readonly": self.readonly,
            "effects": self.effects.as_payload(),
            "targets": [item.as_payload() for item in self.targets],
        }
        if self.error is not None:
            payload["error"] = self.error.as_payload()
        for key, value in self.extras.items():
            if key not in payload:
                payload[key] = value
        return payload


@dataclass(frozen=True, slots=True)
class SingleTargetRequest:
    symbol: str
    dataset_kind: DatasetKind
    contract_or_series: str
    frequency: BarFrequency
    start: datetime
    end: datetime
    provider: str = DEFAULT_PROVIDER
    adjustment: str = DEFAULT_ADJUSTMENT
    schema_version: str = DEFAULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class BatchTargetRequest:
    symbols_file: Path
    dataset_kind: DatasetKind
    frequency: BarFrequency
    start: datetime
    end: datetime
    provider: str = DEFAULT_PROVIDER
    adjustment: str = DEFAULT_ADJUSTMENT
    schema_version: str = DEFAULT_SCHEMA_VERSION
    allowed_roots: Sequence[Path] = ()
    max_targets: int = MAX_BATCH_TARGETS
    max_bytes: int = MAX_BATCH_BYTES


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    targets: Sequence[DataTarget]
    apply: bool = False
    batch_size: int | None = None


@dataclass(frozen=True, slots=True)
class AggregateRequest:
    targets: Sequence[DataTarget]
    apply: bool = False
    batch_size: int | None = None


@dataclass(frozen=True, slots=True)
class LiveRequest:
    targets: Sequence[DataTarget]
    confirm_observation_write: bool = False


@dataclass(frozen=True, slots=True)
class MetadataSyncRequest:
    scope: MetadataSyncScope
    apply: bool = False
    symbols: Sequence[str] = ()
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditRequest:
    scope: AuditScope
    symbols: Sequence[str] = ()
    dataset_kind: DatasetKind | None = None
    frequency: BarFrequency | None = None
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoricalUpdateRequest:
    """High-level retained-universe historical catch-up request.

    ``since`` / ``through`` are inclusive trading days. They are materialized to
    timezone-aware half-open ``[start, end)`` windows on ``DataTarget``.
    """

    products: tuple[str, ...]
    through: date | None = None
    since: date | None = None
    apply: bool = False

    def __post_init__(self) -> None:
        normalized = tuple(
            str(product).strip().lower() for product in self.products
        )
        if not normalized or any(not product for product in normalized):
            raise CliArgumentInvalid(
                code="HISTORICAL_UPDATE_PRODUCTS_REQUIRED"
            )
        if len(set(normalized)) != len(normalized):
            raise CliArgumentInvalid(
                code="HISTORICAL_UPDATE_PRODUCTS_DUPLICATE"
            )
        if any(
            not isinstance(value, date) or isinstance(value, datetime)
            for value in (self.since, self.through)
            if value is not None
        ):
            raise CliArgumentInvalid(code="HISTORICAL_UPDATE_DATE_INVALID")
        if (
            self.since is not None
            and self.through is not None
            and self.since > self.through
        ):
            raise CliArgumentInvalid(code="HISTORICAL_UPDATE_WINDOW_INVALID")
        if not isinstance(self.apply, bool):
            raise CliArgumentInvalid(code="HISTORICAL_UPDATE_APPLY_INVALID")
        object.__setattr__(self, "products", normalized)


DIRECT_FREQUENCY_VALUES = frozenset(item.value for item in DirectFrequency)
DERIVED_FREQUENCY_VALUES = frozenset(item.value for item in DerivedFrequency)


def require_direct_frequency(frequency: BarFrequency) -> BarFrequency:
    if frequency not in DIRECT_FREQUENCIES:
        raise CliArgumentInvalid(
            facts={"field": "frequency", "value": frequency.value, "allowed": "direct"}
        )
    return frequency


def require_derived_frequency(frequency: BarFrequency) -> BarFrequency:
    if frequency not in DERIVED_FREQUENCIES:
        raise CliArgumentInvalid(
            facts={"field": "frequency", "value": frequency.value, "allowed": "derived"}
        )
    return frequency


def overall_batch_status(results: Sequence[TargetResult]) -> CommandStatus:
    if not results:
        return CommandStatus.PASSED
    statuses = {item.status for item in results}
    if statuses == {CommandStatus.PASSED}:
        return CommandStatus.PASSED
    if statuses == {CommandStatus.PLANNED}:
        return CommandStatus.PLANNED
    if CommandStatus.PASSED in statuses and (
        CommandStatus.ERROR in statuses
        or CommandStatus.BLOCKED in statuses
        or CommandStatus.PARTIAL in statuses
    ):
        return CommandStatus.PARTIAL
    if CommandStatus.BLOCKED in statuses and CommandStatus.PASSED not in statuses:
        return CommandStatus.BLOCKED
    return CommandStatus.ERROR
