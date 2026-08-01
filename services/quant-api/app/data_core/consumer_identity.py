from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Mapping

from app.data_core.contracts import (
    DERIVED_FREQUENCIES,
    BarFrequency,
    BarQuery,
    BarsResult,
    ContractValidationError,
    DatasetKey,
)


CANONICAL_CONSUMER_INPUT_SCHEMA_VERSION = "canonical_consumer_input_v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "request",
        "source_datasets",
        "manifest_digests",
        "source_data_versions",
        "derived_frequency",
        "strategy_input_version",
        "digest",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "dataset_kind",
        "symbol",
        "contract_or_series",
        "frequency",
        "start",
        "end",
        "strict",
    }
)
_DATASET_FIELDS = frozenset(
    {
        "provider",
        "dataset_kind",
        "symbol",
        "contract_or_series",
        "frequency",
        "adjustment",
        "schema_version",
    }
)


@dataclass(frozen=True, slots=True)
class CanonicalConsumerInput:
    """Immutable, versioned input identity for a canonical data consumer."""

    request: BarQuery
    source_datasets: tuple[DatasetKey, ...]
    manifest_digests: tuple[str, ...]
    source_data_versions: tuple[str, ...]
    derived_frequency: BarFrequency | None
    strategy_input_version: str
    digest: str
    schema_version: str = CANONICAL_CONSUMER_INPUT_SCHEMA_VERSION

    def to_snapshot(self) -> dict[str, object]:
        """Return the JSON-safe representation persisted by consumer paths."""
        payload = _snapshot_payload(
            request=self.request,
            source_datasets=self.source_datasets,
            manifest_digests=self.manifest_digests,
            source_data_versions=self.source_data_versions,
            derived_frequency=self.derived_frequency,
            strategy_input_version=self.strategy_input_version,
        )
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, object],
    ) -> CanonicalConsumerInput:
        """Strictly validate a stored identity before any consumer re-read."""
        _require_exact_fields(snapshot, _TOP_LEVEL_FIELDS, field="snapshot")
        schema_version = snapshot["schema_version"]
        if schema_version != CANONICAL_CONSUMER_INPUT_SCHEMA_VERSION:
            raise ContractValidationError(
                facts={"field": "schema_version", "reason": "unsupported"}
            )

        request = _parse_request(snapshot["request"])
        source_datasets = _parse_source_datasets(snapshot["source_datasets"])
        manifest_digests = _parse_hashes(
            snapshot["manifest_digests"], field="manifest_digests", allow_empty=False
        )
        source_data_versions = _parse_versions(snapshot["source_data_versions"])
        derived_frequency = _parse_derived_frequency(snapshot["derived_frequency"])
        strategy_input_version = _parse_strategy_input_version(
            snapshot["strategy_input_version"]
        )
        _validate_request_result_identity(
            request,
            source_datasets=source_datasets,
            derived_frequency=derived_frequency,
        )

        digest = snapshot["digest"]
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise ContractValidationError(
                facts={"field": "digest", "reason": "invalid_sha256"}
            )
        payload = _snapshot_payload(
            request=request,
            source_datasets=source_datasets,
            manifest_digests=manifest_digests,
            source_data_versions=source_data_versions,
            derived_frequency=derived_frequency,
            strategy_input_version=strategy_input_version,
        )
        if digest != _digest(payload):
            raise ContractValidationError(
                facts={"field": "digest", "reason": "mismatch"}
            )
        return cls(
            request=request,
            source_datasets=source_datasets,
            manifest_digests=manifest_digests,
            source_data_versions=source_data_versions,
            derived_frequency=derived_frequency,
            strategy_input_version=strategy_input_version,
            digest=digest,
        )


