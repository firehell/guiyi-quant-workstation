from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from app.data_core.bar_schema import CanonicalBar


class DatasetKind(StrEnum):
    CONTINUOUS = "continuous"
    ACTUAL_DOMINANT = "actual_dominant"


class BarFrequency(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "60m"
    D1 = "1d"
    W1 = "1w"


class DatasetOrigin(StrEnum):
    PROVIDER_DIRECT = "provider_direct"
    PREAGGREGATED_FROM_1M = "preaggregated_from_1m"


DIRECT_FREQUENCIES = frozenset(
    {
        BarFrequency.M1,
        BarFrequency.D1,
        BarFrequency.W1,
    }
)
DERIVED_FREQUENCIES = frozenset(
    {
        BarFrequency.M5,
        BarFrequency.M15,
        BarFrequency.M30,
        BarFrequency.H1,
    }
)
PERSISTED_FREQUENCIES = DIRECT_FREQUENCIES | DERIVED_FREQUENCIES
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_CONCRETE_CONTRACT_PATTERN = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")


class DataCoreError(ValueError):
    error_code = "DATA_CORE_ERROR"

    def __init__(self, *, facts: Mapping[str, Any] | None = None) -> None:
        if facts is None:
            facts = {}
        if not isinstance(facts, Mapping):
            raise TypeError("facts must be a mapping")
        self.code = self.error_code
        self.facts = MappingProxyType(dict(facts))
        super().__init__(self.code)


class ContractValidationError(DataCoreError):
    error_code = "DATA_CONTRACT_INVALID"


class DataGapError(DataCoreError):
    error_code = "DATA_GAP"


class DatasetAmbiguousError(DataCoreError):
    error_code = "DATASET_AMBIGUOUS"


class ManifestMismatchError(DataCoreError):
    error_code = "MANIFEST_MISMATCH"


@dataclass(frozen=True, slots=True)
class ManifestLineage:
    origin: DatasetOrigin
    source_frequency: BarFrequency | None = None
    legacy_source_checksum: str | None = None
    quality_evidence_digest: str | None = None

    def __post_init__(self) -> None:
        try:
            origin = DatasetOrigin(self.origin)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                facts={"field": "lineage", "reason": "origin_invalid"}
            ) from exc
        object.__setattr__(self, "origin", origin)
        if origin is DatasetOrigin.PROVIDER_DIRECT:
            if any(
                value is not None
                for value in (
                    self.source_frequency,
                    self.legacy_source_checksum,
                    self.quality_evidence_digest,
                )
            ):
                raise ContractValidationError(
                    facts={
                        "field": "lineage",
                        "reason": "provider_direct_fields_invalid",
                    }
                )
            return
        try:
            source_frequency = BarFrequency(self.source_frequency)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                facts={
                    "field": "lineage",
                    "reason": "aggregate_source_frequency_invalid",
                }
            ) from exc
        if source_frequency is not BarFrequency.M1:
            raise ContractValidationError(
                facts={
                    "field": "lineage",
                    "reason": "aggregate_source_frequency_invalid",
                }
            )
        object.__setattr__(self, "source_frequency", source_frequency)
        object.__setattr__(
            self,
            "legacy_source_checksum",
            _normalize_sha256(
                self.legacy_source_checksum,
                field="legacy_source_checksum",
            ),
        )
        object.__setattr__(
            self,
            "quality_evidence_digest",
            _normalize_sha256(
                self.quality_evidence_digest,
                field="quality_evidence_digest",
            ),
        )

    @classmethod
    def from_payload(cls, payload: object) -> ManifestLineage:
        if not isinstance(payload, Mapping):
            raise ContractValidationError(
                facts={"field": "lineage", "reason": "schema_invalid"}
            )
        if payload.get("origin") == DatasetOrigin.PROVIDER_DIRECT.value:
            if set(payload) != {"origin"}:
                raise ContractValidationError(
                    facts={"field": "lineage", "reason": "schema_invalid"}
                )
            return cls(origin=DatasetOrigin.PROVIDER_DIRECT)
        aggregate_fields = {
            "origin",
            "source_frequency",
            "legacy_source_checksum",
            "quality_evidence_digest",
        }
        if set(payload) != aggregate_fields:
            raise ContractValidationError(
                facts={"field": "lineage", "reason": "schema_invalid"}
            )
        return cls(
            origin=payload["origin"],  # type: ignore[arg-type]
            source_frequency=payload["source_frequency"],  # type: ignore[arg-type]
            legacy_source_checksum=payload["legacy_source_checksum"],  # type: ignore[arg-type]
            quality_evidence_digest=payload["quality_evidence_digest"],  # type: ignore[arg-type]
        )

    def validate_dataset(self, dataset: DatasetKey) -> None:
        if not isinstance(dataset, DatasetKey):
            raise ContractValidationError(
                facts={"field": "lineage", "reason": "dataset_invalid"}
            )
        if self.origin is DatasetOrigin.PROVIDER_DIRECT:
            allowed = DIRECT_FREQUENCIES
            reason = "provider_direct_frequency_invalid"
        else:
            allowed = DERIVED_FREQUENCIES
            reason = "preaggregated_target_frequency_invalid"
        if dataset.frequency not in allowed:
            raise ContractValidationError(
                facts={
                    "field": "lineage",
                    "reason": reason,
                    "frequency": dataset.frequency.value,
                }
            )

    def as_payload(self) -> dict[str, str]:
        if self.origin is DatasetOrigin.PROVIDER_DIRECT:
            return {"origin": self.origin.value}
        assert self.source_frequency is not None
        assert self.legacy_source_checksum is not None
        assert self.quality_evidence_digest is not None
        return {
            "origin": self.origin.value,
            "source_frequency": self.source_frequency.value,
            "legacy_source_checksum": self.legacy_source_checksum,
            "quality_evidence_digest": self.quality_evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class DatasetKey:
    provider: str
    dataset_kind: DatasetKind
    symbol: str
    contract_or_series: str
    frequency: BarFrequency
    adjustment: str
    schema_version: str

    def __post_init__(self) -> None:
        provider = _normalize_text(self.provider, field="provider", lower=True)
        if provider != "rqdata":
            raise ContractValidationError(
                facts={"field": "provider", "value": provider}
            )
        frequency = _normalize_frequency(self.frequency, field="frequency")
        if frequency not in PERSISTED_FREQUENCIES:
            raise ContractValidationError(
                facts={"field": "frequency", "value": frequency.value}
            )
        object.__setattr__(self, "provider", provider)
        dataset_kind = _normalize_dataset_kind(self.dataset_kind)
        symbol = _normalize_text(self.symbol, field="symbol", lower=True)
        contract_or_series = _normalize_text(
            self.contract_or_series,
            field="contract_or_series",
            upper=True,
        )
        _validate_dataset_identity(
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
        )
        if dataset_kind is DatasetKind.ACTUAL_DOMINANT and frequency is BarFrequency.W1:
            raise ContractValidationError(
                facts={
                    "field": "frequency",
                    "reason": "actual_dominant_weekly_not_supported",
                    "value": frequency.value,
                }
            )
        object.__setattr__(self, "dataset_kind", dataset_kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "contract_or_series", contract_or_series)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(
            self,
            "adjustment",
            _normalize_text(self.adjustment, field="adjustment", lower=True),
        )
        object.__setattr__(
            self,
            "schema_version",
            _normalize_text(self.schema_version, field="schema_version"),
        )


@dataclass(frozen=True, slots=True)
class BarQuery:
    dataset_kind: DatasetKind
    symbol: str
    contract_or_series: str | None
    frequency: BarFrequency
    start: datetime
    end: datetime
    strict: bool = True

    def __post_init__(self) -> None:
        start, end = _normalize_window(self.start, self.end)
        if type(self.strict) is not bool:
            raise ContractValidationError(
                facts={"field": "strict", "value_type": type(self.strict).__name__}
            )
        contract_or_series = self.contract_or_series
        if contract_or_series is not None:
            contract_or_series = _normalize_text(
                contract_or_series,
                field="contract_or_series",
                upper=True,
            )
        dataset_kind = _normalize_dataset_kind(self.dataset_kind)
        symbol = _normalize_text(self.symbol, field="symbol", lower=True)
        _validate_dataset_identity(
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
            allow_resolved_actual=True,
        )
        frequency = _normalize_frequency(self.frequency, field="frequency")
        if dataset_kind is DatasetKind.ACTUAL_DOMINANT and frequency is BarFrequency.W1:
            raise ContractValidationError(
                facts={
                    "field": "frequency",
                    "reason": "actual_dominant_weekly_not_supported",
                    "value": frequency.value,
                }
            )
        object.__setattr__(self, "dataset_kind", dataset_kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "contract_or_series", contract_or_series)
        object.__setattr__(
            self,
            "frequency",
            frequency,
        )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class BarsResult:
    bars: Sequence[CanonicalBar]
    source_datasets: tuple[DatasetKey, ...]
    manifest_digests: tuple[str, ...]
    requested_window: tuple[datetime, datetime]
    data_type: DatasetKind
    derived_frequency: BarFrequency | None
    source_data_versions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from app.data_core.bar_schema import CanonicalBar

        try:
            bars = tuple(self.bars)
            source_datasets = tuple(self.source_datasets)
            manifest_digests = tuple(self.manifest_digests)
            source_data_versions = tuple(self.source_data_versions)
        except TypeError as exc:
            raise ContractValidationError(
                facts={"field": "sequences", "reason": "not_iterable"}
            ) from exc
        if not all(isinstance(item, CanonicalBar) for item in bars):
            raise ContractValidationError(
                facts={"field": "bars", "reason": "invalid_item"}
            )
        if not all(isinstance(item, DatasetKey) for item in source_datasets):
            raise ContractValidationError(
                facts={"field": "source_datasets", "reason": "invalid_item"}
            )
        if not source_datasets:
            raise ContractValidationError(
                facts={"field": "source_datasets", "reason": "empty"}
            )
        source_datasets = tuple(
            sorted(
                set(source_datasets),
                key=_dataset_key_sort_key,
            )
        )
        source_families = {
            _dataset_family_key(source) for source in source_datasets
        }
        if len(source_families) != 1:
            raise ContractValidationError(
                facts={
                    "field": "source_datasets",
                    "reason": "source_family_mismatch",
                }
            )
        data_type = _normalize_dataset_kind(self.data_type)
        if any(
            item.dataset_kind is not data_type for item in source_datasets
        ):
            raise ContractValidationError(
                facts={
                    "field": "data_type",
                    "reason": "source_dataset_kind_mismatch",
                }
            )
        if (
            data_type is DatasetKind.CONTINUOUS
            and len(source_datasets) != 1
        ):
            raise ContractValidationError(
                facts={
                    "field": "source_datasets",
                    "reason": "continuous_requires_one_series",
                }
            )
        manifest_digests = _normalize_manifest_digests(manifest_digests)
        if not all(
            isinstance(item, str) and bool(item.strip())
            for item in source_data_versions
        ):
            raise ContractValidationError(
                facts={"field": "source_data_versions", "reason": "invalid_item"}
            )
        source_data_versions = tuple(
            sorted({item.strip() for item in source_data_versions})
        )
        if (
            not isinstance(self.requested_window, tuple)
            or len(self.requested_window) != 2
        ):
            raise ContractValidationError(
                facts={"field": "window", "reason": "invalid_shape"}
            )
        start, end = _normalize_window(*self.requested_window)
        derived_frequency = self.derived_frequency
        if derived_frequency is not None:
            derived_frequency = _normalize_frequency(
                derived_frequency,
                field="derived_frequency",
            )
            if derived_frequency not in DERIVED_FREQUENCIES:
                raise ContractValidationError(
                    facts={
                        "field": "derived_frequency",
                        "value": derived_frequency.value,
                    }
                )
            if any(
                source.frequency is not BarFrequency.M1
                for source in source_datasets
            ):
                raise ContractValidationError(
                    facts={
                        "field": "source_datasets",
                        "reason": "derived_source_frequency_must_be_1m",
                    }
                )
        for previous, current in zip(bars, bars[1:], strict=False):
            if previous.bar_end >= current.bar_end:
                raise ContractValidationError(
                    facts={
                        "field": "bars",
                        "reason": "bar_end_not_strictly_increasing",
                    }
                )
        for bar in bars:
            if not start < bar.bar_end <= end:
                raise ContractValidationError(
                    facts={
                        "field": "bars",
                        "reason": "bar_outside_requested_window",
                        "bar_end": bar.bar_end.isoformat(),
                    }
                )
            if bar.dataset_kind is not data_type:
                raise ContractValidationError(
                    facts={
                        "field": "data_type",
                        "reason": "bar_dataset_kind_mismatch",
                        "bar_end": bar.bar_end.isoformat(),
                    }
                )
            matching_sources = tuple(
                source
                for source in source_datasets
                if _bar_matches_dataset_identity(bar, source)
            )
            if not matching_sources:
                raise ContractValidationError(
                    facts={
                        "field": "bars",
                        "reason": "source_dataset_identity_mismatch",
                        "bar_end": bar.bar_end.isoformat(),
                    }
                )
            if derived_frequency is not None:
                if bar.frequency is not derived_frequency:
                    raise ContractValidationError(
                        facts={
                            "field": "bars",
                            "reason": "derived_bar_frequency_mismatch",
                            "expected": derived_frequency.value,
                            "actual": bar.frequency.value,
                        }
                    )
                if not any(
                    source.frequency is BarFrequency.M1
                    for source in matching_sources
                ):
                    raise ContractValidationError(
                        facts={
                            "field": "source_datasets",
                            "reason": "derived_source_frequency_must_be_1m",
                        }
                    )
            else:
                if bar.frequency not in DIRECT_FREQUENCIES:
                    raise ContractValidationError(
                        facts={
                            "field": "bars",
                            "reason": "direct_bar_frequency_required",
                            "actual": bar.frequency.value,
                        }
                    )
                if not any(
                    source.frequency is bar.frequency
                    for source in matching_sources
                ):
                    raise ContractValidationError(
                        facts={
                            "field": "bars",
                            "reason": "direct_source_frequency_mismatch",
                            "bar_end": bar.bar_end.isoformat(),
                        }
                    )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "source_datasets", source_datasets)
        object.__setattr__(self, "manifest_digests", manifest_digests)
        object.__setattr__(self, "requested_window", (start, end))
        object.__setattr__(self, "data_type", data_type)
        object.__setattr__(self, "derived_frequency", derived_frequency)
        object.__setattr__(self, "source_data_versions", source_data_versions)


