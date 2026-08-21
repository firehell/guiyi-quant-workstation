from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import traceback

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.market_data.member_rank_snapshot import (
    MEMBER_RANK_SCHEMA,
    MemberRankSnapshotError,
    MemberRankSnapshotRepository,
)


_CONTRACT = "JM2609"
_DAY = date(2026, 8, 20)


class _TradingCalendar:
    def __init__(self, days: set[date] | None = None) -> None:
        self.days = (
            {_DAY, date(2026, 8, 18), date(2026, 8, 19), date(2026, 8, 21)}
            if days is None
            else days
        )

    def is_trading_day(self, symbol: str, trade_date: date) -> bool:
        return symbol == "jm" and trade_date in self.days


class _ContractValidity:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid

    def is_contract_valid(self, physical_contract: str, trade_date: date) -> bool:
        return self.valid and physical_contract == _CONTRACT


def _repository(root: Path, dataset_id: str = "snapshot") -> MemberRankSnapshotRepository:
    return MemberRankSnapshotRepository(
        root,
        dataset_id,
        trading_calendar=_TradingCalendar(),
        contract_validity=_ContractValidity(),
    )


def _rows_for(day: date = _DAY, contract: str = _CONTRACT) -> list[dict[str, object]]:
    return [
        {
            "physical_contract": contract,
            "trade_date": day,
            "rank_by": rank_by,
            "rank": rank,
            "member_name": f"member-{rank_by}-{rank}",
            "value": Decimal(rank),
            "change": Decimal(rank - 10),
            "provider": "rqdata",
            "dataset_id": "snapshot",
        }
        for rank_by in ("volume", "long", "short")
        for rank in range(1, 21)
    ]


def _descriptor(
    *,
    dataset_id: str,
    relative_uri: str,
    row_count: int,
    coverage_start: date,
    coverage_end: date,
    admitted_products: tuple[str, ...] = ("jm",),
    physical_contracts: tuple[str, ...] = (_CONTRACT,),
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "provider": "rqdata",
        "provider_client_version": "3.5.6.1",
        "created_at": "2026-08-21T00:00:00Z",
        "requested_since": "2026-08-18",
        "requested_through": "2026-08-21",
        "requested_products": list(admitted_products),
        "admitted_products": list(admitted_products),
        "physical_contracts": list(physical_contracts),
        "partitions": [
            {
                "relative_uri": relative_uri,
                "row_count": row_count,
                "coverage_start": coverage_start.isoformat(),
                "coverage_end": coverage_end.isoformat(),
                "quality_status": "passed",
            }
        ],
    }


def write_descriptor(
    root: Path,
    dataset_id: str,
    *,
    relative_uri: str,
    row_count: int = 60,
    coverage_start: date = _DAY,
    coverage_end: date = _DAY,
    admitted_products: tuple[str, ...] = ("jm",),
    physical_contracts: tuple[str, ...] = (_CONTRACT,),
) -> Path:
    snapshot_root = root / "main_force_member_rank_v1" / dataset_id
    snapshot_root.mkdir(parents=True)
    (snapshot_root / "snapshot.json").write_text(
        json.dumps(
            _descriptor(
                dataset_id=dataset_id,
                relative_uri=relative_uri,
                row_count=row_count,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                admitted_products=admitted_products,
                physical_contracts=physical_contracts,
            )
        )
    )
    return snapshot_root


def write_snapshot(
    root: Path,
    dataset_id: str,
    *,
    rows: list[dict[str, object]] | None = None,
    admitted_products: tuple[str, ...] = ("jm",),
) -> Path:
    values = rows if rows is not None else _rows_for()
    snapshot_root = write_descriptor(
        root,
        dataset_id,
        relative_uri=f"contract={_CONTRACT}/year=2026/member_rank.parquet",
        row_count=len(values),
        coverage_start=min(row["trade_date"] for row in values),  # type: ignore[arg-type]
        coverage_end=max(row["trade_date"] for row in values),  # type: ignore[arg-type]
        admitted_products=admitted_products,
        physical_contracts=tuple(sorted({str(row["physical_contract"]) for row in values})),
    )
    path = snapshot_root / f"contract={_CONTRACT}/year=2026/member_rank.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(values, schema=MEMBER_RANK_SCHEMA), path)
    return snapshot_root


def test_repository_requires_exact_dataset_id_and_never_selects_newest(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "older", admitted_products=("jm",))
    write_snapshot(tmp_path, "newer", admitted_products=("ag",))

    repository = _repository(tmp_path, "older")

    assert repository.descriptor.dataset_id == "older"
    assert repository.descriptor.admitted_products == ("jm",)


def test_repository_rejects_descriptor_path_escape(tmp_path: Path) -> None:
    write_descriptor(tmp_path, "broken", relative_uri="../outside.parquet")

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_ROOT_ESCAPE"):
        _repository(tmp_path, "broken")


def test_repository_rejects_boolean_descriptor_schema_version(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "snapshot")
    descriptor_path = tmp_path / "main_force_member_rank_v1" / "snapshot" / "snapshot.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["schema_version"] = True
    descriptor_path.write_text(json.dumps(descriptor))

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_SCHEMA_VERSION_INVALID"):
        _repository(tmp_path)