def build_canonical_consumer_input(
    query: BarQuery,
    result: BarsResult,
    *,
    strategy_input_version: str,
) -> CanonicalConsumerInput:
    """Freeze a successful canonical read into its stable consumer identity."""
    if not isinstance(query, BarQuery) or not isinstance(result, BarsResult):
        raise ContractValidationError(
            facts={"field": "query_or_result", "reason": "invalid_type"}
        )
    if result.requested_window != (query.start, query.end):
        raise ContractValidationError(
            facts={"field": "requested_window", "reason": "query_result_mismatch"}
        )
    if result.data_type is not query.dataset_kind:
        raise ContractValidationError(
            facts={"field": "dataset_kind", "reason": "query_result_mismatch"}
        )
    _validate_request_result_identity(
        query,
        source_datasets=result.source_datasets,
        derived_frequency=result.derived_frequency,
    )
    normalized_version = _parse_strategy_input_version(strategy_input_version)
    payload = _snapshot_payload(
        request=query,
        source_datasets=result.source_datasets,
        manifest_digests=result.manifest_digests,
        source_data_versions=result.source_data_versions,
        derived_frequency=result.derived_frequency,
        strategy_input_version=normalized_version,
    )
    return CanonicalConsumerInput(
        request=query,
        source_datasets=result.source_datasets,
        manifest_digests=result.manifest_digests,
        source_data_versions=result.source_data_versions,
        derived_frequency=result.derived_frequency,
        strategy_input_version=normalized_version,
        digest=_digest(payload),
    )


def reconstruct_bar_query(snapshot: Mapping[str, object]) -> BarQuery:
    """Validate a persisted identity and return its exact canonical re-read."""
    return CanonicalConsumerInput.from_snapshot(snapshot).request


def _snapshot_payload(
    *,
    request: BarQuery,
    source_datasets: tuple[DatasetKey, ...],
    manifest_digests: tuple[str, ...],
    source_data_versions: tuple[str, ...],
    derived_frequency: BarFrequency | None,
    strategy_input_version: str,
) -> dict[str, object]:
    return {
        "schema_version": CANONICAL_CONSUMER_INPUT_SCHEMA_VERSION,
        "request": {
            "dataset_kind": request.dataset_kind.value,
            "symbol": request.symbol,
            "contract_or_series": request.contract_or_series,
            "frequency": request.frequency.value,
            "start": _serialize_datetime(request.start),
            "end": _serialize_datetime(request.end),
            "strict": request.strict,
        },
        "source_datasets": [
            _dataset_snapshot(item) for item in source_datasets
        ],
        "manifest_digests": list(manifest_digests),
        "source_data_versions": list(source_data_versions),
        "derived_frequency": (
            derived_frequency.value if derived_frequency is not None else None
        ),
        "strategy_input_version": strategy_input_version,
    }


def _dataset_snapshot(dataset: DatasetKey) -> dict[str, str]:
    return {
        "provider": dataset.provider,
        "dataset_kind": dataset.dataset_kind.value,
        "symbol": dataset.symbol,
        "contract_or_series": dataset.contract_or_series,
        "frequency": dataset.frequency.value,
        "adjustment": dataset.adjustment,
        "schema_version": dataset.schema_version,
    }


def _parse_request(value: object) -> BarQuery:
    if not isinstance(value, Mapping):
        raise ContractValidationError(facts={"field": "request", "reason": "invalid"})
    _require_exact_fields(value, _REQUEST_FIELDS, field="request")
    try:
        query = BarQuery(
            dataset_kind=value["dataset_kind"],
            symbol=value["symbol"],
            contract_or_series=value["contract_or_series"],
            frequency=value["frequency"],
            start=_parse_datetime(value["start"], field="request.start"),
            end=_parse_datetime(value["end"], field="request.end"),
            strict=value["strict"],
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": "request", "reason": "invalid"}
        ) from exc
    if _snapshot_payload_for_request(query) != dict(value):
        raise ContractValidationError(
            facts={"field": "request", "reason": "not_canonical"}
        )
    return query


def _snapshot_payload_for_request(query: BarQuery) -> dict[str, object]:
    return {
        "dataset_kind": query.dataset_kind.value,
        "symbol": query.symbol,
        "contract_or_series": query.contract_or_series,
        "frequency": query.frequency.value,
        "start": _serialize_datetime(query.start),
        "end": _serialize_datetime(query.end),
        "strict": query.strict,
    }


