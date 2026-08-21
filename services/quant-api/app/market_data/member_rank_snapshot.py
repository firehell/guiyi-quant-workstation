"""Pinned, immutable reader for Main Force member-rank research snapshots."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Literal, Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq


RANK_BY_VALUES = ("volume", "long", "short")
MEMBER_RANK_ADMITTED_PRODUCTS = ("jm", "ag", "cu", "m")
MEMBER_RANK_SCHEMA_VERSION = 1
MEMBER_RANK_SCHEMA = pa.schema(
    [
        pa.field("physical_contract", pa.string(), nullable=False),
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("rank_by", pa.string(), nullable=False),
        pa.field("rank", pa.int16(), nullable=False),
        pa.field("member_name", pa.string(), nullable=False),
        pa.field("value", pa.decimal128(38, 0), nullable=False),
        pa.field("change", pa.decimal128(38, 0), nullable=False),
        pa.field("provider", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
    ]
)

_CONTRACT = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")
_DATASET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class MemberRankSnapshotError(RuntimeError):
    """Stable fail-closed error for a pinned member-rank snapshot."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TradingCalendarVerifier(Protocol):
    """The existing official calendar, injected by the composition root."""

    def is_trading_day(self, symbol: str, trade_date: date) -> bool: ...


class ContractValidityVerifier(Protocol):
    """The existing Catalog contract-validity fact, injected by the caller."""

    def is_contract_valid(self, physical_contract: str, trade_date: date) -> bool: ...


@dataclass(frozen=True, slots=True)
class MemberRankRow:
    physical_contract: str
    trade_date: date
    rank_by: Literal["volume", "long", "short"]
    rank: int
    member_name: str
    value: Decimal
    change: Decimal


@dataclass(frozen=True, slots=True)
class MemberRankDay:
    physical_contract: str
    trade_date: date
    rows: tuple[MemberRankRow, ...]

    def rows_for(self, rank_by: str) -> tuple[MemberRankRow, ...]:
        return tuple(row for row in self.rows if row.rank_by == rank_by)


@dataclass(frozen=True, slots=True)
class MemberRankPartitionDescriptor:
    relative_uri: str
    row_count: int
    coverage_start: date
    coverage_end: date
    quality_status: Literal["passed"]


@dataclass(frozen=True, slots=True)
class MemberRankSnapshotDescriptor:
    schema_version: int
    dataset_id: str
    provider: Literal["rqdata"]
    provider_client_version: str
    created_at: datetime
    requested_since: date
    requested_through: date
    requested_products: tuple[str, ...]
    admitted_products: tuple[str, ...]
    physical_contracts: tuple[str, ...]
    partitions: tuple[MemberRankPartitionDescriptor, ...]