def _dataset_key_sort_key(key: DatasetKey) -> tuple[str, ...]:
    return (
        key.provider,
        key.dataset_kind.value,
        key.symbol,
        key.contract_or_series,
        key.frequency.value,
        key.adjustment,
        key.schema_version,
    )


def _dataset_family_key(key: DatasetKey) -> tuple[str, ...]:
    return (
        key.provider,
        key.dataset_kind.value,
        key.symbol,
        key.frequency.value,
        key.adjustment,
        key.schema_version,
    )


def _normalize_manifest_digests(values: tuple[object, ...]) -> tuple[str, ...]:
    if not values:
        raise ManifestMismatchError(
            facts={"reason": "manifest_digests_empty"}
        )
    if any(
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value.strip().lower()) is None
        for value in values
    ):
        raise ManifestMismatchError(
            facts={"reason": "invalid_manifest_digest"}
        )
    return tuple(sorted({value.strip().lower() for value in values}))


def _normalize_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ContractValidationError(
            facts={"field": "lineage", "reason": f"{field}_invalid"}
        )
    return value


def _bar_matches_dataset_identity(
    bar: CanonicalBar,
    source: DatasetKey,
) -> bool:
    return (
        bar.provider == source.provider
        and bar.dataset_kind is source.dataset_kind
        and bar.symbol == source.symbol
        and bar.contract_or_series == source.contract_or_series
        and bar.adjustment == source.adjustment
        and bar.schema_version == source.schema_version
    )


