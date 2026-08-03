"""Task 07 adapters for immutable legacy RQData Parquet sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.bar_schema import CanonicalBar
from app.data_core.aggregation import AggregationSession, aggregate_bars
from app.data_core.canonical_store import (
    CANONICAL_MANIFEST_FORMAT_V2,
    CANONICAL_PARQUET_SCHEMA,
    CanonicalStore,
    PublishExpectation,
    canonical_json_digest,
)
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    DERIVED_FREQUENCIES,
    BarFrequency,
    BarsResult,
    DataCoreError,
    DatasetKey,
    DatasetKind,
    DatasetOrigin,
    ManifestLineage,
)
from app.data_core.quality import validate_provider_batch
from app.data_core.historical_sessions import build_provider_sessions, product_sessions
from app.data_core.rqdata_adapter import (
    ProviderBarBatch,
    ProviderBarRequest,
    TradingSessionCoverage,
)
from app.models.data_center import MainContractMap


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_VALUE_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "open_interest",
)
TASK07_AGGREGATE_MANIFEST_VERSION = "task07-aggregate-migration-v1"
TASK07_DIRECT_REPAIR_MANIFEST_VERSION = "task07-direct-repair-v1"


class Task07MigrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Task07CorrectionEvidence:
    source_checksum: str
    source_row_count: int
    corrected_row_count: int
    corrected_trading_day_count: int
    original_trading_day_digest: str
    corrected_trading_day_digest: str
    main_map_digest: str | None


@dataclass(frozen=True, slots=True)
class Task07AggregateEvidence:
    source_checksum: str
    source_row_count: int
    target_frequency: str
    source_frequency: str
    quality_evidence_digest: str
    trading_day_digest: str
    main_map_digest: str | None
    schema_conversion_only: bool
    session_completeness_validated: bool


@dataclass(frozen=True, slots=True)
class PreparedLegacyBatch:
    batch: ProviderBarBatch
    evidence: Task07CorrectionEvidence | Task07AggregateEvidence
    lineage: ManifestLineage | None = None


@dataclass(frozen=True, slots=True)
class Task07RepairTarget:
    operation: str
    dataset: DatasetKey
    start: datetime
    end: datetime
    source_action_ids: tuple[int, ...]
    source_action_digests: tuple[str, ...]
    target_digest: str


def build_task07_repair_targets(
    plan: Mapping[str, Any],
    batch: Mapping[str, Any],
) -> tuple[Task07RepairTarget, ...]:
    operation = batch.get("operation")
    if operation not in {"rqdata_redownload", "canonical_1m_reaggregate"}:
        raise Task07MigrationError("TASK07_REPAIR_OPERATION_INVALID")
    action_by_id: dict[int, Mapping[str, Any]] = {}
    for action in plan.get("repair_actions", []):
        if not isinstance(action, Mapping):
            raise Task07MigrationError("TASK07_REPAIR_ACTION_INVALID")
        try:
            identifier = int(action["market_data_file_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Task07MigrationError("TASK07_REPAIR_ACTION_INVALID") from exc
        if identifier in action_by_id:
            raise Task07MigrationError("TASK07_REPAIR_ACTION_INVALID")
        action_by_id[identifier] = action
    action_ids = batch.get("repair_action_ids")
    action_digests = batch.get("repair_action_digests")
    if (
        not isinstance(action_ids, list)
        or not isinstance(action_digests, list)
        or not action_ids
        or len(action_ids) != len(action_digests)
    ):
        raise Task07MigrationError("TASK07_REPAIR_BATCH_INVALID")
    grouped: dict[DatasetKey, list[tuple[datetime, datetime, int, str]]] = {}
    for raw_id, raw_digest in zip(action_ids, action_digests, strict=True):
        identifier = int(raw_id)
        action = action_by_id.get(identifier)
        if (
            action is None
            or action.get("action") != operation
            or action.get("action_digest") != raw_digest
            or action.get("symbol") != batch.get("symbol")
            or action.get("dataset_kind") != batch.get("dataset_kind")
            or action.get("frequency") != batch.get("frequency")
        ):
            raise Task07MigrationError("TASK07_REPAIR_BATCH_INVALID")
        try:
            dataset = DatasetKey(
                provider=str(action["provider"]),
                dataset_kind=DatasetKind(str(action["dataset_kind"])),
                symbol=str(action["symbol"]),
                contract_or_series=str(action["contract_or_series"]),
                frequency=BarFrequency(str(action["frequency"])),
                adjustment=str(action["adjustment"]),
                schema_version=str(action["schema_version"]),
            )
            window = action["window"]
            if not isinstance(window, Mapping):
                raise TypeError
            start = _aware_datetime(str(window["start"]))
            end = _aware_datetime(str(window["end"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise Task07MigrationError("TASK07_REPAIR_ACTION_INVALID") from exc
        if start >= end:
            raise Task07MigrationError("TASK07_REPAIR_ACTION_INVALID")
        grouped.setdefault(dataset, []).append(
            (start, end, identifier, str(raw_digest))
        )
    targets: list[Task07RepairTarget] = []
    for dataset, windows in grouped.items():
        ordered = sorted(windows, key=lambda item: (item[0], item[1], item[2]))
        current_start, current_end, identifier, digest = ordered[0]
        current_ids = [identifier]
        current_digests = [digest]
        for start, end, identifier, digest in ordered[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
                current_ids.append(identifier)
                current_digests.append(digest)
                continue
            targets.append(
                _task07_repair_target(
                    operation=operation,
                    dataset=dataset,
                    start=current_start,
                    end=current_end,
                    action_ids=current_ids,
                    action_digests=current_digests,
                )
            )
            current_start, current_end = start, end
            current_ids = [identifier]
            current_digests = [digest]
        targets.append(
            _task07_repair_target(
                operation=operation,
                dataset=dataset,
                start=current_start,
                end=current_end,
                action_ids=current_ids,
                action_digests=current_digests,
            )
        )
    return tuple(
        sorted(
            targets,
            key=lambda item: (
                item.dataset.symbol,
                item.dataset.dataset_kind.value,
                item.dataset.frequency.value,
                item.dataset.contract_or_series,
                item.start,
            ),
        )
    )


def _task07_repair_target(
    *,
    operation: str,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
    action_ids: Sequence[int],
    action_digests: Sequence[str],
) -> Task07RepairTarget:
    body = {
        "operation": operation,
        "dataset": {
            "provider": dataset.provider,
            "dataset_kind": dataset.dataset_kind.value,
            "symbol": dataset.symbol,
            "contract_or_series": dataset.contract_or_series,
            "frequency": dataset.frequency.value,
            "adjustment": dataset.adjustment,
            "schema_version": dataset.schema_version,
        },
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source_action_ids": list(action_ids),
        "source_action_digests": list(action_digests),
    }
    return Task07RepairTarget(
        operation=operation,
        dataset=dataset,
        start=start,
        end=end,
        source_action_ids=tuple(action_ids),
        source_action_digests=tuple(action_digests),
        target_digest=canonical_json_digest(body),
    )


def execute_task07_repair_target(
    target: Task07RepairTarget,
    *,
    sessions: Sequence[TradingSessionCoverage],
    fetch_direct: Callable[[ProviderBarRequest], ProviderBarBatch],
    read_canonical_1m: Callable[[Task07RepairTarget], object],
    publish: Callable[[ProviderBarBatch, ManifestLineage | None], Mapping[str, object]],
    record_gap: Callable[[Task07RepairTarget, str], object],
) -> dict[str, object]:
    if not isinstance(target, Task07RepairTarget):
        raise Task07MigrationError("TASK07_REPAIR_TARGET_INVALID")
    session_tuple = tuple(sessions)
    if not session_tuple or not all(
        isinstance(item, TradingSessionCoverage) for item in session_tuple
    ):
        raise Task07MigrationError("TASK07_REPAIR_SESSION_INVALID")
    calls_rqdata = target.operation == "rqdata_redownload"
    try:
        lineage: ManifestLineage | None = None
        request = ProviderBarRequest(
            dataset=target.dataset,
            start=target.start,
            end=target.end,
            sessions=session_tuple,
        )
        if calls_rqdata:
            batch = fetch_direct(request)
        elif target.operation == "canonical_1m_reaggregate":
            source = read_canonical_1m(target)
            if not isinstance(source, BarsResult):
                raise Task07MigrationError("TASK07_REAGGREGATE_SOURCE_INVALID")
            if (
                not source.source_datasets
                or any(
                    item.frequency is not BarFrequency.M1
                    or item.provider != target.dataset.provider
                    or item.dataset_kind is not target.dataset.dataset_kind
                    or item.symbol != target.dataset.symbol
                    or item.contract_or_series
                    != target.dataset.contract_or_series
                    for item in source.source_datasets
                )
            ):
                raise Task07MigrationError("TASK07_REAGGREGATE_SOURCE_INVALID")
            aggregation_sessions = tuple(
                AggregationSession(
                    trading_day=item.trading_day,
                    name=f"task07-repair-{index:06d}",
                    start=item.start,
                    end=item.end,
                )
                for index, item in enumerate(session_tuple, 1)
            )
            bars = aggregate_bars(
                source.bars,
                target_frequency=target.dataset.frequency,
                sessions=aggregation_sessions,
                requested_window=(target.start, target.end),
            )
            source_manifest_digest = canonical_json_digest(
                {
                    "source_datasets": [
                        {
                            "provider": item.provider,
                            "dataset_kind": item.dataset_kind.value,
                            "symbol": item.symbol,
                            "contract_or_series": item.contract_or_series,
                            "frequency": item.frequency.value,
                            "adjustment": item.adjustment,
                            "schema_version": item.schema_version,
                        }
                        for item in source.source_datasets
                    ],
                    "manifest_digests": list(source.manifest_digests),
                }
            )
            quality_evidence_digest = canonical_json_digest(
                {
                    "source_manifest_digest": source_manifest_digest,
                    "source_data_versions": list(source.source_data_versions),
                    "requested_window": [
                        target.start.isoformat(),
                        target.end.isoformat(),
                    ],
                }
            )
            lineage = ManifestLineage(
                origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
                source_frequency=BarFrequency.M1,
                legacy_source_checksum=source_manifest_digest,
                quality_evidence_digest=quality_evidence_digest,
            )
            batch = ProviderBarBatch(
                request=request,
                bars=bars,
                data_version=f"task07-reaggregate-{target.target_digest[:16]}",
            )
        else:
            raise Task07MigrationError("TASK07_REPAIR_OPERATION_INVALID")
        validate_provider_batch(batch)
    except (
        DataCoreError,
        Task07MigrationError,
        RuntimeError,
        TimeoutError,
        ConnectionError,
    ) as exc:
        reason = (
            "task07_rqdata_redownload_failed"
            if calls_rqdata
            else "task07_canonical_1m_reaggregate_failed"
        )
        record_gap(target, reason)
        body = {
            "schema_version": 1,
            "command": "data.task07.repair",
            "status": "data_gap",
            "operation": target.operation,
            "target_digest": target.target_digest,
            "source_action_ids": list(target.source_action_ids),
            "source_action_digests": list(target.source_action_digests),
            "calls_rqdata": calls_rqdata,
            "publication": None,
            "data_gap": {
                "reason_code": reason,
                "error_type": type(exc).__name__,
            },
        }
        return {**body, "receipt_digest": canonical_json_digest(body)}
    publication = dict(publish(batch, lineage))
    body = {
        "schema_version": 1,
        "command": "data.task07.repair",
        "status": "passed",
        "operation": target.operation,
        "target_digest": target.target_digest,
        "source_action_ids": list(target.source_action_ids),
        "source_action_digests": list(target.source_action_digests),
        "calls_rqdata": calls_rqdata,
        "publication": publication,
        "data_gap": None,
    }
    return {**body, "receipt_digest": canonical_json_digest(body)}


def publish_task07_repair_batch(
    batch: ProviderBarBatch,
    *,
    lineage: ManifestLineage | None,
    target: Task07RepairTarget,
    store: CanonicalStore,
    catalog: HistoricalCatalog,
    batch_key: str,
    plan_digest: str,
    batch_digest: str,
    source_market_data_file_id: int,
    canonical_root: Path,
) -> dict[str, object]:
    _require_sha256(plan_digest, "TASK07_PLAN_DIGEST_INVALID")
    _require_sha256(batch_digest, "TASK07_BATCH_DIGEST_INVALID")
    if batch.request.dataset != target.dataset:
        raise Task07MigrationError("TASK07_REPAIR_TARGET_DRIFT")
    staged = store.stage(batch)
    validation = store.validate(staged)
    manifest_version = (
        TASK07_AGGREGATE_MANIFEST_VERSION
        if lineage is not None
        else TASK07_DIRECT_REPAIR_MANIFEST_VERSION
    )
    exact = [
        item
        for item in catalog.list_partitions(target.dataset)
        if _as_utc(item.coverage_start) == _as_utc(validation.coverage_start)
        and _as_utc(item.coverage_end) == _as_utc(validation.coverage_end)
        and item.row_count == validation.row_count
        and item.checksum == validation.file_checksum
        and item.overlap_reason == "version_replacement"
        and item.manifest_version == manifest_version
    ]
    if len(exact) > 1:
        store.discard(staged)
        raise Task07MigrationError("TASK07_REPAIR_REPLACEMENT_AMBIGUOUS")
    if exact:
        store.discard(staged)
        manifest = exact[0]
        publication_status = "reused"
    else:
        expectation_kwargs: dict[str, object] = {
            "overlap_reason": "version_replacement",
        }
        if lineage is not None:
            expectation_kwargs.update(
                {
                    "manifest_format": CANONICAL_MANIFEST_FORMAT_V2,
                    "lineage": lineage,
                }
            )
        published = store.publish(
            staged,
            PublishExpectation.from_validation(
                validation,
                manifest_version=manifest_version,
                **expectation_kwargs,
            ),
        )
        manifest = published.partition_manifest
        publication_status = "published"
    body: dict[str, object] = {
        "schema_version": 1,
        "command": "data.task07.repair-publication",
        "status": "passed",
        "publication_status": publication_status,
        "overlap_reason": "version_replacement",
        "batch_key": batch_key,
        "plan_digest": plan_digest,
        "batch_digest": batch_digest,
        "market_data_file_id": source_market_data_file_id,
        "target_digest": target.target_digest,
        "dataset": {
            "provider": target.dataset.provider,
            "dataset_kind": target.dataset.dataset_kind.value,
            "symbol": target.dataset.symbol,
            "contract_or_series": target.dataset.contract_or_series,
            "frequency": target.dataset.frequency.value,
            "adjustment": target.dataset.adjustment,
            "schema_version": target.dataset.schema_version,
        },
        "coverage_start": manifest.coverage_start.isoformat(),
        "coverage_end": manifest.coverage_end.isoformat(),
        "row_count": manifest.row_count,
        "file_uri": manifest.file_uri,
        "physical_checksum": manifest.checksum,
        "manifest_uri": manifest.manifest_uri,
        "manifest_digest": manifest.manifest_digest,
        "manifest_version": manifest.manifest_version,
        "data_version": validation.data_version,
        "canonical_logical_fingerprint": validation.canonical_logical_fingerprint,
        "calls_rqdata": target.operation == "rqdata_redownload",
        "deletion_authorized": False,
    }
    if lineage is not None:
        body.update(
            {
                "manifest_format": CANONICAL_MANIFEST_FORMAT_V2,
                "source_lineage": lineage.as_payload(),
            }
        )
    receipt = {**body, "receipt_digest": _digest(body)}
    verify_task07_published_batch(
        receipt,
        catalog=catalog,
        canonical_root=canonical_root,
    )
    return receipt


def prepare_legacy_aggregate_parquet_batch(
    *,
    path: Path,
    source_checksum: str,
    dataset: DatasetKey,
    data_version: str,
    quality_evidence_digest: str,
    rank1_contract_by_day: Mapping[date, str] | None = None,
) -> PreparedLegacyBatch:
    """Convert a verified same-frequency legacy aggregate without reaggregation."""

    if dataset.frequency not in DERIVED_FREQUENCIES:
        raise Task07MigrationError("TASK07_AGGREGATE_FREQUENCY_INVALID")
    _require_sha256(
        quality_evidence_digest,
        "TASK07_QUALITY_EVIDENCE_DIGEST_INVALID",
    )
    if _file_checksum(path) != source_checksum:
        raise Task07MigrationError("TASK07_SOURCE_DRIFT")
    rows = _read_legacy_aggregate_rows(path)
    periods = {
        str(row.get("period") or "").strip().lower()
        for row in rows
    }
    source_intervals = {
        str(row.get("source_interval") or "").strip().lower()
        for row in rows
    }
    if periods != {dataset.frequency.value}:
        raise Task07MigrationError("TASK07_AGGREGATE_PERIOD_MISMATCH")
    if source_intervals != {BarFrequency.M1.value}:
        raise Task07MigrationError("TASK07_AGGREGATE_SOURCE_INTERVAL_MISMATCH")
    bars: list[CanonicalBar] = []
    seen_bar_ends: set[datetime] = set()
    source_days: set[date] = set()
    for row in rows:
        bar_end = _bar_end(row.get("datetime"), dataset.frequency)
        if bar_end in seen_bar_ends:
            raise Task07MigrationError("TASK07_AGGREGATE_DUPLICATE_BAR")
        seen_bar_ends.add(bar_end)
        trading_day = date.fromisoformat(
            _day_text(row.get("trading_day", row.get("trading_date")))
        )
        source_days.add(trading_day)
        if dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT:
            if rank1_contract_by_day is None:
                raise Task07MigrationError("TASK07_MAIN_MAP_MISSING")
            mapped = rank1_contract_by_day.get(trading_day)
            if mapped is None:
                raise Task07MigrationError("TASK07_MAIN_MAP_MISSING")
            if str(mapped).strip().upper() != dataset.contract_or_series:
                raise Task07MigrationError("TASK07_MAIN_MAP_MISMATCH")
        bars.append(
            CanonicalBar(
                provider="rqdata",
                dataset_kind=dataset.dataset_kind,
                symbol=dataset.symbol,
                contract_or_series=dataset.contract_or_series,
                frequency=dataset.frequency,
                bar_end=bar_end,
                trading_day=trading_day,
                open=_decimal(row, "open"),
                high=_decimal(row, "high"),
                low=_decimal(row, "low"),
                close=_decimal(row, "close"),
                volume=_decimal(row, "volume"),
                turnover=_decimal(row, "turnover", optional=True),
                open_interest=_decimal(row, "open_interest", optional=True),
                adjustment=dataset.adjustment,
                schema_version=dataset.schema_version,
            )
        )
    sessions = _exact_source_coverage_sessions(bars, dataset.frequency)
    request = ProviderBarRequest(
        dataset=dataset,
        start=min(item.start for item in sessions),
        end=max(item.end for item in sessions),
        sessions=sessions,
    )
    validated = validate_provider_batch(
        ProviderBarBatch(
            request=request,
            bars=tuple(bars),
            data_version=data_version,
        )
    )
    main_map_digest = None
    if rank1_contract_by_day is not None:
        main_map_digest = _digest(
            [
                [day.isoformat(), str(rank1_contract_by_day[day]).strip().upper()]
                for day in sorted(source_days)
            ]
        )
    lineage = ManifestLineage(
        origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
        source_frequency=BarFrequency.M1,
        legacy_source_checksum=source_checksum,
        quality_evidence_digest=quality_evidence_digest,
    )
    return PreparedLegacyBatch(
        batch=ProviderBarBatch(
            request=request,
            bars=validated.bars,
            data_version=validated.data_version,
        ),
        evidence=Task07AggregateEvidence(
            source_checksum=source_checksum,
            source_row_count=len(rows),
            target_frequency=dataset.frequency.value,
            source_frequency=BarFrequency.M1.value,
            quality_evidence_digest=quality_evidence_digest,
            trading_day_digest=_digest(
                [item.trading_day.isoformat() for item in validated.bars]
            ),
            main_map_digest=main_map_digest,
            schema_conversion_only=True,
            session_completeness_validated=False,
        ),
        lineage=lineage,
    )


def execute_task07_prepared_batch(
    prepared: PreparedLegacyBatch,
    *,
    store: CanonicalStore,
    catalog: HistoricalCatalog,
    manifest_version: str,
    batch_key: str,
    plan_digest: str,
    batch_digest: str,
    source_market_data_file_id: int,
    canonical_root: Path,
) -> dict[str, object]:
    if not isinstance(prepared, PreparedLegacyBatch):
        raise Task07MigrationError("TASK07_PREPARED_BATCH_INVALID")
    _require_sha256(plan_digest, "TASK07_PLAN_DIGEST_INVALID")
    _require_sha256(batch_digest, "TASK07_BATCH_DIGEST_INVALID")
    if source_market_data_file_id < 1:
        raise Task07MigrationError("TASK07_SOURCE_ID_INVALID")
    dataset = prepared.batch.request.dataset
    start = prepared.batch.request.start
    end = prepared.batch.request.end
    staged = store.stage(prepared.batch)
    validation = store.validate(staged)
    overlaps = [
        item
        for item in catalog.list_partitions(dataset)
        if _as_utc(item.coverage_start) < _as_utc(end)
        and _as_utc(start) < _as_utc(item.coverage_end)
    ]
    if overlaps:
        exact = [
            item
            for item in overlaps
            if _as_utc(item.coverage_start) == _as_utc(validation.coverage_start)
            and _as_utc(item.coverage_end) == _as_utc(validation.coverage_end)
            and item.row_count == validation.row_count
            and item.checksum == validation.file_checksum
        ]
        store.discard(staged)
        if len(overlaps) != 1 or len(exact) != 1:
            raise Task07MigrationError("TASK07_TARGET_OVERLAP_BLOCKED")
        manifest = exact[0]
        data_version = validation.data_version
        logical_fingerprint = validation.canonical_logical_fingerprint
        publication_status = "reused"
    else:
        expectation_kwargs: dict[str, object] = {}
        if prepared.lineage is not None:
            expectation_kwargs = {
                "manifest_format": CANONICAL_MANIFEST_FORMAT_V2,
                "lineage": prepared.lineage,
            }
        published = store.publish(
            staged,
            PublishExpectation.from_validation(
                validation,
                manifest_version=manifest_version,
                **expectation_kwargs,
            ),
        )
        manifest = published.partition_manifest
        data_version = published.data_version
        logical_fingerprint = published.canonical_logical_fingerprint
        publication_status = "published"
    correction = asdict(prepared.evidence)
    body: dict[str, object] = {
        "schema_version": 1,
        "command": "data.task07.apply",
        "status": "passed",
        "publication_status": publication_status,
        "batch_key": batch_key,
        "plan_digest": plan_digest,
        "batch_digest": batch_digest,
        "market_data_file_id": source_market_data_file_id,
        "dataset": {
            "provider": dataset.provider,
            "dataset_kind": dataset.dataset_kind.value,
            "symbol": dataset.symbol,
            "contract_or_series": dataset.contract_or_series,
            "frequency": dataset.frequency.value,
            "adjustment": dataset.adjustment,
            "schema_version": dataset.schema_version,
        },
        "coverage_start": manifest.coverage_start.isoformat(),
        "coverage_end": manifest.coverage_end.isoformat(),
        "row_count": manifest.row_count,
        "file_uri": manifest.file_uri,
        "physical_checksum": manifest.checksum,
        "manifest_uri": manifest.manifest_uri,
        "manifest_digest": manifest.manifest_digest,
        "manifest_version": manifest.manifest_version,
        "data_version": data_version,
        "canonical_logical_fingerprint": logical_fingerprint,
        "correction_evidence": correction,
        "correction_evidence_digest": _digest(correction),
        "calls_rqdata": False,
        "deletion_authorized": False,
    }
    if prepared.lineage is not None:
        body.update(
            {
                "manifest_format": CANONICAL_MANIFEST_FORMAT_V2,
                "source_lineage": prepared.lineage.as_payload(),
            }
        )
    receipt = {**body, "receipt_digest": _digest(body)}
    verify_task07_published_batch(
        receipt,
        catalog=catalog,
        canonical_root=canonical_root,
    )
    return receipt


def verify_task07_published_batch(
    receipt: Mapping[str, object],
    *,
    catalog: HistoricalCatalog,
    canonical_root: Path,
) -> dict[str, object]:
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if receipt.get("receipt_digest") != _digest(receipt_body):
        raise Task07MigrationError("TASK07_APPLY_RECEIPT_DRIFT")
    identity = receipt.get("dataset")
    if not isinstance(identity, Mapping):
        raise Task07MigrationError("TASK07_APPLY_RECEIPT_INVALID")
    try:
        dataset = DatasetKey(
            provider=str(identity["provider"]),
            dataset_kind=DatasetKind(str(identity["dataset_kind"])),
            symbol=str(identity["symbol"]),
            contract_or_series=str(identity["contract_or_series"]),
            frequency=BarFrequency(str(identity["frequency"])),
            adjustment=str(identity["adjustment"]),
            schema_version=str(identity["schema_version"]),
        )
        start = datetime.fromisoformat(str(receipt["coverage_start"]))
        end = datetime.fromisoformat(str(receipt["coverage_end"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise Task07MigrationError("TASK07_APPLY_RECEIPT_INVALID") from exc
    matches = [
        item
        for item in catalog.list_partitions(dataset)
        if _as_utc(item.coverage_start) == _as_utc(start)
        and _as_utc(item.coverage_end) == _as_utc(end)
        and item.manifest_digest == receipt.get("manifest_digest")
        and item.checksum == receipt.get("physical_checksum")
        and item.row_count == receipt.get("row_count")
        and item.file_uri == receipt.get("file_uri")
        and item.manifest_uri == receipt.get("manifest_uri")
    ]
    if len(matches) != 1:
        raise Task07MigrationError("TASK07_CATALOG_READBACK_MISMATCH")
    root = canonical_root.resolve(strict=True)
    file_path = _safe_canonical_path(root, str(receipt["file_uri"]))
    manifest_path = _safe_canonical_path(root, str(receipt["manifest_uri"]))
    if _file_checksum(file_path) != receipt.get("physical_checksum"):
        raise Task07MigrationError("TASK07_CANONICAL_CHECKSUM_MISMATCH")
    try:
        parquet = pq.ParquetFile(file_path)
        if parquet.schema_arrow != CANONICAL_PARQUET_SCHEMA:
            raise Task07MigrationError("TASK07_CANONICAL_SCHEMA_MISMATCH")
        if parquet.metadata.num_rows != receipt.get("row_count"):
            raise Task07MigrationError("TASK07_CANONICAL_ROW_COUNT_MISMATCH")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if isinstance(exc, Task07MigrationError):
            raise
        raise Task07MigrationError("TASK07_CANONICAL_READBACK_INVALID") from exc
    if not isinstance(manifest, dict):
        raise Task07MigrationError("TASK07_CANONICAL_READBACK_INVALID")
    receipt_manifest_format = receipt.get("manifest_format")
    if receipt_manifest_format is not None:
        if (
            receipt_manifest_format != CANONICAL_MANIFEST_FORMAT_V2
            or manifest.get("manifest_format") != receipt_manifest_format
            or manifest.get("manifest_version") != receipt.get("manifest_version")
            or manifest.get("source_lineage") != receipt.get("source_lineage")
        ):
            raise Task07MigrationError("TASK07_MANIFEST_LINEAGE_MISMATCH")
        try:
            lineage = ManifestLineage.from_payload(receipt.get("source_lineage"))
            lineage.validate_dataset(dataset)
        except ValueError as exc:
            raise Task07MigrationError("TASK07_MANIFEST_LINEAGE_MISMATCH") from exc
    stored_manifest_digest = manifest.pop("manifest_digest", None)
    if (
        stored_manifest_digest != receipt.get("manifest_digest")
        or canonical_json_digest(manifest) != stored_manifest_digest
    ):
        raise Task07MigrationError("TASK07_MANIFEST_DIGEST_MISMATCH")
    body = {
        "schema_version": 1,
        "command": "data.task07.verify",
        "status": "passed",
        "batch_key": receipt.get("batch_key"),
        "plan_digest": receipt.get("plan_digest"),
        "batch_digest": receipt.get("batch_digest"),
        "receipt_digest": receipt.get("receipt_digest"),
        "physical_checksum": receipt.get("physical_checksum"),
        "manifest_digest": receipt.get("manifest_digest"),
        "row_count": receipt.get("row_count"),
        "coverage_start": receipt.get("coverage_start"),
        "coverage_end": receipt.get("coverage_end"),
        "readonly": True,
    }
    return {**body, "verify_digest": _digest(body)}


def load_task07_rank1_map(
    session: Session,
    *,
    dataset: DatasetKey,
    trading_days: Sequence[date],
) -> dict[date, str]:
    if dataset.dataset_kind is not DatasetKind.ACTUAL_DOMINANT:
        return {}
    requested = tuple(sorted(set(trading_days)))
    if not requested:
        raise Task07MigrationError("TASK07_MAIN_MAP_MISSING")
    rows = tuple(
        session.execute(
            select(
                MainContractMap.trade_date,
                MainContractMap.contract_code,
                MainContractMap.data_version,
            )
            .where(
                func.lower(MainContractMap.instrument_symbol) == dataset.symbol,
                MainContractMap.provider == "rqdata",
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.rank == 1,
                MainContractMap.trade_date.in_(requested),
            )
            .order_by(
                MainContractMap.trade_date,
                MainContractMap.data_version,
                MainContractMap.id,
            )
        )
    )
    by_day: dict[date, set[str]] = {day: set() for day in requested}
    for trading_day, contract, _version in rows:
        normalized = str(contract or "").strip().upper()
        if not normalized or normalized.endswith(".MAIN"):
            raise Task07MigrationError("TASK07_MAIN_MAP_INVALID")
        by_day[trading_day].add(normalized)
    if any(not contracts for contracts in by_day.values()):
        raise Task07MigrationError("TASK07_MAIN_MAP_MISSING")
    if any(len(contracts) != 1 for contracts in by_day.values()):
        raise Task07MigrationError("TASK07_MAIN_MAP_CONFLICT")
    return {day: next(iter(by_day[day])) for day in requested}


def resolve_task07_provider_sessions(
    session: Session,
    *,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
) -> tuple[TradingSessionCoverage, ...]:
    try:
        aggregation_sessions = product_sessions(
            session,
            symbol=dataset.symbol,
            start=start - timedelta(days=7),
            end=end + timedelta(days=7),
        )
    except (ValueError, TypeError) as exc:
        raise Task07MigrationError("TASK07_INSTRUMENT_SESSION_INVALID") from exc
    if not aggregation_sessions:
        raise Task07MigrationError("TASK07_TRADING_SESSION_MISSING")
    provider_sessions = build_provider_sessions(
        dataset,
        start=start,
        end=end,
        sessions=aggregation_sessions,
    )
    if not provider_sessions:
        raise Task07MigrationError("TASK07_SESSION_COVERAGE_MISSING")
    return provider_sessions


def prepare_legacy_parquet_batch(
    *,
    path: Path,
    source_checksum: str,
    dataset: DatasetKey,
    sessions: Sequence[TradingSessionCoverage],
    data_version: str,
    rank1_contract_by_day: Mapping[date, str] | None = None,
) -> PreparedLegacyBatch:
    physical_checksum = _file_checksum(path)
    if physical_checksum != source_checksum:
        raise Task07MigrationError("TASK07_SOURCE_DRIFT")
    session_tuple = tuple(sessions)
    if not session_tuple:
        raise Task07MigrationError("TASK07_SESSION_COVERAGE_MISSING")
    frame = _read_legacy_rows(path)
    expected_days = {
        bar_end: session.trading_day
        for session in session_tuple
        for bar_end in session.expected_bar_ends
    }
    if len(expected_days) != sum(
        len(session.expected_bar_ends) for session in session_tuple
    ):
        raise Task07MigrationError("TASK07_SESSION_COVERAGE_CONFLICT")
    bars: list[CanonicalBar] = []
    original_days: list[str] = []
    corrected_days: list[str] = []
    for row in frame:
        bar_end = _bar_end(row.get("datetime"), dataset.frequency)
        trading_day = expected_days.get(bar_end)
        if trading_day is None:
            raise Task07MigrationError("TASK07_SESSION_COVERAGE_MISMATCH")
        original_days.append(_day_text(row.get("trading_day", row.get("trading_date"))))
        corrected_days.append(trading_day.isoformat())
        if dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT:
            if rank1_contract_by_day is None:
                raise Task07MigrationError("TASK07_MAIN_MAP_MISSING")
            mapped = rank1_contract_by_day.get(trading_day)
            if mapped is None:
                raise Task07MigrationError("TASK07_MAIN_MAP_MISSING")
            if str(mapped).strip().upper() != dataset.contract_or_series:
                raise Task07MigrationError("TASK07_MAIN_MAP_MISMATCH")
        bars.append(
            CanonicalBar(
                provider="rqdata",
                dataset_kind=dataset.dataset_kind,
                symbol=dataset.symbol,
                contract_or_series=dataset.contract_or_series,
                frequency=dataset.frequency,
                bar_end=bar_end,
                trading_day=trading_day,
                open=_decimal(row, "open"),
                high=_decimal(row, "high"),
                low=_decimal(row, "low"),
                close=_decimal(row, "close"),
                volume=_decimal(row, "volume"),
                turnover=_decimal(row, "turnover", optional=True),
                open_interest=_decimal(row, "open_interest", optional=True),
                adjustment=dataset.adjustment,
                schema_version=dataset.schema_version,
            )
        )
    request = ProviderBarRequest(
        dataset=dataset,
        start=min(session.start for session in session_tuple),
        end=max(session.end for session in session_tuple),
        sessions=session_tuple,
    )
    batch = ProviderBarBatch(
        request=request,
        bars=tuple(bars),
        data_version=data_version,
    )
    validated = validate_provider_batch(batch)
    normalized = ProviderBarBatch(
        request=request,
        bars=validated.bars,
        data_version=validated.data_version,
    )
    main_map_digest = None
    if rank1_contract_by_day is not None:
        main_map_digest = _digest(
            [
                [day.isoformat(), str(contract).strip().upper()]
                for day, contract in sorted(rank1_contract_by_day.items())
            ]
        )
    return PreparedLegacyBatch(
        batch=normalized,
        evidence=Task07CorrectionEvidence(
            source_checksum=source_checksum,
            source_row_count=len(frame),
            corrected_row_count=len(validated.bars),
            corrected_trading_day_count=sum(
                original != corrected
                for original, corrected in zip(original_days, corrected_days, strict=True)
            ),
            original_trading_day_digest=_digest(original_days),
            corrected_trading_day_digest=_digest(corrected_days),
            main_map_digest=main_map_digest,
        ),
    )


def _read_legacy_rows(path: Path) -> tuple[dict[str, object], ...]:
    try:
        parquet = pq.ParquetFile(path)
        names = set(parquet.schema_arrow.names)
        day_column = "trading_day" if "trading_day" in names else "trading_date"
        required = {"datetime", day_column, "open", "high", "low", "close", "volume"}
        if not required <= names:
            raise Task07MigrationError("TASK07_SOURCE_SCHEMA_INVALID")
        columns = ["datetime", day_column, *_VALUE_COLUMNS]
        table = parquet.read(columns=[name for name in columns if name in names])
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, Task07MigrationError):
            raise
        raise Task07MigrationError("TASK07_SOURCE_SCHEMA_INVALID") from exc
    rows = tuple(dict(item) for item in table.to_pylist())
    if not rows:
        raise Task07MigrationError("TASK07_SOURCE_EMPTY")
    if day_column != "trading_day":
        for row in rows:
            row["trading_day"] = row.pop(day_column)
    return rows


def _read_legacy_aggregate_rows(path: Path) -> tuple[dict[str, object], ...]:
    try:
        parquet = pq.ParquetFile(path)
        names = set(parquet.schema_arrow.names)
        day_column = (
            "trading_day" if "trading_day" in names else "trading_date"
        )
        required = {
            "datetime",
            day_column,
            "open",
            "high",
            "low",
            "close",
            "volume",
            "period",
            "source_interval",
        }
        if not required <= names:
            raise Task07MigrationError("TASK07_SOURCE_SCHEMA_INVALID")
        columns = [
            "datetime",
            day_column,
            *_VALUE_COLUMNS,
            "period",
            "source_interval",
        ]
        table = parquet.read(
            columns=[name for name in columns if name in names]
        )
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, Task07MigrationError):
            raise
        raise Task07MigrationError("TASK07_SOURCE_SCHEMA_INVALID") from exc
    rows = tuple(dict(item) for item in table.to_pylist())
    if not rows:
        raise Task07MigrationError("TASK07_SOURCE_EMPTY")
    if day_column != "trading_day":
        for row in rows:
            row["trading_day"] = row.pop(day_column)
    return rows


def read_legacy_aggregate_trading_days(
    path: Path,
    *,
    source_checksum: str,
) -> tuple[date, ...]:
    if _file_checksum(path) != source_checksum:
        raise Task07MigrationError("TASK07_SOURCE_DRIFT")
    try:
        parquet = pq.ParquetFile(path)
        names = set(parquet.schema_arrow.names)
        day_column = (
            "trading_day" if "trading_day" in names else "trading_date"
        )
        if day_column not in names:
            raise Task07MigrationError("TASK07_SOURCE_SCHEMA_INVALID")
        days: set[date] = set()
        for batch in parquet.iter_batches(
            batch_size=65_536,
            columns=[day_column],
        ):
            days.update(_source_day(item) for item in batch.column(0).to_pylist())
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, Task07MigrationError):
            raise
        raise Task07MigrationError("TASK07_SOURCE_SCHEMA_INVALID") from exc
    if not days:
        raise Task07MigrationError("TASK07_SOURCE_EMPTY")
    return tuple(sorted(days))


def _source_day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise Task07MigrationError("TASK07_SOURCE_TRADING_DAY_INVALID") from exc


def _exact_source_coverage_sessions(
    bars: Sequence[CanonicalBar],
    frequency: BarFrequency,
) -> tuple[TradingSessionCoverage, ...]:
    minutes = {
        BarFrequency.M5: 5,
        BarFrequency.M15: 15,
        BarFrequency.M30: 30,
        BarFrequency.H1: 60,
    }.get(frequency)
    if minutes is None:
        raise Task07MigrationError("TASK07_AGGREGATE_FREQUENCY_INVALID")
    by_day: dict[date, list[datetime]] = {}
    for bar in bars:
        by_day.setdefault(bar.trading_day, []).append(bar.bar_end)
    sessions = tuple(
        TradingSessionCoverage(
            trading_day=trading_day,
            start=min(bar_ends) - timedelta(minutes=minutes),
            end=max(bar_ends),
            expected_bar_ends=tuple(sorted(bar_ends)),
        )
        for trading_day, bar_ends in sorted(by_day.items())
    )
    if not sessions:
        raise Task07MigrationError("TASK07_SESSION_COVERAGE_MISSING")
    return sessions


def _bar_end(value: object, frequency: BarFrequency) -> datetime:
    if not isinstance(value, datetime):
        raise Task07MigrationError("TASK07_SOURCE_DATETIME_INVALID")
    if value.tzinfo is None or value.utcoffset() is None:
        timezone = UTC if frequency in {BarFrequency.D1, BarFrequency.W1} else _SHANGHAI
        value = value.replace(tzinfo=timezone)
    return value.astimezone(UTC)


def _day_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _decimal(row: Mapping[str, object], field: str, *, optional: bool = False) -> Decimal | None:
    value = row.get(field)
    if value is None and optional:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Task07MigrationError("TASK07_SOURCE_DECIMAL_INVALID") from exc


def _file_checksum(path: Path) -> str:
    try:
        if not path.is_file() or path.is_symlink():
            raise Task07MigrationError("TASK07_SOURCE_MISSING")
        digest = sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise Task07MigrationError("TASK07_SOURCE_MISSING") from exc


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_sha256(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Task07MigrationError(code)
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC)


def _safe_canonical_path(root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise Task07MigrationError("TASK07_CANONICAL_PATH_INVALID")
    candidate = (root / relative).resolve(strict=True)
    if candidate == root or root not in candidate.parents or candidate.is_symlink():
        raise Task07MigrationError("TASK07_CANONICAL_PATH_INVALID")
    return candidate