class MemberRankSnapshotRepository:
    """Reads exactly one descriptor-pinned snapshot; it never discovers snapshots."""

    def __init__(
        self,
        root: Path,
        dataset_id: str,
        *,
        trading_calendar: TradingCalendarVerifier | None = None,
        contract_validity: ContractValidityVerifier
        | Callable[[str, date], bool]
        | None = None,
    ) -> None:
        if not isinstance(root, Path):
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_ROOT_INVALID")
        if not isinstance(dataset_id, str) or _DATASET_ID.fullmatch(dataset_id) is None:
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DATASET_ID_INVALID")
        self._snapshot_root = (
            root.resolve() / "main_force_member_rank_v1" / dataset_id
        ).resolve()
        self._trading_calendar = trading_calendar
        self._contract_validity = contract_validity
        self._descriptor = self._load_descriptor(dataset_id)

    @property
    def descriptor(self) -> MemberRankSnapshotDescriptor:
        return self._descriptor

    def day(self, physical_contract: str, trade_date: date) -> MemberRankDay | None:
        contract, symbol = _normalized_contract(physical_contract)
        if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
            raise MemberRankSnapshotError("MEMBER_TRADE_DATE_INVALID")
        if contract not in self.descriptor.physical_contracts:
            return None

        rows: list[MemberRankRow] = []
        found_partition = False
        for partition in self.descriptor.partitions:
            if partition.coverage_start <= trade_date <= partition.coverage_end:
                found_partition = True
                rows.extend(
                    row
                    for row in self._partition_rows(partition)
                    if row.physical_contract == contract and row.trade_date == trade_date
                )
        if not found_partition or not rows:
            return None

        self._verify_calendar(symbol, trade_date)
        self._verify_contract_validity(contract, trade_date)
        day = MemberRankDay(contract, trade_date, tuple(rows))
        _validate_day(day)
        return day

    def contract_days_before(
        self,
        physical_contract: str,
        before: date,
        *,
        limit: int,
    ) -> tuple[MemberRankDay, ...]:
        contract, _ = _normalized_contract(physical_contract)
        _validate_before_and_limit(before, limit)
        days = sorted(
            {
                row.trade_date
                for partition in self.descriptor.partitions
                for row in self._partition_rows(partition)
                if row.physical_contract == contract and row.trade_date < before
            },
            reverse=True,
        )
        result: list[MemberRankDay] = []
        for trade_date in days:
            value = self.day(contract, trade_date)
            if value is not None:
                result.append(value)
            if len(result) == limit:
                break
        return tuple(reversed(result))

    def rank1_days_before(
        self,
        symbol: str,
        before: date,
        *,
        limit: int,
        contract_by_day: Mapping[date, str],
    ) -> tuple[MemberRankDay, ...]:
        normalized_symbol = _normalized_symbol(symbol)
        _validate_before_and_limit(before, limit)
        if not isinstance(contract_by_day, Mapping):
            raise MemberRankSnapshotError("MEMBER_RANK1_MAP_INVALID")
        result: list[MemberRankDay] = []
        for trade_date in sorted(contract_by_day, reverse=True):
            if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
                raise MemberRankSnapshotError("MEMBER_RANK1_MAP_INVALID")
            if trade_date >= before:
                continue
            contract, contract_symbol = _normalized_contract(contract_by_day[trade_date])
            if contract_symbol != normalized_symbol:
                raise MemberRankSnapshotError("MEMBER_RANK1_MAP_INVALID")
            value = self.day(contract, trade_date)
            if value is not None:
                result.append(value)
            if len(result) == limit:
                break
        return tuple(reversed(result))

    def _load_descriptor(self, dataset_id: str) -> MemberRankSnapshotDescriptor:
        descriptor_path = self._snapshot_root / "snapshot.json"
        if not descriptor_path.is_file():
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_MISSING")
        try:
            payload = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID") from None
        descriptor = _parse_descriptor(payload, expected_dataset_id=dataset_id)
        for partition in descriptor.partitions:
            self._partition_path(partition)
        return descriptor

    def _partition_path(self, partition: MemberRankPartitionDescriptor) -> Path:
        relative = Path(partition.relative_uri)
        if relative.is_absolute():
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_ROOT_ESCAPE")
        path = (self._snapshot_root / relative).resolve()
        if path != self._snapshot_root and self._snapshot_root not in path.parents:
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_ROOT_ESCAPE")
        return path

    def _partition_rows(
        self, partition: MemberRankPartitionDescriptor
    ) -> tuple[MemberRankRow, ...]:
        path = self._partition_path(partition)
        if not path.is_file():
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_PARTITION_MISSING")
        try:
            table = pq.ParquetFile(path).read()
        except (OSError, pa.ArrowException):
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_PARQUET_INVALID") from None
        if not table.schema.equals(MEMBER_RANK_SCHEMA, check_metadata=True):
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_PARQUET_SCHEMA_MISMATCH")
        if table.num_rows != partition.row_count:
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_ROW_COUNT_MISMATCH")
        values = table.to_pylist()
        rows = tuple(_row_from_parquet(value, self.descriptor) for value in values)
        dates = {row.trade_date for row in rows}
        if not dates or min(dates) != partition.coverage_start or max(dates) != partition.coverage_end:
            raise MemberRankSnapshotError("MEMBER_SNAPSHOT_COVERAGE_MISMATCH")
        return rows

    def _verify_calendar(self, symbol: str, trade_date: date) -> None:
        if self._trading_calendar is None:
            raise MemberRankSnapshotError("MEMBER_TRADING_CALENDAR_UNAVAILABLE")
        try:
            valid = self._trading_calendar.is_trading_day(symbol, trade_date)
        except Exception as exc:
            raise MemberRankSnapshotError("MEMBER_TRADING_CALENDAR_UNAVAILABLE") from exc
        if valid is not True:
            raise MemberRankSnapshotError("MEMBER_TRADING_DAY_INVALID")

    def _verify_contract_validity(self, physical_contract: str, trade_date: date) -> None:
        verifier = self._contract_validity
        if verifier is None:
            raise MemberRankSnapshotError("MEMBER_CONTRACT_VALIDITY_UNAVAILABLE")
        try:
            valid = (
                verifier(physical_contract, trade_date)
                if callable(verifier)
                else verifier.is_contract_valid(physical_contract, trade_date)
            )
        except Exception as exc:
            raise MemberRankSnapshotError("MEMBER_CONTRACT_VALIDITY_UNAVAILABLE") from exc
        if valid is not True:
            raise MemberRankSnapshotError("MEMBER_CONTRACT_INVALID")


