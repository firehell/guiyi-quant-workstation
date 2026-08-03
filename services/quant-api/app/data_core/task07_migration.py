"""Task 07 adapters for immutable legacy RQData Parquet sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.bar_schema import CanonicalBar
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
    raw_checksum: str | None
    raw_comparison_digest: str | None


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
    raw_path: Path | None = None,
    raw_checksum: str | None = None,
    dataset: DatasetKey,
    sessions: Sequence[TradingSessionCoverage],
    data_version: str,
    rank1_contract_by_day: Mapping[date, str] | None = None,
) -> PreparedLegacyBatch:
    if (raw_path is None) != (raw_checksum is None):
        raise Task07MigrationError("TASK07_RAW_EVIDENCE_INCOMPLETE")
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
    corrected_by_bar_end: dict[datetime, date] = {}
    for row in frame:
        bar_end = _bar_end(row.get("datetime"), dataset.frequency)
        trading_day = expected_days.get(bar_end)
        if trading_day is None:
            raise Task07MigrationError("TASK07_SESSION_COVERAGE_MISMATCH")
        original_days.append(_day_text(row.get("trading_day", row.get("trading_date"))))
        corrected_days.append(trading_day.isoformat())
        corrected_by_bar_end[bar_end] = trading_day
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
    raw_comparison_digest = None
    if raw_path is not None and raw_checksum is not None:
        if _file_checksum(raw_path) != raw_checksum:
            raise Task07MigrationError("TASK07_RAW_SOURCE_DRIFT")
        raw_comparison_digest = _compare_raw_rows(
            source_rows=frame,
            raw_rows=_read_legacy_rows(raw_path),
            frequency=dataset.frequency,
            corrected_by_bar_end=corrected_by_bar_end,
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
            raw_checksum=raw_checksum,
            raw_comparison_digest=raw_comparison_digest,
        ),
    )


def _compare_raw_rows(
    *,
    source_rows: Sequence[Mapping[str, object]],
    raw_rows: Sequence[Mapping[str, object]],
    frequency: BarFrequency,
    corrected_by_bar_end: Mapping[datetime, date],
) -> str:
    source = _comparison_rows(source_rows, frequency)
    raw = _comparison_rows(raw_rows, frequency)
    if set(source) != set(raw):
        raise Task07MigrationError("TASK07_RAW_COVERAGE_CONFLICT")
    evidence: list[dict[str, object]] = []
    for bar_end in sorted(source):
        if source[bar_end] != raw[bar_end]:
            raise Task07MigrationError("TASK07_RAW_VALUE_CONFLICT")
        raw_day = _day_text(raw_rows[raw[bar_end]["row_index"]].get("trading_day"))
        corrected_day = corrected_by_bar_end.get(bar_end)
        if corrected_day is None or raw_day != corrected_day.isoformat():
            raise Task07MigrationError("TASK07_RAW_TRADING_DAY_CONFLICT")
        evidence.append(
            {
                "bar_end": bar_end.isoformat(),
                "trading_day": corrected_day.isoformat(),
                "values": [str(source[bar_end][field]) for field in _VALUE_COLUMNS],
            }
        )
    return _digest(evidence)


def _comparison_rows(
    rows: Sequence[Mapping[str, object]],
    frequency: BarFrequency,
) -> dict[datetime, dict[str, object]]:
    result: dict[datetime, dict[str, object]] = {}
    for index, row in enumerate(rows):
        bar_end = _bar_end(row.get("datetime"), frequency)
        values = {
            field: _decimal(row, field, optional=field in {"turnover", "open_interest"})
            for field in _VALUE_COLUMNS
        }
        if bar_end in result and any(
            result[bar_end][field] != value for field, value in values.items()
        ):
            raise Task07MigrationError("TASK07_RAW_VALUE_CONFLICT")
        result[bar_end] = {**values, "row_index": index}
    return result


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


def _safe_canonical_path(root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise Task07MigrationError("TASK07_CANONICAL_PATH_INVALID")
    candidate = (root / relative).resolve(strict=True)
    if candidate == root or root not in candidate.parents or candidate.is_symlink():
        raise Task07MigrationError("TASK07_CANONICAL_PATH_INVALID")
    return candidate
