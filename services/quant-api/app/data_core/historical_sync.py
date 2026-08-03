from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Callable, Iterable, Protocol, Sequence, TypeVar

from app.data_core.canonical_store import CanonicalStoreError, PublishExpectation
from app.data_core.catalog import CatalogError, GapWindow, PartitionManifest
from app.data_core.contracts import (
    ContractValidationError,
    DataCoreError,
    DataGapError,
    DatasetKey,
)
from app.data_core.rqdata_adapter import (
    MainMapRequest,
    MainMapRow,
    ProviderBarBatch,
    ProviderBarRequest,
    TradingSessionCoverage,
)
from app.services.jm_session_contract import JM_SESSION_MANIFEST_VERSION


CoverageWindow = tuple[datetime, datetime]
Result = TypeVar("Result")


class _Partition(Protocol):
    coverage_start: datetime
    coverage_end: datetime


class _Catalog(Protocol):
    def list_partitions(self, key: DatasetKey) -> Sequence[_Partition]: ...

    def record_gap(self, key: DatasetKey, gap: GapWindow) -> object: ...

    def clear_gaps_covered_by(
        self,
        key: DatasetKey,
        *,
        coverage_start: datetime,
        coverage_end: datetime,
    ) -> int: ...


class _Adapter(Protocol):
    def fetch_bars(self, request: ProviderBarRequest) -> object: ...


