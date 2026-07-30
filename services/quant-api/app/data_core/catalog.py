from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap
from app.models.data_core import DataGap, MarketDataset, MarketPartition
from app.services import actual_contract_semantics


ALLOWED_OVERLAP_REASONS = frozenset(
    {
        "version_replacement",
        "repair_overlay",
        "rollover_transition",
    }
)


class CatalogError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DatasetKey:
    provider: str
    data_type: str
    instrument_symbol: str
    contract_code: str
    period: str

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "data_type",
            "instrument_symbol",
            "contract_code",
            "period",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CatalogError("CATALOG_DATASET_KEY_INVALID")
            normalized = value.strip()
            if field_name != "contract_code":
                normalized = normalized.lower()
            object.__setattr__(self, field_name, normalized)


@dataclass(frozen=True)
class PartitionManifest:
    coverage_start: datetime
    coverage_end: datetime
    manifest_version: str
    manifest_uri: str
    manifest_digest: str
    file_uri: str
    checksum: str
    row_count: int
    overlap_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_window(self.coverage_start, self.coverage_end)
        for value in (
            self.manifest_version,
            self.manifest_uri,
            self.file_uri,
        ):
            if not isinstance(value, str) or not value.strip():
                raise CatalogError("CATALOG_PARTITION_INVALID")
        _validate_sha256(self.manifest_digest)
        _validate_sha256(self.checksum)
        if (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise CatalogError("CATALOG_ROW_COUNT_INVALID")
        if (
            self.overlap_reason is not None
            and self.overlap_reason not in ALLOWED_OVERLAP_REASONS
        ):
            raise CatalogError("CATALOG_OVERLAP_REASON_INVALID")


@dataclass(frozen=True)
class GapWindow:
    gap_start: datetime
    gap_end: datetime
    reason_code: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_window(self.gap_start, self.gap_end)
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise CatalogError("CATALOG_GAP_INVALID")
        if not isinstance(self.details, Mapping):
            raise CatalogError("CATALOG_GAP_INVALID")
        object.__setattr__(
            self,
            "details",
            MappingProxyType(dict(self.details)),
        )


class HistoricalCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create_dataset(self, key: DatasetKey) -> MarketDataset:
        normalized = _require_dataset_key(key)
        existing = self._find_dataset(normalized)
        if existing is not None:
            return existing
        dataset = MarketDataset(
            provider=normalized.provider,
            data_type=normalized.data_type,
            instrument_symbol=normalized.instrument_symbol,
            contract_code=normalized.contract_code,
            period=normalized.period,
        )
        self._session.add(dataset)
        self._session.flush()
        return dataset

    def register_partition(
        self,
        key: DatasetKey,
        manifest: PartitionManifest,
    ) -> MarketPartition:
        if not isinstance(manifest, PartitionManifest):
            raise CatalogError("CATALOG_PARTITION_INVALID")
        dataset = self.get_or_create_dataset(key)
        existing = self._session.scalar(
            select(MarketPartition).where(
                MarketPartition.dataset_id == dataset.id,
                MarketPartition.coverage_start == manifest.coverage_start,
                MarketPartition.coverage_end == manifest.coverage_end,
                MarketPartition.manifest_version == manifest.manifest_version,
            )
        )
        if existing is not None:
            if not _partition_matches(existing, manifest):
                raise CatalogError("CATALOG_PARTITION_CONFLICT")
            return existing
        partition = MarketPartition(
            dataset_id=dataset.id,
            coverage_start=manifest.coverage_start,
            coverage_end=manifest.coverage_end,
            manifest_version=manifest.manifest_version,
            manifest_uri=manifest.manifest_uri,
            manifest_digest=manifest.manifest_digest,
            file_uri=manifest.file_uri,
            checksum=manifest.checksum,
            row_count=manifest.row_count,
            overlap_reason=manifest.overlap_reason,
        )
        self._session.add(partition)
        self._session.flush()
        return partition

    def record_gap(self, key: DatasetKey, gap: GapWindow) -> DataGap:
        if not isinstance(gap, GapWindow):
            raise CatalogError("CATALOG_GAP_INVALID")
        dataset = self.get_or_create_dataset(key)
        existing = self._session.scalar(
            select(DataGap).where(
                DataGap.dataset_id == dataset.id,
                DataGap.gap_start == gap.gap_start,
                DataGap.gap_end == gap.gap_end,
            )
        )
        if existing is not None:
            if (
                existing.reason_code != gap.reason_code
                or existing.details != dict(gap.details)
            ):
                raise CatalogError("CATALOG_GAP_CONFLICT")
            return existing
        data_gap = DataGap(
            dataset_id=dataset.id,
            gap_start=gap.gap_start,
            gap_end=gap.gap_end,
            reason_code=gap.reason_code,
            details=dict(gap.details),
        )
        self._session.add(data_gap)
        self._session.flush()
        return data_gap

    def list_partitions(self, key: DatasetKey) -> list[MarketPartition]:
        dataset = self._find_dataset(_require_dataset_key(key))
        if dataset is None:
            return []
        return list(
            self._session.scalars(
                select(MarketPartition)
                .where(MarketPartition.dataset_id == dataset.id)
                .order_by(
                    MarketPartition.coverage_start.asc(),
                    MarketPartition.coverage_end.asc(),
                    MarketPartition.manifest_version.asc(),
                    MarketPartition.id.asc(),
                )
            )
        )

    def list_gaps(self, key: DatasetKey) -> list[DataGap]:
        dataset = self._find_dataset(_require_dataset_key(key))
        if dataset is None:
            return []
        return list(
            self._session.scalars(
                select(DataGap)
                .where(DataGap.dataset_id == dataset.id)
                .order_by(
                    DataGap.gap_start.asc(),
                    DataGap.gap_end.asc(),
                    DataGap.id.asc(),
                )
            )
        )

    def get_main_contract_mapping(
        self,
        *,
        instrument_symbol: str,
        trade_date: date,
    ) -> MainContractMap:
        if not isinstance(instrument_symbol, str) or not instrument_symbol.strip():
            raise CatalogError("CATALOG_INSTRUMENT_SYMBOL_INVALID")
        mapping = actual_contract_semantics.load_strict_main_contract_mapping(
            self._session,
            instrument_symbol=instrument_symbol,
            trade_date=trade_date,
        )
        if mapping is None:
            raise CatalogError("CATALOG_MAIN_CONTRACT_MAPPING_NOT_FOUND")
        return mapping

    def _find_dataset(self, key: DatasetKey) -> MarketDataset | None:
        return self._session.scalar(
            select(MarketDataset).where(
                MarketDataset.provider == key.provider,
                MarketDataset.data_type == key.data_type,
                MarketDataset.instrument_symbol == key.instrument_symbol,
                MarketDataset.contract_code == key.contract_code,
                MarketDataset.period == key.period,
            )
        )


def _require_dataset_key(key: DatasetKey) -> DatasetKey:
    if not isinstance(key, DatasetKey):
        raise CatalogError("CATALOG_DATASET_KEY_INVALID")
    return key


def _validate_window(start: datetime, end: datetime) -> None:
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise CatalogError("CATALOG_TIME_WINDOW_INVALID")


def _validate_sha256(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CatalogError("CATALOG_SHA256_INVALID")


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _partition_matches(
    row: MarketPartition,
    manifest: PartitionManifest,
) -> bool:
    return (
        _as_utc_naive(row.coverage_start)
        == _as_utc_naive(manifest.coverage_start)
        and _as_utc_naive(row.coverage_end)
        == _as_utc_naive(manifest.coverage_end)
        and row.manifest_version == manifest.manifest_version
        and row.manifest_uri == manifest.manifest_uri
        and row.manifest_digest == manifest.manifest_digest
        and row.file_uri == manifest.file_uri
        and row.checksum == manifest.checksum
        and row.row_count == manifest.row_count
        and row.overlap_reason == manifest.overlap_reason
    )