def _parse_source_datasets(value: object) -> tuple[DatasetKey, ...]:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(
            facts={"field": "source_datasets", "reason": "invalid"}
        )
    datasets: list[DatasetKey] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ContractValidationError(
                facts={"field": "source_datasets", "reason": "invalid_item"}
            )
        _require_exact_fields(item, _DATASET_FIELDS, field="source_datasets")
        try:
            dataset = DatasetKey(**dict(item))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                facts={"field": "source_datasets", "reason": "invalid_item"}
            ) from exc
        if _dataset_snapshot(dataset) != dict(item):
            raise ContractValidationError(
                facts={"field": "source_datasets", "reason": "not_canonical"}
            )
        datasets.append(dataset)
    normalized = tuple(sorted(set(datasets), key=_dataset_sort_key))
    if tuple(datasets) != normalized:
        raise ContractValidationError(
            facts={"field": "source_datasets", "reason": "not_canonical"}
        )
    return normalized


def _parse_hashes(
    value: object,
    *,
    field: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ContractValidationError(facts={"field": field, "reason": "invalid"})
    if any(
        not isinstance(item, str) or _SHA256_PATTERN.fullmatch(item) is None
        for item in value
    ):
        raise ContractValidationError(
            facts={"field": field, "reason": "invalid_sha256"}
        )
    normalized = tuple(sorted(set(value)))
    if tuple(value) != normalized:
        raise ContractValidationError(
            facts={"field": field, "reason": "not_canonical"}
        )
    return normalized


def _parse_versions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ):
        raise ContractValidationError(
            facts={"field": "source_data_versions", "reason": "invalid"}
        )
    normalized = tuple(sorted(set(value)))
    if tuple(value) != normalized:
        raise ContractValidationError(
            facts={"field": "source_data_versions", "reason": "not_canonical"}
        )
    return normalized


def _parse_derived_frequency(value: object) -> BarFrequency | None:
    if value is None:
        return None
    try:
        frequency = BarFrequency(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": "derived_frequency", "reason": "invalid"}
        ) from exc
    if frequency not in DERIVED_FREQUENCIES:
        raise ContractValidationError(
            facts={"field": "derived_frequency", "reason": "invalid"}
        )
    return frequency


def _parse_strategy_input_version(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(
            facts={"field": "strategy_input_version", "reason": "invalid"}
        )
    return value.strip()


def _parse_datetime(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ContractValidationError(facts={"field": field, "reason": "invalid"})
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractValidationError(
            facts={"field": field, "reason": "invalid"}
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(facts={"field": field, "reason": "timezone_required"})
    normalized = parsed.astimezone(UTC)
    if value != _serialize_datetime(normalized):
        raise ContractValidationError(
            facts={"field": field, "reason": "not_canonical"}
        )
    return normalized


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _validate_request_result_identity(
    query: BarQuery,
    *,
    source_datasets: tuple[DatasetKey, ...],
    derived_frequency: BarFrequency | None,
) -> None:
    if not source_datasets or any(
        source.dataset_kind is not query.dataset_kind or source.symbol != query.symbol
        for source in source_datasets
    ):
        raise ContractValidationError(
            facts={"field": "source_datasets", "reason": "query_result_mismatch"}
        )
    if query.contract_or_series is not None and any(
        source.contract_or_series != query.contract_or_series
        for source in source_datasets
    ):
        raise ContractValidationError(
            facts={"field": "source_datasets", "reason": "query_result_mismatch"}
        )
    if derived_frequency is not None:
        valid_frequency = (
            query.frequency is derived_frequency
            and all(source.frequency is BarFrequency.M1 for source in source_datasets)
        )
    else:
        valid_frequency = all(
            source.frequency is query.frequency for source in source_datasets
        )
    if not valid_frequency:
        raise ContractValidationError(
            facts={"field": "frequency", "reason": "query_result_mismatch"}
        )


def _dataset_sort_key(dataset: DatasetKey) -> tuple[str, ...]:
    return (
        dataset.provider,
        dataset.dataset_kind.value,
        dataset.symbol,
        dataset.contract_or_series,
        dataset.frequency.value,
        dataset.adjustment,
        dataset.schema_version,
    )


def _require_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractValidationError(
            facts={
                "field": field,
                "reason": "fields_mismatch",
                "missing": sorted(expected - actual),
                "extra": sorted(actual - expected),
            }
        )


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