@pytest.mark.parametrize(
    ("admitted_products", "physical_contracts"),
    (
        (("sc",), ("SC2609",)),
        (("ag",), ("JM2609",)),
    ),
)
def test_repository_rejects_forged_admission_or_contract_product_ownership(
    tmp_path: Path,
    admitted_products: tuple[str, ...],
    physical_contracts: tuple[str, ...],
) -> None:
    write_descriptor(
        tmp_path,
        "snapshot",
        relative_uri="contract=forged/year=2026/member_rank.parquet",
        admitted_products=admitted_products,
        physical_contracts=physical_contracts,
    )

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_DESCRIPTOR_INVALID"):
        _repository(tmp_path)


def test_descriptor_read_failure_does_not_retain_underlying_path(tmp_path: Path) -> None:
    snapshot_root = write_descriptor(
        tmp_path,
        "snapshot",
        relative_uri=f"contract={_CONTRACT}/year=2026/member_rank.parquet",
    )
    (snapshot_root / "snapshot.json").write_text("{")

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_DESCRIPTOR_INVALID") as info:
        _repository(tmp_path)

    assert info.value.__cause__ is None
    assert str(tmp_path) not in "".join(traceback.format_exception(info.value))


def test_parquet_read_failure_does_not_retain_underlying_path(tmp_path: Path) -> None:
    snapshot_root = write_descriptor(
        tmp_path,
        "snapshot",
        relative_uri=f"contract={_CONTRACT}/year=2026/member_rank.parquet",
    )
    path = snapshot_root / f"contract={_CONTRACT}/year=2026/member_rank.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_PARQUET_INVALID") as info:
        _repository(tmp_path).day(_CONTRACT, _DAY)

    assert info.value.__cause__ is None
    assert str(tmp_path) not in "".join(traceback.format_exception(info.value))


def test_day_requires_three_complete_top20_rank_sets(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "snapshot", rows=_rows_for()[:-1])

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_CONTRACT_DAY_INCOMPLETE"):
        _repository(tmp_path).day(_CONTRACT, _DAY)


def test_day_returns_none_when_no_descriptor_partition_covers_the_date(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "snapshot")

    assert _repository(tmp_path).day(_CONTRACT, date(2026, 8, 21)) is None


def test_day_rejects_duplicate_member_rank_key(tmp_path: Path) -> None:
    rows = _rows_for()
    rows.append(rows[0].copy())
    write_snapshot(tmp_path, "snapshot", rows=rows)

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_CONTRACT_DAY_DUPLICATE"):
        _repository(tmp_path).day(_CONTRACT, _DAY)


def test_day_rejects_non_trading_day(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "snapshot")
    repository = MemberRankSnapshotRepository(
        tmp_path,
        "snapshot",
        trading_calendar=_TradingCalendar(days=set()),
        contract_validity=_ContractValidity(),
    )

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_TRADING_DAY_INVALID"):
        repository.day(_CONTRACT, _DAY)


def test_day_rejects_contract_outside_catalog_validity(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "snapshot")
    repository = MemberRankSnapshotRepository(
        tmp_path,
        "snapshot",
        trading_calendar=_TradingCalendar(),
        contract_validity=_ContractValidity(valid=False),
    )

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_CONTRACT_INVALID"):
        repository.day(_CONTRACT, _DAY)


def test_day_requires_parquet_row_identity_to_match_descriptor(tmp_path: Path) -> None:
    rows = _rows_for()
    for row in rows:
        row["dataset_id"] = "other"
    write_snapshot(tmp_path, "snapshot", rows=rows)

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_ROW_IDENTITY_MISMATCH"):
        _repository(tmp_path).day(_CONTRACT, _DAY)


def test_day_requires_descriptor_row_count_to_match_parquet(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "snapshot")
    descriptor_path = tmp_path / "main_force_member_rank_v1" / "snapshot" / "snapshot.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["partitions"][0]["row_count"] = 61
    descriptor_path.write_text(json.dumps(descriptor))

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_ROW_COUNT_MISMATCH"):
        _repository(tmp_path).day(_CONTRACT, _DAY)


def test_contract_history_is_strictly_before_and_bounded(tmp_path: Path) -> None:
    rows = [
        row
        for day_number in (18, 19, 20, 21)
        for row in _rows_for(date(2026, 8, day_number))
    ]
    write_snapshot(tmp_path, "snapshot", rows=rows)

    result = _repository(tmp_path).contract_days_before(
        _CONTRACT, date(2026, 8, 21), limit=2
    )

    assert [item.trade_date.day for item in result] == [19, 20]


def test_rank1_history_uses_exact_contract_for_each_day(tmp_path: Path) -> None:
    alternate = "JM2610"
    rows = _rows_for(date(2026, 8, 18)) + _rows_for(date(2026, 8, 19))
    rows += _rows_for(date(2026, 8, 20), contract=alternate)
    write_snapshot(tmp_path, "snapshot", rows=rows)
    repository = MemberRankSnapshotRepository(
        tmp_path,
        "snapshot",
        trading_calendar=_TradingCalendar(),
        contract_validity=lambda physical_contract, trade_date: physical_contract in {_CONTRACT, alternate},
    )

    result = repository.rank1_days_before(
        "jm",
        date(2026, 8, 21),
        limit=2,
        contract_by_day={
            date(2026, 8, 18): _CONTRACT,
            date(2026, 8, 19): _CONTRACT,
            date(2026, 8, 20): alternate,
        },
    )

    assert [(item.trade_date, item.physical_contract) for item in result] == [
        (date(2026, 8, 19), _CONTRACT),
        (date(2026, 8, 20), alternate),
    ]