class _CanonicalStore(Protocol):
    def stage(self, batch: object) -> object: ...

    def publish(
        self,
        staged: object,
        expected: PublishExpectation,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class SyncResult:
    dry_run: bool
    planned_windows: tuple[CoverageWindow, ...]
    published_windows: tuple[CoverageWindow, ...]
    gap_windows: tuple[CoverageWindow, ...]


@dataclass(frozen=True, slots=True)
class MappingSyncResult:
    dry_run: bool
    rows: tuple[MainMapRow, ...]


class SyncRetryExhaustedError(DataCoreError):
    error_code = "HISTORICAL_SYNC_RETRY_EXHAUSTED"


class CanonicalBatchPublisher:
    """Adapt the Task 03 writer to a sync-safe publish callable."""

    def __init__(
        self,
        store: _CanonicalStore,
        *,
        manifest_version: str = "canonical-manifest-v1",
        overlap_reason: str | None = None,
        data_version_suffix: str | None = None,
    ) -> None:
        if not isinstance(manifest_version, str) or not manifest_version.strip():
            raise ContractValidationError(
                facts={"field": "manifest_version", "reason": "invalid"}
            )
        self._store = store
        self._manifest_version = manifest_version.strip()
        self._overlap_reason = overlap_reason
        if data_version_suffix is not None and (
            not isinstance(data_version_suffix, str)
            or not data_version_suffix.strip()
            or data_version_suffix != data_version_suffix.strip()
        ):
            raise ContractValidationError(
                facts={"field": "data_version_suffix", "reason": "invalid"}
            )
        self._data_version_suffix = data_version_suffix

    def __call__(self, batch: object) -> PartitionManifest:
        if self._data_version_suffix is not None:
            if not isinstance(batch, ProviderBarBatch):
                raise ContractValidationError(
                    facts={"field": "batch", "reason": "invalid"}
                )
            suffix = f"-{self._data_version_suffix}"
            batch = replace(
                batch,
                data_version=(
                    batch.data_version
                    if batch.data_version.endswith(suffix)
                    else f"{batch.data_version}{suffix}"
                ),
            )
        staged = self._store.stage(batch)
        source = getattr(staged, "source", None)
        if source is None:
            raise ContractValidationError(
                facts={"field": "staged", "reason": "source_missing"}
            )
        expectation = PublishExpectation(
            dataset=source.dataset,
            coverage_start=source.coverage_start,
            coverage_end=source.coverage_end,
            row_count=source.row_count,
            data_version=source.data_version,
            manifest_version=self._manifest_version,
            file_checksum=getattr(staged, "file_checksum", None),
            canonical_logical_fingerprint=getattr(
                staged,
                "canonical_logical_fingerprint",
                None,
            ),
            overlap_reason=self._overlap_reason,
        )
        published = self._store.publish(staged, expectation)
        manifest = getattr(published, "partition_manifest", None)
        if not isinstance(manifest, PartitionManifest):
            raise ContractValidationError(
                facts={"field": "published", "reason": "manifest_missing"}
            )
        return manifest


class HistoricalSynchronizer:
    """Plan and execute bounded historical syncs against Catalog coverage."""

    def __init__(
        self,
        *,
        catalog: _Catalog,
        adapter: _Adapter,
        session_provider: Callable[
            [DatasetKey, datetime, datetime],
            Sequence[TradingSessionCoverage],
        ],
        publish_batch: Callable[[object], PartitionManifest],
        replace_batch: Callable[[object], PartitionManifest] | None = None,
    ) -> None:
        self._catalog = catalog
        self._adapter = adapter
        self._session_provider = session_provider
        self._publish_batch = publish_batch
        self._replace_batch = replace_batch

    def sync(
        self,
        *,
        dataset: DatasetKey,
        start: datetime,
        end: datetime,
        dry_run: bool = False,
        replace_existing: bool = False,
    ) -> SyncResult:
        query_start, query_end = _normalize_window(start, end)
        if type(dry_run) is not bool:
            raise ContractValidationError(
                facts={"field": "dry_run", "reason": "invalid"}
            )
        if type(replace_existing) is not bool:
            raise ContractValidationError(
                facts={"field": "replace_existing", "reason": "invalid"}
            )
        if replace_existing and not callable(self._replace_batch):
            raise ContractValidationError(
                facts={"field": "replace_batch", "reason": "missing"}
            )
        partitions = tuple(self._catalog.list_partitions(dataset))
        covered = tuple(
            (partition.coverage_start, partition.coverage_end)
            for partition in partitions
        )
        replacement_covered = tuple(
            (partition.coverage_start, partition.coverage_end)
            for partition in partitions
            if getattr(partition, "overlap_reason", None)
            == "version_replacement"
            and getattr(partition, "manifest_version", None)
            == JM_SESSION_MANIFEST_VERSION
        )
        planned = plan_missing_windows(
            dataset=dataset,
            start=query_start,
            end=query_end,
            covered_windows=(replacement_covered if replace_existing else covered),
        )
        if dry_run:
            return SyncResult(
                dry_run=True,
                planned_windows=planned,
                published_windows=(),
                gap_windows=(),
            )

        published_windows: list[CoverageWindow] = []
        gap_windows: list[CoverageWindow] = []
        publish_batch = (
            self._replace_batch if replace_existing else self._publish_batch
        )
        if not callable(publish_batch):
            raise ContractValidationError(
                facts={"field": "publish_batch", "reason": "missing"}
            )
        for window_start, window_end in planned:
            sessions = tuple(
                self._session_provider(dataset, window_start, window_end)
            )
            request = ProviderBarRequest(
                dataset=dataset,
                start=window_start,
                end=window_end,
                sessions=sessions,
            )
            try:
                manifest = execute_with_retries(
                    lambda: publish_batch(self._adapter.fetch_bars(request))
                )
            except SyncRetryExhaustedError as exc:
                self._catalog.record_gap(
                    dataset,
                    GapWindow(
                        gap_start=window_start,
                        gap_end=window_end,
                        reason_code="historical_sync_retry_exhausted",
                        details=dict(exc.facts),
                    ),
                )
                gap_windows.append((window_start, window_end))
                continue
            self._catalog.clear_gaps_covered_by(
                dataset,
                coverage_start=manifest.coverage_start,
                coverage_end=manifest.coverage_end,
            )
            published_windows.append(
                (manifest.coverage_start, manifest.coverage_end)
            )
        return SyncResult(
            dry_run=False,
            planned_windows=planned,
            published_windows=tuple(published_windows),
            gap_windows=tuple(gap_windows),
        )

    def sync_rank1_mapping(
        self,
        *,
        symbol: str,
        start_day: date,
        end_day: date,
        expected_trading_days: Sequence[date],
        allowed_contracts: Sequence[str] | None = None,
        dry_run: bool = False,
    ) -> MappingSyncResult:
        request = MainMapRequest(
            symbol=symbol,
            start_day=start_day,
            end_day=end_day,
        )
        if type(dry_run) is not bool:
            raise ContractValidationError(
                facts={"field": "dry_run", "reason": "invalid"}
            )
        expected_days = tuple(sorted(set(expected_trading_days)))
        if (
            not expected_days
            or any(
                not isinstance(item, date) or isinstance(item, datetime)
                for item in expected_days
            )
            or expected_days[0] < start_day
            or expected_days[-1] > end_day
        ):
            raise ContractValidationError(
                facts={"field": "expected_trading_days", "reason": "invalid"}
            )
        allowed = None
        if allowed_contracts is not None:
            try:
                raw_allowed = tuple(allowed_contracts)
            except TypeError as exc:
                raise ContractValidationError(
                    facts={"field": "allowed_contracts", "reason": "not_iterable"}
                ) from exc
            allowed = {
                item.strip().upper()
                for item in raw_allowed
                if isinstance(item, str) and item.strip()
            }
            if not allowed or len(allowed) != len(raw_allowed):
                raise ContractValidationError(
                    facts={"field": "allowed_contracts", "reason": "invalid"}
                )
        if dry_run:
            return MappingSyncResult(dry_run=True, rows=())
        fetch = getattr(self._adapter, "fetch_rank1_map", None)
        register = getattr(self._catalog, "register_main_contract_mapping", None)
        if not callable(fetch) or not callable(register):
            raise ContractValidationError(
                facts={"field": "mapping_sync", "reason": "unsupported"}
            )
        try:
            rows = tuple(fetch(request))
        except TypeError as exc:
            raise ContractValidationError(
                facts={"field": "mapping_rows", "reason": "not_iterable"}
            ) from exc
        if any(
            not isinstance(row, MainMapRow)
            or row.symbol != request.symbol
            or not request.start_day <= row.trading_day <= request.end_day
            or row.trading_day not in expected_days
            or (allowed is not None and row.actual_contract not in allowed)
            for row in rows
        ):
            raise ContractValidationError(
                facts={"field": "mapping_rows", "reason": "outside_approved_scope"}
            )
        received_days = {row.trading_day for row in rows}
        missing_days = tuple(item for item in expected_days if item not in received_days)
        if missing_days:
            raise DataGapError(
                facts={
                    "reason": "main_contract_mapping_missing",
                    "trading_days": tuple(item.isoformat() for item in missing_days),
                }
            )
        for row in rows:
            register(row)
        return MappingSyncResult(dry_run=False, rows=rows)


def execute_with_retries(
    operation: Callable[[], Result],
    *,
    max_retries: int = 3,
) -> Result:
    """Run one precise provider operation with a bounded retry budget."""
    if not callable(operation):
        raise ContractValidationError(
            facts={"field": "operation", "reason": "not_callable"}
        )
    if (
        type(max_retries) is not int
        or max_retries < 0
    ):
        raise ContractValidationError(
            facts={"field": "max_retries", "reason": "invalid"}
        )

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except (CatalogError, CanonicalStoreError, ContractValidationError):
            raise
        except (TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt == max_retries:
                break
    raise SyncRetryExhaustedError(
        facts={
            "attempt_count": max_retries + 1,
            "last_error_type": type(last_error).__name__,
            "last_error_code": (
                "provider_timeout"
                if isinstance(last_error, TimeoutError)
                else "provider_connection_error"
            ),
        }
    ) from last_error


def plan_missing_windows(
    *,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
    covered_windows: Iterable[CoverageWindow],
) -> tuple[CoverageWindow, ...]:
    """Return the exact uncovered sub-windows of a canonical query.

    Windows use the data-core ``(start, end]`` convention.  Their endpoints
    can therefore be used directly for a provider request and Catalog gap.
    """
    if not isinstance(dataset, DatasetKey):
        raise ContractValidationError(
            facts={"field": "dataset", "reason": "invalid"}
        )
    query_start, query_end = _normalize_window(start, end)
    normalized = _normalize_and_merge_windows(
        covered_windows,
        query_start=query_start,
        query_end=query_end,
    )

    cursor = query_start
    missing: list[CoverageWindow] = []
    for covered_start, covered_end in normalized:
        if cursor < covered_start:
            missing.append((cursor, covered_start))
        if covered_end > cursor:
            cursor = covered_end
    if cursor < query_end:
        missing.append((cursor, query_end))
    return tuple(missing)


def _normalize_and_merge_windows(
    windows: Iterable[CoverageWindow],
    *,
    query_start: datetime,
    query_end: datetime,
) -> tuple[CoverageWindow, ...]:
    try:
        raw_windows = tuple(windows)
    except TypeError as exc:
        raise ContractValidationError(
            facts={"field": "covered_windows", "reason": "not_iterable"}
        ) from exc

    clipped: list[CoverageWindow] = []
    for raw_window in raw_windows:
        if not isinstance(raw_window, tuple) or len(raw_window) != 2:
            raise ContractValidationError(
                facts={"field": "covered_windows", "reason": "invalid"}
            )
        start, end = _normalize_window(*raw_window)
        clipped_start = max(start, query_start)
        clipped_end = min(end, query_end)
        if clipped_start < clipped_end:
            clipped.append((clipped_start, clipped_end))

    merged: list[CoverageWindow] = []
    for start, end in sorted(clipped):
        if not merged or merged[-1][1] < start:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return tuple(merged)


def _normalize_window(start: object, end: object) -> CoverageWindow:
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
    ):
        raise ContractValidationError(
            facts={"field": "window", "reason": "timezone_required"}
        )
    normalized_start = start.astimezone(UTC)
    normalized_end = end.astimezone(UTC)
    if normalized_start >= normalized_end:
        raise ContractValidationError(
            facts={"field": "window", "reason": "invalid"}
        )
    return normalized_start, normalized_end
