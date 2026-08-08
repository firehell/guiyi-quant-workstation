from __future__ import annotations

from app.db.base import Base
from app.models import (  # noqa: F401 - imports register metadata
    ContractSpec,
    DataGap,
    MainContractMap,
    MarketDataset,
    MarketPartition,
)


def _unique_columns(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }


def test_active_metadata_contains_only_minimal_data_tables() -> None:
    active = {
        "exchanges",
        "instruments",
        "contracts",
        "trading_calendars",
        "trading_sessions",
        "main_contract_map",
        "contract_specs",
        "market_datasets",
        "market_partitions",
        "data_gaps",
    }
    retired = {
        "data_sources",
        "data_download_tasks",
        "market_data_files",
        "data_quality_reports",
        "fee_margin_rules",
        "futures_trading_parameters",
        "futures_ex_factors",
        "futures_warehouse_stocks",
        "futures_roll_yields",
        "futures_member_ranks",
        "futures_basis",
        "futures_contract_universe",
        "futures_continuous_contract_map",
    }

    assert active <= set(Base.metadata.tables)
    assert retired.isdisjoint(Base.metadata.tables)


def test_current_fact_and_month_partition_unique_keys() -> None:
    assert ("kind", "symbol", "series_or_contract", "frequency") in _unique_columns(
        "market_datasets"
    )
    assert ("dataset_id", "year", "month") in _unique_columns("market_partitions")
    assert ("symbol", "trade_date") in _unique_columns("main_contract_map")
    assert ("contract_code", "trade_date") in _unique_columns("contract_specs")


def test_retired_version_and_raw_columns_are_absent() -> None:
    main_columns = set(MainContractMap.__table__.columns.keys())
    spec_columns = set(ContractSpec.__table__.columns.keys())
    dataset_columns = set(MarketDataset.__table__.columns.keys())
    partition_columns = set(MarketPartition.__table__.columns.keys())

    assert {"data_version", "raw_payload", "provider"}.isdisjoint(main_columns)
    assert "raw_payload" not in spec_columns
    assert {"provider", "adjustment", "schema_version"}.isdisjoint(dataset_columns)
    assert {"year", "month", "manifest_digest", "checksum"} <= partition_columns
    assert "resolved_at" not in DataGap.__table__.columns
