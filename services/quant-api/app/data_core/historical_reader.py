from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Callable, Sequence

import pyarrow.parquet as pq

from app.data_core.canonical_store import (
    CANONICAL_PARQUET_SCHEMA,
    _bars_from_table,
    _validate_stored_manifest_document,
)
from app.data_core.aggregation import AggregationSession
from app.data_core.catalog import CatalogError, HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    BarsResult,
    ContractValidationError,
    DataGapError,
    DatasetAmbiguousError,
    DatasetKind,
    DatasetKey,
    ManifestMismatchError,
)
from app.data_core.historical_sessions import build_provider_sessions
from app.data_core.historical_sync import plan_missing_windows


class CanonicalHistoricalReader:
    """Read direct canonical bars only after Catalog and filesystem checks."""

    def __init__(
        self,
        *,
        catalog: HistoricalCatalog,
        canonical_root: Path,
        session_provider: Callable[
            [str, datetime, datetime], Sequence[AggregationSession]
        ]
        | None = None,
    ) -> None:
        if not isinstance(catalog, HistoricalCatalog):
            raise TypeError("catalog must be a HistoricalCatalog")
        if not isinstance(canonical_root, Path) or not canonical_root.is_absolute():
            raise ValueError("canonical_root must be an absolute Path")
        self._catalog = catalog
        self._canonical_root = canonical_root.resolve()
        self._session_provider = session_provider

    def get_bars(self, query: BarQuery) -> BarsResult:
        if not isinstance(query, BarQuery):
            raise ContractValidationError(
                facts={"field": "query", "reason": "invalid"}
            )
        if query.contract_or_series is None and (
            query.dataset_kind is not DatasetKind.ACTUAL_DOMINANT
        ):
            raise ContractValidationError(
                facts={"field": "contract_or_series", "reason": "required"}
            )
        return self._get_direct_bars(query)

    def _get_direct_bars(self, query: BarQuery) -> BarsResult:
        datasets: tuple[DatasetKey, ...]
        expected_contract_by_day: dict[object, str] | None = None
        if (
            query.dataset_kind is DatasetKind.ACTUAL_DOMINANT
            and self._session_provider is not None
        ):
            expected_contract_by_day = self._resolve_actual_dominant_contracts(query)
        if query.contract_or_series is None:
            if expected_contract_by_day is None:
                raise DataGapError(facts={"reason": "mapping_session_provider_required"})
            datasets = tuple(
                DatasetKey(
                    provider="rqdata",
                    dataset_kind=query.dataset_kind,
                    symbol=query.symbol,
                    contract_or_series=contract,
                    frequency=query.frequency,
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                )
                for contract in sorted(set(expected_contract_by_day.values()))
            )
        else:
            datasets = (
                DatasetKey(
                    provider="rqdata",
                    dataset_kind=query.dataset_kind,
                    symbol=query.symbol,
                    contract_or_series=query.contract_or_series,
                    frequency=query.frequency,
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                ),
            )

        bars_by_identity: dict[tuple[object, ...], object] = {}
        manifest_digests: list[str] = []
        source_data_versions: list[str] = []
        for dataset in datasets:
            windows = self._mapping_valid_windows(
                query,
                dataset=dataset,
                mappings=expected_contract_by_day,
            )
            for window_start, window_end in windows:
                bars, digests, data_versions = self._read_direct_dataset(
                    dataset,
                    start=window_start,
                    end=window_end,
                )
                manifest_digests.extend(digests)
                source_data_versions.extend(data_versions)
                for bar in bars:
                    if (
                        expected_contract_by_day is not None
                        and expected_contract_by_day.get(bar.trading_day)
                        != bar.contract_or_series
                    ):
                        continue
                    existing = bars_by_identity.get(bar.identity)
                    if existing is not None:
                        raise DatasetAmbiguousError(
                            facts={
                                "reason": (
                                    "same_key_value_conflict"
                                    if existing != bar
                                    else "duplicate_primary_key"
                                )
                            }
                        )
                    bars_by_identity[bar.identity] = bar

        ordered_bars = tuple(sorted(bars_by_identity.values(), key=lambda bar: bar.bar_end))
        if not ordered_bars:
            raise DataGapError(facts={"reason": "canonical_bars_missing"})
        self._require_direct_coverage(
            query,
            datasets=datasets,
            bars=ordered_bars,
            mappings=expected_contract_by_day,
        )
        return BarsResult(
            bars=ordered_bars,
            source_datasets=datasets,
            manifest_digests=tuple(dict.fromkeys(manifest_digests)),
            requested_window=(query.start, query.end),
            data_type=query.dataset_kind,
            derived_frequency=None,
            source_data_versions=tuple(dict.fromkeys(source_data_versions)),
        )

    def _require_direct_coverage(
        self,
        query: BarQuery,
        *,
        datasets: Sequence[DatasetKey],
        bars: Sequence[object],
        mappings: dict[object, str] | None,
    ) -> None:
        if self._session_provider is not None:
            sessions = tuple(
                self._session_provider(query.symbol, query.start, query.end)
            )
            expected: set[datetime] = set()
            for dataset in datasets:
                dataset_sessions = sessions
                if mappings is not None:
                    dataset_sessions = tuple(
                        item
                        for item in sessions
                        if mappings.get(item.trading_day)
                        == dataset.contract_or_series
                    )
                expected.update(
                    bar_end
                    for item in build_provider_sessions(
                        dataset,
                        start=query.start,
                        end=query.end,
                        sessions=dataset_sessions,
                    )
                    for bar_end in item.expected_bar_ends
                )
            actual = {bar.bar_end for bar in bars}
            if not expected or actual != expected:
                raise DataGapError(
                    facts={
                        "reason": "canonical_bar_coverage_missing",
                        "expected_count": len(expected),
                        "actual_count": len(actual),
                    }
                )
            return
        covered_windows = tuple(
            (
                _as_utc(partition.coverage_start),
                _as_utc(partition.coverage_end),
            )
            for dataset in datasets
            for partition in self._catalog.list_effective_partitions(dataset)
        )
        missing = plan_missing_windows(
            dataset=datasets[0],
            start=query.start,
            end=query.end,
            covered_windows=covered_windows,
        )
        if missing:
            raise DataGapError(
                facts={
                    "reason": "catalog_coverage_missing",
                    "missing_window_count": len(missing),
                }
            )

    def _mapping_valid_windows(
        self,
        query: BarQuery,
        *,
        dataset: DatasetKey,
        mappings: dict[object, str] | None,
    ) -> tuple[tuple[datetime, datetime], ...]:
        if mappings is None or self._session_provider is None:
            return ((query.start, query.end),)
        sessions = tuple(
            item
            for item in self._session_provider(query.symbol, query.start, query.end)
            if mappings.get(item.trading_day) == dataset.contract_or_series
        )
        return tuple(
            (item.start, item.end)
            for item in build_provider_sessions(
                dataset,
                start=query.start,
                end=query.end,
                sessions=sessions,
            )
        )

    def _resolve_actual_dominant_contracts(
        self,
        query: BarQuery,
    ) -> dict[object, str]:
        if self._session_provider is None:
            raise DataGapError(facts={"reason": "mapping_session_provider_required"})
        sessions = tuple(self._session_provider(query.symbol, query.start, query.end))
        trading_days = sorted(
            {
                session.trading_day
                for session in sessions
                if _intersects(session.start, session.end, query.start, query.end)
            }
        )
        if query.frequency is BarFrequency.W1:
            last_day_by_week: dict[tuple[int, int], object] = {}
            for trading_day in trading_days:
                iso = trading_day.isocalendar()
                last_day_by_week[(iso.year, iso.week)] = trading_day
            trading_days = list(last_day_by_week.values())
        if not trading_days:
            raise DataGapError(facts={"reason": "mapping_session_coverage_missing"})
        mappings: dict[object, str] = {}
        for trading_day in trading_days:
            try:
                mapping = self._catalog.get_main_contract_mapping(
                    instrument_symbol=query.symbol,
                    trade_date=trading_day,
                )
            except CatalogError as exc:
                raise DataGapError(
                    facts={
                        "reason": "main_contract_mapping_missing",
                        "trading_day": trading_day.isoformat(),
                    }
                ) from exc
            except ValueError as exc:
                raise DatasetAmbiguousError(
                    facts={
                        "reason": "main_contract_mapping_ambiguous",
                        "trading_day": trading_day.isoformat(),
                    }
                ) from exc
            mappings[trading_day] = mapping.actual_contract
        return mappings

    def _read_direct_dataset(
        self,
        dataset: DatasetKey,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[tuple[object, ...], tuple[str, ...], tuple[str, ...]]:
        self._raise_if_gap_intersects(dataset, start, end)
        partitions = tuple(
            partition
            for partition in self._catalog.list_effective_partitions(dataset)
            if _intersects(
                _as_utc(partition.coverage_start),
                _as_utc(partition.coverage_end),
                start,
                end,
            )
        )
        if not partitions:
            raise DataGapError(facts={"reason": "catalog_coverage_missing"})
        bars: list[object] = []
        manifest_digests: list[str] = []
        source_data_versions: list[str] = []
        for partition in partitions:
            manifest_digests.append(str(partition.manifest_digest))
            partition_bars, data_version = self._read_partition(dataset, partition)
            source_data_versions.append(data_version)
            bars.extend(
                bar
                for bar in partition_bars
                if start < bar.bar_end <= end
            )
        return (
            tuple(bars),
            tuple(manifest_digests),
            tuple(source_data_versions),
        )

    def _raise_if_gap_intersects(
        self,
        dataset: DatasetKey,
        start: datetime,
        end: datetime,
    ) -> None:
        for gap in self._catalog.list_gaps(dataset):
            if _intersects(
                _as_utc(gap.gap_start),
                _as_utc(gap.gap_end),
                start,
                end,
            ):
                raise DataGapError(facts={"reason": "catalog_gap"})

    def _read_partition(
        self,
        dataset: DatasetKey,
        partition: object,
    ) -> tuple[tuple[object, ...], str]:
        manifest_uri = _partition_value(partition, "manifest_uri")
        file_uri = _partition_value(partition, "file_uri")
        manifest_path = _safe_child(self._canonical_root, manifest_uri)
        file_path = _safe_child(self._canonical_root, file_uri)
        document = _read_manifest(manifest_path)
        partition_payload = document.get("partition")
        if not isinstance(partition_payload, dict):
            raise ManifestMismatchError(facts={"reason": "manifest_partition_invalid"})
        data_version = partition_payload.get("data_version")
        if not isinstance(data_version, str):
            raise ManifestMismatchError(facts={"reason": "manifest_data_version_invalid"})
        try:
            _validate_stored_manifest_document(
                document,
                dataset=dataset,
                coverage_start=_as_utc(_partition_value(partition, "coverage_start")),
                coverage_end=_as_utc(_partition_value(partition, "coverage_end")),
                row_count=int(_partition_value(partition, "row_count")),
                data_version=data_version,
                manifest_version=str(_partition_value(partition, "manifest_version")),
                file_uri=file_uri,
                manifest_uri=manifest_uri,
                file_checksum=str(_partition_value(partition, "checksum")),
                canonical_logical_fingerprint=str(
                    document.get("canonical_logical_fingerprint", "")
                ),
                overlap_reason=_partition_value(partition, "overlap_reason"),
            )
        except (TypeError, ValueError) as exc:
            raise ManifestMismatchError(
                facts={"reason": "manifest_content_mismatch"}
            ) from exc
        if document.get("manifest_digest") != _partition_value(
            partition, "manifest_digest"
        ):
            raise ManifestMismatchError(facts={"reason": "manifest_digest_mismatch"})
        if _sha256(file_path) != _partition_value(partition, "checksum"):
            raise ManifestMismatchError(facts={"reason": "file_checksum_mismatch"})
        expected_row_count = int(_partition_value(partition, "row_count"))
        try:
            parquet = pq.ParquetFile(file_path)
        except Exception as exc:
            raise ManifestMismatchError(facts={"reason": "parquet_unreadable"}) from exc
        if int(parquet.metadata.num_rows) != expected_row_count:
            raise ManifestMismatchError(facts={"reason": "parquet_row_count_mismatch"})
        try:
            table = parquet.read()
        except Exception as exc:
            raise ManifestMismatchError(facts={"reason": "parquet_unreadable"}) from exc
        if table.schema != CANONICAL_PARQUET_SCHEMA:
            raise ManifestMismatchError(facts={"reason": "parquet_schema_mismatch"})
        if table.num_rows != expected_row_count:
            raise ManifestMismatchError(facts={"reason": "parquet_row_count_mismatch"})
        bars = _bars_from_table(table)
        if any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:], strict=False)
        ):
            raise ManifestMismatchError(
                facts={"reason": "parquet_primary_key_order_invalid"}
            )
        return bars, data_version


def _partition_value(partition: object, field: str) -> object:
    try:
        return getattr(partition, field)
    except AttributeError as exc:
        raise ManifestMismatchError(
            facts={"reason": "catalog_partition_invalid"}
        ) from exc


def _safe_child(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or not relative_path or "\\" in relative_path:
        raise ManifestMismatchError(facts={"reason": "canonical_path_invalid"})
    resolved = (root / candidate).resolve()
    if root != resolved and root not in resolved.parents:
        raise ManifestMismatchError(facts={"reason": "canonical_path_escape"})
    return resolved


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestMismatchError(facts={"reason": "manifest_unreadable"}) from exc
    if not isinstance(parsed, dict):
        raise ManifestMismatchError(facts={"reason": "manifest_invalid"})
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ManifestMismatchError(facts={"reason": "file_unreadable"}) from exc
    return digest.hexdigest()


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ManifestMismatchError(facts={"reason": "catalog_datetime_invalid"})
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _intersects(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return left_start < right_end and right_start < left_end
