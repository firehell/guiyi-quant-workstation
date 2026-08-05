from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    String,
    column,
    delete,
    func,
    select,
    table,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data_core.contracts import DatasetKey
from app.models.data_center import MainContractMap
from app.models.data_core import DataGap, MarketDataset, MarketPartition
from app.data_core.rqdata_adapter import MainMapRow


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


_CANONICAL_MAIN_CONTRACT_VIEW = table(
    "data_core_main_contract_map",
    column("id", Integer()),
    column("symbol", String()),
    column("trading_day", Date()),
    column("actual_contract", String()),
    column("provider", String()),
    column("rank", Integer()),
    column("rule", String()),
    column("data_version", String()),
    column("created_at", DateTime(timezone=True)),
)


@dataclass(frozen=True, slots=True)
class CanonicalMainContractMapping:
    id: int
    symbol: str
    trading_day: date
    actual_contract: str
    data_version: str
    created_at: datetime | None

    @property
    def instrument_symbol(self) -> str:
        return self.symbol

    @property
    def trade_date(self) -> date:
        return self.trading_day

    @property
    def contract_code(self) -> str:
        return self.actual_contract


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
        object.__setattr__(
            self,
            "coverage_start",
            self.coverage_start.astimezone(UTC),
        )
        object.__setattr__(
            self,
            "coverage_end",
            self.coverage_end.astimezone(UTC),
        )
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
        object.__setattr__(
            self,
            "gap_start",
            self.gap_start.astimezone(UTC),
        )
        object.__setattr__(
            self,
            "gap_end",
            self.gap_end.astimezone(UTC),
        )
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise CatalogError("CATALOG_GAP_INVALID")
        if not isinstance(self.details, Mapping):
            raise CatalogError("CATALOG_GAP_INVALID")
        canonical_details = _canonical_json(self.details)
        if not isinstance(canonical_details, dict):
            raise CatalogError("CATALOG_GAP_INVALID")
        object.__setattr__(
            self,
            "details",
            MappingProxyType(canonical_details),
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
            dataset_kind=normalized.dataset_kind.value,
            symbol=normalized.symbol,
            contract_or_series=normalized.contract_or_series,
            frequency=normalized.frequency.value,
            adjustment=normalized.adjustment,
            schema_version=normalized.schema_version,
        )
        try:
            with self._session.begin_nested():
                self._session.add(dataset)
                self._session.flush()
            return dataset
        except IntegrityError:
            collision = self._find_dataset(normalized)
            if collision is None:
                raise CatalogError("CATALOG_DATASET_CONFLICT") from None
            return collision

    def register_partition(
        self,
        key: DatasetKey,
        manifest: PartitionManifest,
    ) -> MarketPartition:
        if not isinstance(manifest, PartitionManifest):
            raise CatalogError("CATALOG_PARTITION_INVALID")
        dataset = self.get_or_create_dataset(key)
        existing = self._find_partition(dataset.id, manifest)
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
        try:
            with self._session.begin_nested():
                self._session.add(partition)
                self._session.flush()
            return partition
        except IntegrityError:
            collision = self._find_partition(dataset.id, manifest)
            if collision is None or not _partition_matches(collision, manifest):
                raise CatalogError("CATALOG_PARTITION_CONFLICT") from None
            return collision

    def record_gap(self, key: DatasetKey, gap: GapWindow) -> DataGap:
        if not isinstance(gap, GapWindow):
            raise CatalogError("CATALOG_GAP_INVALID")
        dataset = self.get_or_create_dataset(key)
        existing = self._find_gap(dataset.id, gap)
        if existing is not None:
            if (
                existing.reason_code != gap.reason_code
                or existing.details != _details_dict(gap)
            ):
                raise CatalogError("CATALOG_GAP_CONFLICT")
            return existing
        data_gap = DataGap(
            dataset_id=dataset.id,
            gap_start=gap.gap_start,
            gap_end=gap.gap_end,
            reason_code=gap.reason_code,
            details=_details_dict(gap),
        )
        try:
            with self._session.begin_nested():
                self._session.add(data_gap)
                self._session.flush()
            return data_gap
        except IntegrityError:
            collision = self._find_gap(dataset.id, gap)
            if (
                collision is None
                or collision.reason_code != gap.reason_code
                or collision.details != _details_dict(gap)
            ):
                raise CatalogError("CATALOG_GAP_CONFLICT") from None
            return collision

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

    def list_effective_partitions(
        self,
        key: DatasetKey,
    ) -> list[MarketPartition]:
        """Select complete append-only replacements without deleting history."""
        rows = self.list_partitions(key)
        selected_replacements: list[MarketPartition] = []
        for replacement in sorted(
            (row for row in rows if row.overlap_reason == "version_replacement"),
            key=lambda row: row.id,
            reverse=True,
        ):
            window = _partition_window(replacement)
            replacement_windows = tuple(
                _partition_window(row) for row in selected_replacements
            )
            if _window_fully_covered(window, replacement_windows):
                continue
            if any(_windows_intersect(window, item) for item in replacement_windows):
                raise CatalogError("CATALOG_PARTITION_REPLACEMENT_PARTIAL_OVERLAP")
            selected_replacements.append(replacement)
        replacement_windows = tuple(
            _partition_window(row) for row in selected_replacements
        )
        effective: list[MarketPartition] = list(selected_replacements)
        for row in rows:
            if row.overlap_reason == "version_replacement":
                continue
            window = _partition_window(row)
            if _window_fully_covered(window, replacement_windows):
                continue
            if any(_windows_intersect(window, item) for item in replacement_windows):
                raise CatalogError("CATALOG_PARTITION_REPLACEMENT_PARTIAL_OVERLAP")
            effective.append(row)
        return sorted(
            effective,
            key=lambda row: (
                _as_utc_naive(row.coverage_start),
                _as_utc_naive(row.coverage_end),
                row.id,
            ),
        )

    def list_datasets(self, *, symbol: str) -> list[MarketDataset]:
        if not isinstance(symbol, str) or not symbol.strip():
            raise CatalogError("CATALOG_INSTRUMENT_SYMBOL_INVALID")
        return list(
            self._session.scalars(
                select(MarketDataset)
                .where(MarketDataset.symbol == symbol.strip().lower())
                .order_by(
                    MarketDataset.dataset_kind.asc(),
                    MarketDataset.contract_or_series.asc(),
                    MarketDataset.frequency.asc(),
                    MarketDataset.id.asc(),
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

    def clear_gaps_covered_by(
        self,
        key: DatasetKey,
        *,
        coverage_start: datetime,
        coverage_end: datetime,
    ) -> int:
        """Clear only gap markers fully repaired by a committed partition."""
        _validate_window(coverage_start, coverage_end)
        dataset = self._find_dataset(_require_dataset_key(key))
        if dataset is None:
            return 0
        gaps = list(
            self._session.scalars(
                select(DataGap).where(
                    DataGap.dataset_id == dataset.id,
                    DataGap.gap_start >= coverage_start.astimezone(UTC),
                    DataGap.gap_end <= coverage_end.astimezone(UTC),
                )
            )
        )
        for gap in gaps:
            self._session.delete(gap)
        self._session.flush()
        return len(gaps)

    def get_main_contract_mapping(
        self,
        *,
        instrument_symbol: str,
        trade_date: date,
    ) -> CanonicalMainContractMapping:
        if not isinstance(instrument_symbol, str) or not instrument_symbol.strip():
            raise CatalogError("CATALOG_INSTRUMENT_SYMBOL_INVALID")
        rows = list(
            self._session.execute(
                select(_CANONICAL_MAIN_CONTRACT_VIEW).where(
                    func.lower(_CANONICAL_MAIN_CONTRACT_VIEW.c.symbol)
                    == instrument_symbol.strip().lower(),
                    _CANONICAL_MAIN_CONTRACT_VIEW.c.trading_day == trade_date,
                )
            ).mappings()
        )
        return canonical_main_contract_mapping_from_rows(rows)

    def list_main_contract_mappings(
        self,
        *,
        instrument_symbol: str,
        start_date: date,
    ) -> tuple[CanonicalMainContractMapping, ...]:
        """Return the unambiguous rank-1 canonical map from ``start_date``."""

        if not isinstance(instrument_symbol, str) or not instrument_symbol.strip():
            raise CatalogError("CATALOG_INSTRUMENT_SYMBOL_INVALID")
        if not isinstance(start_date, date):
            raise CatalogError("CATALOG_TRADE_DATE_INVALID")
        rows = list(
            self._session.execute(
                select(_CANONICAL_MAIN_CONTRACT_VIEW)
                .where(
                    func.lower(_CANONICAL_MAIN_CONTRACT_VIEW.c.symbol)
                    == instrument_symbol.strip().lower(),
                    _CANONICAL_MAIN_CONTRACT_VIEW.c.trading_day >= start_date,
                )
                .order_by(
                    _CANONICAL_MAIN_CONTRACT_VIEW.c.trading_day.asc(),
                    _CANONICAL_MAIN_CONTRACT_VIEW.c.data_version.asc(),
                    _CANONICAL_MAIN_CONTRACT_VIEW.c.id.asc(),
                )
            ).mappings()
        )
        grouped: dict[date, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["trading_day"], []).append(row)
        return tuple(
            canonical_main_contract_mapping_from_rows(grouped[trading_day])
            for trading_day in sorted(grouped)
        )

    def register_main_contract_mapping(
        self,
        row: MainMapRow,
    ) -> MainContractMap:
        if not isinstance(row, MainMapRow):
            raise CatalogError("CATALOG_MAIN_CONTRACT_MAPPING_INVALID")
        existing = self._find_main_contract_mapping(row)
        if existing is not None:
            if existing.contract_code.strip().upper() != row.actual_contract:
                raise CatalogError("CATALOG_MAIN_CONTRACT_MAPPING_CONFLICT")
            return existing
        mapping = MainContractMap(
            instrument_symbol=row.symbol,
            trade_date=row.trading_day,
            rank=1,
            contract_code=row.actual_contract,
            rule="volume_open_interest",
            provider="rqdata",
            data_version=row.data_version,
            raw_payload={},
        )
        try:
            with self._session.begin_nested():
                self._session.add(mapping)
                self._session.flush()
            return mapping
        except IntegrityError:
            collision = self._find_main_contract_mapping(row)
            if collision is None:
                raise CatalogError("CATALOG_MAIN_CONTRACT_MAPPING_CONFLICT") from None
            if collision.contract_code.strip().upper() != row.actual_contract:
                raise CatalogError("CATALOG_MAIN_CONTRACT_MAPPING_CONFLICT")
            return collision

    def replace_rank1_mapping_window(
        self,
        *,
        symbol: str,
        start_day: date,
        end_day: date,
        rows: Sequence[MainMapRow],
    ) -> int:
        """Replace the exact RQData rank-1 mapping window, leaving all other days intact."""

        normalized = str(symbol or "").strip().lower()
        selected = tuple(rows)
        if (
            not normalized
            or not isinstance(start_day, date)
            or isinstance(start_day, datetime)
            or not isinstance(end_day, date)
            or isinstance(end_day, datetime)
            or start_day > end_day
            or not selected
            or any(
                not isinstance(row, MainMapRow)
                or row.symbol != normalized
                or row.rank != 1
                or not start_day <= row.trading_day <= end_day
                for row in selected
            )
        ):
            raise CatalogError("CATALOG_MAIN_CONTRACT_REPLACEMENT_INVALID")
        days = [row.trading_day for row in selected]
        if len(days) != len(set(days)):
            raise CatalogError("CATALOG_MAIN_CONTRACT_REPLACEMENT_DUPLICATE")
        self._session.execute(
            delete(MainContractMap).where(
                func.lower(MainContractMap.instrument_symbol) == normalized,
                MainContractMap.trade_date >= start_day,
                MainContractMap.trade_date <= end_day,
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
        )
        for row in selected:
            self._session.add(
                MainContractMap(
                    instrument_symbol=row.symbol,
                    trade_date=row.trading_day,
                    rank=1,
                    contract_code=row.actual_contract,
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version=row.data_version,
                    raw_payload={},
                )
            )
        self._session.flush()
        return len(selected)

    def _find_dataset(self, key: DatasetKey) -> MarketDataset | None:
        return self._session.scalar(
            select(MarketDataset).where(
                MarketDataset.provider == key.provider,
                MarketDataset.dataset_kind == key.dataset_kind.value,
                MarketDataset.symbol == key.symbol,
                MarketDataset.contract_or_series == key.contract_or_series,
                MarketDataset.frequency == key.frequency.value,
                MarketDataset.adjustment == key.adjustment,
                MarketDataset.schema_version == key.schema_version,
            )
        )

    def _find_partition(
        self,
        dataset_id: int,
        manifest: PartitionManifest,
    ) -> MarketPartition | None:
        return self._session.scalar(
            select(MarketPartition).where(
                MarketPartition.dataset_id == dataset_id,
                MarketPartition.coverage_start == manifest.coverage_start,
                MarketPartition.coverage_end == manifest.coverage_end,
                MarketPartition.manifest_version == manifest.manifest_version,
            )
        )

    def _find_gap(
        self,
        dataset_id: int,
        gap: GapWindow,
    ) -> DataGap | None:
        return self._session.scalar(
            select(DataGap).where(
                DataGap.dataset_id == dataset_id,
                DataGap.gap_start == gap.gap_start,
                DataGap.gap_end == gap.gap_end,
            )
        )

    def _find_main_contract_mapping(
        self,
        row: MainMapRow,
    ) -> MainContractMap | None:
        return self._session.scalar(
            select(MainContractMap).where(
                func.lower(MainContractMap.instrument_symbol) == row.symbol,
                MainContractMap.trade_date == row.trading_day,
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
                MainContractMap.data_version == row.data_version,
            )
        )


def canonical_main_contract_mapping_from_rows(
    rows: list[Mapping[str, Any]],
) -> CanonicalMainContractMapping:
    """Resolve rows selected with the frozen canonical-view predicate."""
    if not rows:
        raise CatalogError("CATALOG_MAIN_CONTRACT_MAPPING_NOT_FOUND")
    contracts: set[str] = set()
    versions: dict[str, int] = {}
    for row in rows:
        contract = str(row["actual_contract"] or "").strip().upper()
        if not contract or contract.endswith(".MAIN"):
            raise ValueError("ACTUAL_CONTRACT_MAPPING_INVALID")
        contracts.add(contract)
        version = str(row["data_version"] or "")
        versions[version] = versions.get(version, 0) + 1
    if len(contracts) != 1:
        raise ValueError("ACTUAL_CONTRACT_MAPPING_CONFLICT")
    if any(count > 1 for count in versions.values()):
        raise ValueError("ACTUAL_CONTRACT_MAPPING_DUPLICATE")
    selected = max(
        rows,
        key=lambda row: (
            _sortable_datetime(row["created_at"]),
            int(row["id"] or 0),
        ),
    )
    return CanonicalMainContractMapping(
        id=int(selected["id"]),
        symbol=str(selected["symbol"]),
        trading_day=selected["trading_day"],
        actual_contract=str(selected["actual_contract"]).strip().upper(),
        data_version=str(selected["data_version"]),
        created_at=selected["created_at"],
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


def _canonical_json(value: Any) -> Any:
    try:
        return _canonical_json_value(value, active_containers=set())
    except RecursionError:
        raise CatalogError("CATALOG_GAP_INVALID") from None


def _canonical_json_value(
    value: Any,
    *,
    active_containers: set[int],
) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise CatalogError("CATALOG_GAP_INVALID")
        return value
    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_containers:
            raise CatalogError("CATALOG_GAP_INVALID")
        active_containers.add(container_id)
        try:
            canonical: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise CatalogError("CATALOG_GAP_INVALID")
                canonical[key] = _canonical_json_value(
                    item,
                    active_containers=active_containers,
                )
            return canonical
        finally:
            active_containers.remove(container_id)
    if isinstance(value, (list, tuple)):
        container_id = id(value)
        if container_id in active_containers:
            raise CatalogError("CATALOG_GAP_INVALID")
        active_containers.add(container_id)
        try:
            return [
                _canonical_json_value(
                    item,
                    active_containers=active_containers,
                )
                for item in value
            ]
        finally:
            active_containers.remove(container_id)
    raise CatalogError("CATALOG_GAP_INVALID")


def _details_dict(gap: GapWindow) -> dict[str, Any]:
    details = _canonical_json(gap.details)
    if not isinstance(details, dict):
        raise CatalogError("CATALOG_GAP_INVALID")
    return details


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _partition_window(row: MarketPartition) -> tuple[datetime, datetime]:
    return (
        _as_utc_naive(row.coverage_start),
        _as_utc_naive(row.coverage_end),
    )


def _windows_intersect(
    first: tuple[datetime, datetime],
    second: tuple[datetime, datetime],
) -> bool:
    return first[0] < second[1] and first[1] > second[0]


def _window_fully_covered(
    window: tuple[datetime, datetime],
    covered_windows: tuple[tuple[datetime, datetime], ...],
) -> bool:
    cursor = window[0]
    for start, end in sorted(covered_windows):
        if end <= cursor or start >= window[1]:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, end)
        if cursor >= window[1]:
            return True
    return cursor >= window[1]


def _sortable_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _partition_matches(
    row: MarketPartition,
    manifest: PartitionManifest,
) -> bool:
    return (
        _as_utc_naive(row.coverage_start) == _as_utc_naive(manifest.coverage_start)
        and _as_utc_naive(row.coverage_end) == _as_utc_naive(manifest.coverage_end)
        and row.manifest_version == manifest.manifest_version
        and row.manifest_uri == manifest.manifest_uri
        and row.manifest_digest == manifest.manifest_digest
        and row.file_uri == manifest.file_uri
        and row.checksum == manifest.checksum
        and row.row_count == manifest.row_count
        and row.overlap_reason == manifest.overlap_reason
    )