def _parse_descriptor(
    value: object, *, expected_dataset_id: str
) -> MemberRankSnapshotDescriptor:
    expected_fields = {
        "schema_version",
        "dataset_id",
        "provider",
        "provider_client_version",
        "created_at",
        "requested_since",
        "requested_through",
        "requested_products",
        "admitted_products",
        "physical_contracts",
        "partitions",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != MEMBER_RANK_SCHEMA_VERSION
    ):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_SCHEMA_VERSION_INVALID")
    if value["dataset_id"] != expected_dataset_id:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DATASET_ID_MISMATCH")
    if value["provider"] != "rqdata":
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_PROVIDER_INVALID")
    requested_since = _date_field(value["requested_since"])
    requested_through = _date_field(value["requested_through"])
    if requested_since > requested_through:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    partitions_value = value["partitions"]
    if not isinstance(partitions_value, list) or not partitions_value:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    requested_products = _products_field(value["requested_products"])
    admitted_products = _products_field(value["admitted_products"])
    physical_contracts = _contracts_field(value["physical_contracts"])
    allowed = frozenset(MEMBER_RANK_ADMITTED_PRODUCTS)
    if (
        not set(requested_products).issubset(allowed)
        or not set(admitted_products).issubset(allowed)
        or not set(requested_products).issubset(admitted_products)
        or any(
            _normalized_contract(contract)[1] not in requested_products
            for contract in physical_contracts
        )
    ):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    return MemberRankSnapshotDescriptor(
        schema_version=MEMBER_RANK_SCHEMA_VERSION,
        dataset_id=expected_dataset_id,
        provider="rqdata",
        provider_client_version=_text_field(value["provider_client_version"]),
        created_at=_instant_field(value["created_at"]),
        requested_since=requested_since,
        requested_through=requested_through,
        requested_products=requested_products,
        admitted_products=admitted_products,
        physical_contracts=physical_contracts,
        partitions=tuple(_partition_descriptor(item) for item in partitions_value),
    )