def _normalize_text(
    value: object,
    *,
    field: str,
    lower: bool = False,
    upper: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(
            facts={"field": field, "value_type": type(value).__name__}
        )
    normalized = value.strip()
    if lower:
        normalized = normalized.lower()
    if upper:
        normalized = normalized.upper()
    return normalized


def _normalize_dataset_kind(value: object) -> DatasetKind:
    try:
        return DatasetKind(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": "dataset_kind", "value": str(value)}
        ) from exc


def _normalize_frequency(value: object, *, field: str) -> BarFrequency:
    try:
        return BarFrequency(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": field, "value": str(value)}
        ) from exc


def _validate_dataset_identity(
    *,
    dataset_kind: DatasetKind,
    symbol: str,
    contract_or_series: str | None,
    allow_resolved_actual: bool = False,
) -> None:
    expected_series = f"{symbol.upper()}.MAIN"
    if dataset_kind is DatasetKind.CONTINUOUS:
        if contract_or_series is None or not contract_or_series.endswith(".MAIN"):
            reason = "continuous_series_required"
        elif contract_or_series != expected_series:
            reason = "continuous_series_symbol_mismatch"
        else:
            return
    else:
        if contract_or_series is None and allow_resolved_actual:
            return
        match = (
            _CONCRETE_CONTRACT_PATTERN.fullmatch(contract_or_series)
            if contract_or_series is not None
            else None
        )
        if match is None:
            reason = "concrete_contract_required"
        elif match.group(1) != symbol.upper():
            reason = "concrete_contract_symbol_mismatch"
        else:
            return
    raise ContractValidationError(
        facts={"field": "contract_or_series", "reason": reason}
    )


def _normalize_window(start: object, end: object) -> tuple[datetime, datetime]:
    if not _is_aware_datetime(start) or not _is_aware_datetime(end):
        raise ContractValidationError(
            facts={"field": "window", "reason": "timezone_required"}
        )
    normalized_start = start.astimezone(UTC)
    normalized_end = end.astimezone(UTC)
    if normalized_start >= normalized_end:
        raise ContractValidationError(
            facts={"field": "window", "reason": "start_must_precede_end"}
        )
    return normalized_start, normalized_end


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
