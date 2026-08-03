from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.historical_migration import (
    ShadowException,
    _source_intervals,
    build_jm_migration_plan,
    build_jm_apply_bound_facts,
    build_jm_shadow_query_set,
    compare_shadow_bars,
    inventory_jm_legacy_assets,
    run_historical_shadow_query_set,
)
from app.db.base import Base
from app.models.data_center import MarketDataFile


def _write_legacy(
    path: Path,
    *,
    period: str,
    source_interval: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {
            "datetime": [datetime(2026, 7, 1, 1, 1, tzinfo=UTC)],
            "trading_day": ["2026-07-01"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [12.0],
            "turnover": [1206.0],
            "open_interest": [99.0],
            "period": [period],
        }
    if source_interval is not None:
        columns["source_interval"] = [source_interval]
    table = pa.table(columns)
    pq.write_table(table, path)


def test_inventory_and_plan_reuse_only_direct_jm_assets(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    one_minute = tmp_path / "legacy" / "jm2609_1m.parquet"
    derived = tmp_path / "legacy" / "jm2609_5m.parquet"
    derived_daily = tmp_path / "legacy" / "jm2609_1d.parquet"
    unproven_weekly = tmp_path / "legacy" / "jm2609_1w.parquet"
    _write_legacy(one_minute, period="1m", source_interval="1m")
    _write_legacy(derived, period="5m", source_interval="1m")
    _write_legacy(derived_daily, period="1d", source_interval="1m")
    _write_legacy(unproven_weekly, period="1w", source_interval=None)
    with sessionmaker(bind=engine)() as session:
        for index, (path, period) in enumerate(
            (
                (one_minute, "1m"),
                (derived, "5m"),
                (derived_daily, "1d"),
                (unproven_weekly, "1w"),
            ),
            start=1,
        ):
            session.add(
                MarketDataFile(
                    id=index,
                    provider="rqdata",
                    data_type="actual_dominant",
                    instrument_symbol="jm",
                    contract_code="JM2609",
                    period=period,
                    start_time=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
                    end_time=datetime(2026, 7, 1, 1, 1, tzinfo=UTC),
                    file_path=str(path),
                    row_count=1,
                    checksum=None,
                    data_version=f"legacy-{period}",
                    data_role="primary",
                    quality_status="passed",
                )
            )
        session.commit()

        inventory = inventory_jm_legacy_assets(session, project_root=tmp_path)
        plan = build_jm_migration_plan(inventory)

    assert [item.period for item in inventory] == ["1d", "1m", "1w", "5m"]
    assert all(len(item.checksum_actual) == 64 for item in inventory)
    assert plan["eligible_market_data_file_ids"] == [1]
    assert plan["excluded"] == [
        {"market_data_file_id": 3, "reason": "derived_daily_not_rqdata_direct"},
        {
            "market_data_file_id": 4,
            "reason": "direct_provenance_unproven",
        },
        {
            "market_data_file_id": 2,
            "reason": "preaggregated_source_not_direct_reuse_eligible",
        },
    ]
    assert len(plan["plan_digest"]) == 64
    assert plan["writes"] == {
        "rqdata_calls": False,
        "postgresql": False,
        "parquet": False,
    }
    assert plan["rollback"]["deletes_legacy"] is False

    bound_facts = build_jm_apply_bound_facts(
        (
            *inventory,
            replace(
                inventory[0],
                market_data_file_id=99,
                dataset_kind="continuous",
                contract_or_series="JM.MAIN",
            ),
        ),
        plan=plan,
        task_head="a" * 40,
        canonical_root=tmp_path / "canonical",
        staging_root=tmp_path / "staging",
        postgresql_target={
            "drivername": "postgresql+psycopg",
            "username": "guiyi",
            "host": "127.0.0.1",
            "port": 5432,
            "database": "guiyi_quant",
        },
        start=datetime(2026, 6, 30, tzinfo=UTC),
        end=datetime(2026, 7, 1, 1, 1, tzinfo=UTC),
        source_checkout=tmp_path,
            current_state={
                "state_digest": "c" * 64,
                "trading_days": ["2026-07-01"],
            },
    )
    assert bound_facts["scope"]["contract_or_series"] == ["JM.MAIN", "JM2609"]
    assert bound_facts["mapping_write_plan"]["trading_days"] == ["2026-07-01"]
    assert bound_facts["plan_digest"] == plan["plan_digest"]
    assert bound_facts["write_set"]["writes_legacy_market_data_assets"] is False
    receipt_path = Path(bound_facts["write_set"]["partial_apply_receipt"])
    assert receipt_path.parent == tmp_path / "receipts"
    assert receipt_path.name.startswith("jm-historical-apply-" + "a" * 40 + "-")

    progressed_facts = build_jm_apply_bound_facts(
        (
            *inventory,
            replace(
                inventory[0],
                market_data_file_id=99,
                dataset_kind="continuous",
                contract_or_series="JM.MAIN",
            ),
        ),
        plan=plan,
        task_head="a" * 40,
        canonical_root=tmp_path / "canonical",
        staging_root=tmp_path / "staging",
        postgresql_target=bound_facts["write_set"]["postgresql_target"],
        start=datetime(2026, 6, 30, tzinfo=UTC),
        end=datetime(2026, 7, 1, 1, 1, tzinfo=UTC),
        source_checkout=tmp_path,
        current_state={
            "state_digest": "d" * 64,
            "trading_days": ["2026-07-01"],
        },
    )
    assert (
        progressed_facts["write_set"]["partial_apply_receipt"]
        != bound_facts["write_set"]["partial_apply_receipt"]
    )


def test_shadow_compare_only_accepts_reasoned_field_scoped_exceptions() -> None:
    common = {
        "provider": "rqdata",
        "dataset_kind": "actual_dominant",
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
        "bar_end": "2026-07-01T01:01:00+00:00",
        "trading_day": "2026-07-01",
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.5",
        "volume": "12",
        "turnover": "1206",
        "open_interest": "99",
    }

    exact = compare_shadow_bars([common], [dict(common)])
    mismatch = compare_shadow_bars(
        [common],
        [{**common, "close": "100.6"}],
    )
    boundary = compare_shadow_bars(
        [common],
        [],
        allowed_exceptions=(
            ShadowException(
                bar_end="2026-07-01T01:01:00+00:00",
                reason="legacy_window_left_boundary",
                allow_missing=True,
            ),
        ),
    )
    boundary_value = compare_shadow_bars(
        [common],
        [{**common, "close": "100.6"}],
        allowed_exceptions=(
            ShadowException(
                bar_end="2026-07-01T01:01:00+00:00",
                reason="legacy_window_left_boundary",
                allow_missing=True,
            ),
        ),
    )
    identity_mismatch = compare_shadow_bars(
        [common],
        [{**common, "provider": "legacy"}],
    )

    assert exact["status"] == "passed"
    assert mismatch == {
        "status": "blocked",
        "legacy_row_count": 1,
        "canonical_row_count": 1,
        "differences": [
            {
                "bar_end": "2026-07-01T01:01:00+00:00",
                "reason": "value_mismatch",
                "fields": ["close"],
            }
        ],
        "explained_boundary_keys": [],
    }
    assert boundary["status"] == "passed_with_declared_boundaries"
    assert boundary_value["status"] == "blocked"
    assert identity_mismatch["status"] == "blocked"
    assert identity_mismatch["differences"][0]["fields"] == ["provider"]


def test_shadow_query_set_covers_both_identities_and_all_supported_periods() -> None:
    queries = build_jm_shadow_query_set(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert len(queries) == 14
    assert {item.dataset_kind for item in queries} == {
        "continuous",
        "actual_dominant",
    }
    assert {item.frequency for item in queries} == {
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
        "1d",
        "1w",
    }
    assert any(
        item.dataset_kind == "actual_dominant" and item.frequency == "1w"
        for item in queries
    )
    result = run_historical_shadow_query_set(
        queries,
        legacy_reader=lambda _query: [
            {
                "provider": "rqdata",
                "dataset_kind": _query.dataset_kind,
                "symbol": "jm",
                    "contract_or_series": (
                        _query.contract_or_series
                        if _query.contract_or_series is not None
                        else "JM2609"
                    ),
                "frequency": _query.frequency,
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
                "bar_end": "2026-07-01T01:01:00+00:00",
                "trading_day": "2026-07-01",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": "12",
                "turnover": "1206",
                "open_interest": "99",
            }
        ],
        canonical_reader=lambda _query: [
            {
                "provider": "rqdata",
                "dataset_kind": _query.dataset_kind,
                "symbol": "jm",
                    "contract_or_series": (
                        _query.contract_or_series
                        if _query.contract_or_series is not None
                        else "JM2609"
                    ),
                "frequency": _query.frequency,
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
                "bar_end": "2026-07-01T01:01:00+00:00",
                "trading_day": "2026-07-01",
                "open": "100.0",
                "high": "101.0",
                "low": "99.0",
                "close": "100.50",
                "volume": "12.0",
                "turnover": "1206.0",
                "open_interest": "99.0",
            }
        ],
        expected_actual_contract_by_day={"2026-07-01": "JM2609"},
    )

    assert result["status"] == "passed"
    assert result["query_count"] == 14
    assert len(result["query_set_digest"]) == 64
    assert len(result["receipt_digest"]) == 64


def test_shadow_query_binding_rejects_row_identity_from_another_query() -> None:
    queries = build_jm_shadow_query_set(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
    )

    def rows(query):
        return [{
            "provider": "rqdata",
            "dataset_kind": query.dataset_kind,
            "symbol": "jm",
            "contract_or_series": query.contract_or_series,
            "frequency": "1d" if query.frequency == "1m" else query.frequency,
            "adjustment": "none",
            "schema_version": "canonical-bar-v1",
            "bar_end": "2026-07-01T01:01:00+00:00",
            "trading_day": "2026-07-01",
            "open": "100", "high": "101", "low": "99", "close": "100",
            "volume": "1", "turnover": "100", "open_interest": "1",
        }]

    result = run_historical_shadow_query_set(
        queries,
        legacy_reader=rows,
        canonical_reader=rows,
    )

    assert result["status"] == "blocked"
    assert result["blocked_query_count"] >= 1
    assert result["results"][0]["differences"][0]["reason"] == "query_identity_mismatch"


def test_actual_shadow_accepts_mapping_resolved_contract_changes_and_rejects_wrong_day() -> None:
    queries = build_jm_shadow_query_set(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 3, tzinfo=UTC),
    )
    mapping = {"2026-07-01": "JM2609", "2026-07-02": "JM2610"}

    def rows(query):
        if query.dataset_kind == "continuous":
            contracts = [("2026-07-01", "JM.MAIN")]
        else:
            contracts = list(mapping.items())
        return [
            {
                "provider": "rqdata",
                "dataset_kind": query.dataset_kind,
                "symbol": "jm",
                "contract_or_series": contract,
                "frequency": query.frequency,
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
                "bar_end": f"{trading_day}T01:01:00+00:00",
                "trading_day": trading_day,
                "open": "100", "high": "101", "low": "99", "close": "100",
                "volume": "1", "turnover": "100", "open_interest": "1",
            }
            for trading_day, contract in contracts
        ]

    passed = run_historical_shadow_query_set(
        queries,
        legacy_reader=rows,
        canonical_reader=rows,
        expected_actual_contract_by_day=mapping,
    )
    blocked = run_historical_shadow_query_set(
        queries,
        legacy_reader=rows,
        canonical_reader=lambda query: [
            {
                **item,
                "contract_or_series": (
                    "JM2610"
                    if query.dataset_kind == "actual_dominant"
                    and item["trading_day"] == "2026-07-01"
                    else item["contract_or_series"]
                ),
            }
            for item in rows(query)
        ],
        expected_actual_contract_by_day=mapping,
    )

    assert passed["status"] == "passed"
    assert blocked["status"] == "blocked"
    actual_1m = next(
        item for item in blocked["results"]
        if item["query"]["dataset_kind"] == "actual_dominant"
        and item["query"]["frequency"] == "1m"
    )
    assert actual_1m["differences"][0]["reason"] == "query_identity_mismatch"


def test_source_interval_read_does_not_merge_hive_parent_with_file_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "provider=rqdata" / "jm_1m.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "provider": pa.array(["rqdata"], type=pa.large_string()),
                "source_interval": ["1m"],
            }
        ),
        path,
    )

    assert _source_intervals(path) == ("1m",)