def _partition_descriptor(value: object) -> MemberRankPartitionDescriptor:
    expected_fields = {
        "relative_uri",
        "row_count",
        "coverage_start",
        "coverage_end",
        "quality_status",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    row_count = value["row_count"]
    if type(row_count) is not int or row_count <= 0:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    relative_uri = value["relative_uri"]
    if not isinstance(relative_uri, str) or not relative_uri.strip():
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    coverage_start = _date_field(value["coverage_start"])
    coverage_end = _date_field(value["coverage_end"])
    if coverage_start > coverage_end or value["quality_status"] != "passed":
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    return MemberRankPartitionDescriptor(
        relative_uri=relative_uri,
        row_count=row_count,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        quality_status="passed",
    )


def _row_from_parquet(
    value: object, descriptor: MemberRankSnapshotDescriptor
) -> MemberRankRow:
    if not isinstance(value, dict):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_PARQUET_INVALID")
    contract, _ = _normalized_contract(value.get("physical_contract"))
    trade_date = value.get("trade_date")
    rank_by = value.get("rank_by")
    rank = value.get("rank")
    member_name = value.get("member_name")
    numeric_value = value.get("value")
    change = value.get("change")
    if (
        type(trade_date) is not date
        or rank_by not in RANK_BY_VALUES
        or type(rank) is not int
        or not isinstance(member_name, str)
        or not isinstance(numeric_value, Decimal)
        or not isinstance(change, Decimal)
    ):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_PARQUET_INVALID")
    if value.get("provider") != descriptor.provider or value.get("dataset_id") != descriptor.dataset_id:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_ROW_IDENTITY_MISMATCH")
    if contract not in descriptor.physical_contracts:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_ROW_CONTRACT_MISMATCH")
    return MemberRankRow(
        physical_contract=contract,
        trade_date=trade_date,
        rank_by=cast(Literal["volume", "long", "short"], rank_by),
        rank=rank,
        member_name=member_name,
        value=numeric_value,
        change=change,
    )


def _validate_day(day: MemberRankDay) -> None:
    keys = {(row.physical_contract, row.trade_date, row.rank_by, row.rank) for row in day.rows}
    if len(keys) != len(day.rows):
        raise MemberRankSnapshotError("MEMBER_CONTRACT_DAY_DUPLICATE")
    for rank_by in RANK_BY_VALUES:
        rows = tuple(sorted(day.rows_for(rank_by), key=lambda row: row.rank))
        if tuple(row.rank for row in rows) != tuple(range(1, 21)):
            raise MemberRankSnapshotError("MEMBER_CONTRACT_DAY_INCOMPLETE")
        if any(
            not row.member_name.strip() or row.value < 0 or not row.change.is_finite()
            for row in rows
        ):
            raise MemberRankSnapshotError("MEMBER_CONTRACT_DAY_INVALID")


def _normalized_contract(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise MemberRankSnapshotError("MEMBER_PHYSICAL_CONTRACT_INVALID")
    contract = value.strip().upper()
    match = _CONTRACT.fullmatch(contract)
    if match is None or not 1 <= int(contract[-2:]) <= 12:
        raise MemberRankSnapshotError("MEMBER_PHYSICAL_CONTRACT_INVALID")
    return contract, match.group(1).lower()


def member_rank_contract_product(value: object) -> str:
    """Return the product owned by one validated physical-contract identity."""
    return _normalized_contract(value)[1]


def _normalized_symbol(value: object) -> str:
    if not isinstance(value, str) or not value.strip().isalpha():
        raise MemberRankSnapshotError("MEMBER_SYMBOL_INVALID")
    return value.strip().lower()


def _validate_before_and_limit(before: object, limit: object) -> None:
    if not isinstance(before, date) or isinstance(before, datetime):
        raise MemberRankSnapshotError("MEMBER_BEFORE_INVALID")
    if type(limit) is not int or limit <= 0:
        raise MemberRankSnapshotError("MEMBER_HISTORY_LIMIT_INVALID")


def _date_field(value: object) -> date:
    if not isinstance(value, str):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID") from exc


def _instant_field(value: object) -> datetime:
    if not isinstance(value, str):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    return result.astimezone(UTC)


def _text_field(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    return value.strip()


def _products_field(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    products = tuple(_normalized_symbol(item) for item in value)
    if len(set(products)) != len(products):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    return products


def _contracts_field(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    contracts = tuple(_normalized_contract(item)[0] for item in value)
    if len(set(contracts)) != len(contracts):
        raise MemberRankSnapshotError("MEMBER_SNAPSHOT_DESCRIPTOR_INVALID")
    return contracts
