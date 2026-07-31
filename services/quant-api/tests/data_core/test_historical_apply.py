from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.data_core.bar_schema import CanonicalBar
from app.data_core.canonical_store import CanonicalStore
from app.data_core.catalog import HistoricalCatalog, PartitionManifest
from app.data_core import cli_service
from app.data_core import historical_migration
from app.data_core.contracts import BarFrequency, DatasetKind
from app.data_core.historical_apply import (
    _mapping_digest,
    execute_prepared_historical_apply,
    filter_actual_dominant_sessions,
    prepare_historical_apply_roots,
    prepare_historical_apply,
)
from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    build_apply_approval_packet,
    verify_approved_apply_progress,
)
from app.data_core.historical_apply_receipt import PartialApplyReceiptStore
from app.data_core.historical_sync import MappingSyncResult, SyncResult
from app.data_core.historical_sync import CanonicalBatchPublisher, HistoricalSynchronizer
from app.data_core.rqdata_adapter import (
    MainMapRequest,
    MainMapRow,
    ProviderBarBatch,
    TradingSessionCoverage,
)
from app.db.base import Base
from app.models.data_center import MainContractMap
from app.models.data_core import MarketDataset, MarketPartition


def _facts() -> dict[str, object]:
    state = {
        "catalog_digest": "c" * 64,
        "mapping_digest": "d" * 64,
        "calendar_digest": "e" * 64,
        "session_digest": "f" * 64,
        "dataset_write_plan_digest": "1" * 64,
        "mapping_complete": True,
        "missing_mapping_days": [],
        "trading_days": ["2026-07-01", "2026-07-02"],
        "session_windows": [
            {
                "trading_day": "2026-07-01",
                "start": "2026-07-01T01:00:00+00:00",
                "end": "2026-07-01T01:01:00+00:00",
            },
            {
                "trading_day": "2026-07-02",
                "start": "2026-07-02T01:00:00+00:00",
                "end": "2026-07-02T01:01:00+00:00",
            },
        ],
        "catalog_items": [],
        "mapping_rows": [
            {
                "symbol": "jm",
                "trading_day": "2026-07-01",
                "actual_contract": "JM2609",
                "rank": 1,
                "data_version": "rqdata-test-rank1",
            },
            {
                "symbol": "jm",
                "trading_day": "2026-07-02",
                "actual_contract": "JM2610",
                "rank": 1,
                "data_version": "rqdata-test-rank1",
            },
        ],
        "dataset_write_plan": [],
    }
    state["catalog_digest"] = hashlib.sha256(
        json.dumps({"items": []}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    state["mapping_digest"] = hashlib.sha256(
        json.dumps(
            {"rows": state["mapping_rows"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    state["dataset_write_plan_digest"] = hashlib.sha256(
        json.dumps(
            {"plans": state["dataset_write_plan"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    state["state_digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "task_head": "a" * 40,
        "source_checkout": "/tmp/project",
        "migration_revisions": ["20260730_0026", "20260730_0027"],
        "scope": {
            "symbol": "jm",
            "provider": "rqdata",
            "schema_version": "canonical-bar-v1",
            "dataset_kinds": ["continuous", "actual_dominant"],
            "direct_frequencies": ["1m", "1d", "1w"],
            "direct_frequency_matrix": {
                "continuous": ["1m", "1d", "1w"],
                "actual_dominant": ["1m", "1d"],
            },
            "window": {
                "start": "2026-07-01T00:00:00+00:00",
                "end": "2026-07-03T00:00:00+00:00",
            },
            "contract_or_series": ["JM.MAIN", "JM2609", "JM2610"],
        },
        "plan_digest": "b" * 64,
        "mapping_write_plan": {
            "provider": "rqdata",
            "symbol": "jm",
            "rank": 1,
            "start_day": "2026-07-01",
            "end_day": "2026-07-02",
            "trading_days": ["2026-07-01", "2026-07-02"],
            "allowed_contracts": ["JM2609", "JM2610"],
        },
        "current_state": state,
        "write_set": {
            "canonical_root": "/tmp/data/parquet/data-core-v2/canonical",
            "staging_root": "/tmp/data/parquet/data-core-v2/staging",
            "postgresql_target": {
                "drivername": "postgresql+psycopg",
                "username": "guiyi",
                "host": "127.0.0.1",
                "port": 5432,
                "database": "guiyi_quant",
            },
            "postgresql_tables": [
                "market_datasets",
                "market_partitions",
                "data_gaps",
                "main_contract_map",
            ],
            "writes_legacy_market_data_assets": False,
            "partial_apply_receipt": "/tmp/data/parquet/data-core-v2/receipts/apply.json",
        },
        "rollback": {
            "deletes_physical_data": False,
            "strategy": "keep_legacy_readonly_and_disable_canonical_consumer",
        },
    }


def _prepared():
    facts = _facts()
    facts["scope"] = {
        **facts["scope"],
        "window": {
            "start": "2026-06-30T00:00:00+00:00",
            "end": "2026-07-03T00:00:00+00:00",
        },
    }
    packet = build_apply_approval_packet(bound_facts=facts)
    return prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
    )


def _mapping(day: int, contract: str) -> MainMapRow:
    return MainMapRow(
        symbol="jm",
        trading_day=date(2026, 7, day),
        actual_contract=contract,
        rank=1,
        data_version="rqdata-test-rank1",
    )


def _mapping_identity(row: MainMapRow) -> dict[str, object]:
    return {
        "symbol": row.symbol,
        "trading_day": row.trading_day.isoformat(),
        "actual_contract": row.actual_contract,
        "rank": row.rank,
        "data_version": row.data_version,
    }


def _prepared_from_verified_mapping(rows: tuple[MainMapRow, ...]):
    approved_facts = _facts()
    initial_state = {
        **approved_facts["current_state"],
        "mapping_rows": [],
        "mapping_complete": False,
        "missing_mapping_days": ["2026-07-01", "2026-07-02"],
    }
    initial_state["mapping_digest"] = hashlib.sha256(
        b'{"rows":[]}'
    ).hexdigest()
    initial_state.pop("state_digest")
    initial_state["state_digest"] = hashlib.sha256(
        json.dumps(initial_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    approved_facts["current_state"] = initial_state
    packet = build_apply_approval_packet(bound_facts=approved_facts)
    row_identities = [_mapping_identity(row) for row in rows]
    mapped_days = {row["trading_day"] for row in row_identities}
    progressed_state = {
        **initial_state,
        "mapping_rows": row_identities,
        "mapping_complete": len(mapped_days) == 2,
        "missing_mapping_days": sorted(
            {"2026-07-01", "2026-07-02"} - mapped_days
        ),
    }
    progressed_state["mapping_digest"] = hashlib.sha256(
        json.dumps(
            {"rows": row_identities},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    progressed_facts = {**approved_facts, "current_state": progressed_state}
    progress = verify_approved_apply_progress(
        approved_facts,
        progressed_facts,
        verify_partition=lambda _dataset, _partition: True,
    )
    return prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=progressed_facts,
        verified_progress=progress,
    )


def _dataset_identity_for_test(
    dataset_kind: DatasetKind,
    contract: str,
    frequency: BarFrequency,
) -> dict[str, str]:
    return {
        "provider": "rqdata",
        "dataset_kind": dataset_kind.value,
        "symbol": "jm",
        "contract_or_series": contract,
        "frequency": frequency.value,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }


def _shadow_row(query, trading_day: str, contract: str) -> dict[str, str]:
    return {
        "provider": "rqdata",
        "dataset_kind": query.dataset_kind,
        "symbol": "jm",
        "contract_or_series": contract,
        "frequency": query.frequency,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
        "bar_end": f"{trading_day}T01:01:00+00:00",
        "trading_day": trading_day,
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100",
        "volume": "1",
        "turnover": "100",
        "open_interest": "1",
    }


def _shadow_bundle() -> dict[str, list[dict[str, str]]]:
    queries = cli_service.build_jm_shadow_query_set(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 3, tzinfo=UTC),
    )
    bundle: dict[str, list[dict[str, str]]] = {}
    for query in queries:
        query_id = f"{query.dataset_kind}:{query.frequency}"
        if query.dataset_kind == "continuous":
            bundle[query_id] = [_shadow_row(query, "2026-07-01", "JM.MAIN")]
        else:
            bundle[query_id] = [
                _shadow_row(query, "2026-07-01", "JM2609"),
                _shadow_row(query, "2026-07-02", "JM2610"),
            ]
    return bundle


def _shadow_session(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'shadow.sqlite'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT DISTINCT
                    id,
                    instrument_symbol AS symbol,
                    trade_date AS trading_day,
                    contract_code AS actual_contract,
                    provider,
                    rank,
                    rule,
                    data_version,
                    created_at
                FROM main_contract_map
                WHERE provider = 'rqdata'
                  AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def _shadow_args(tmp_path: Path, bundle: dict[str, list[dict[str, str]]]):
    legacy_path = tmp_path / "legacy.json"
    canonical_path = tmp_path / "canonical.json"
    legacy_path.write_text(json.dumps(bundle), encoding="utf-8")
    canonical_path.write_text(json.dumps(bundle), encoding="utf-8")
    return SimpleNamespace(
        legacy_json=legacy_path,
        canonical_json=canonical_path,
        exception_json=None,
        start="2026-07-01T00:00:00Z",
        end="2026-07-03T00:00:00Z",
    )


def test_migrate_shadow_uses_db_rank1_mapping_across_roll_days(tmp_path: Path) -> None:
    engine, session = _shadow_session(tmp_path)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 1),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="rank1-20260701",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 2),
                rank=1,
                contract_code="JM2610",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="rank1-20260702",
            ),
        ]
    )
    session.commit()

    result = cli_service.run_data_core_command(
        "migrate.shadow",
        session,
        _shadow_args(tmp_path, _shadow_bundle()),
    )

    assert result["status"] == "passed", result
    assert result["query_count"] == 13
    empty_mapping_digest = hashlib.sha256(b'{"mapping":{}}').hexdigest()
    assert result["mapping_evidence_digest"] != empty_mapping_digest
    session.close()
    engine.dispose()


def test_migrate_shadow_blocks_rows_that_disagree_with_db_rank1_mapping(
    tmp_path: Path,
) -> None:
    engine, session = _shadow_session(tmp_path)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, day),
                rank=1,
                contract_code="JM2610",
                rule="volume_open_interest",
                provider="rqdata",
                data_version=f"rank1-2026070{day}",
            )
            for day in (1, 2)
        ]
    )
    session.commit()

    result = cli_service.run_data_core_command(
        "migrate.shadow",
        session,
        _shadow_args(tmp_path, _shadow_bundle()),
    )

    assert result["status"] == "blocked"
    assert result["blocked_query_count"] == 6
    empty_mapping_digest = hashlib.sha256(b'{"mapping":{}}').hexdigest()
    assert result["mapping_evidence_digest"] != empty_mapping_digest
    session.close()
    engine.dispose()


def test_migrate_shadow_fails_closed_when_db_rank1_mapping_is_missing(
    tmp_path: Path,
) -> None:
    engine, session = _shadow_session(tmp_path)
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 1),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="rank1-20260701",
        )
    )
    session.commit()

    with pytest.raises(ValueError, match="shadow_rank1_mapping_missing"):
        cli_service.run_data_core_command(
            "migrate.shadow",
            session,
            _shadow_args(tmp_path, _shadow_bundle()),
        )
    session.close()
    engine.dispose()


def test_migrate_shadow_fails_closed_when_db_rank1_mapping_is_ambiguous(
    tmp_path: Path,
) -> None:
    engine, session = _shadow_session(tmp_path)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 1),
                rank=1,
                contract_code=contract,
                rule="volume_open_interest",
                provider="rqdata",
                data_version=data_version,
            )
            for contract, data_version in (
                ("JM2609", "rank1-a"),
                ("JM2610", "rank1-b"),
            )
        ]
    )
    session.commit()

    with pytest.raises(ValueError, match="shadow_rank1_mapping_ambiguous"):
        cli_service.run_data_core_command(
            "migrate.shadow",
            session,
            _shadow_args(tmp_path, _shadow_bundle()),
        )
    session.close()
    engine.dispose()


def test_current_state_serializer_reconstructs_verified_physical_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session = _shadow_session(tmp_path)
    window_start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    window_end = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)

    class SQLiteAwareCatalog(HistoricalCatalog):
        def list_partitions(self, key):
            rows = super().list_partitions(key)
            for row in rows:
                if row.coverage_start.tzinfo is None:
                    row.coverage_start = row.coverage_start.replace(tzinfo=UTC)
                if row.coverage_end.tzinfo is None:
                    row.coverage_end = row.coverage_end.replace(tzinfo=UTC)
            return rows

    monkeypatch.setattr(historical_migration, "HistoricalCatalog", SQLiteAwareCatalog)
    monkeypatch.setattr(
        historical_migration,
        "jm_provider_sessions_for_state",
        lambda _session, _start, _end: (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=window_start,
                end=window_end,
                expected_bar_ends=(window_end,),
            ),
        ),
    )
    initial_state = historical_migration.build_jm_current_state(
        session,
        start=window_start,
        end=window_end,
    )
    dataset = next(
        item
        for item in _prepared().datasets_for_contracts(("JM2609",))
        if item.dataset_kind is DatasetKind.CONTINUOUS
        and item.frequency is BarFrequency.M1
    )
    canonical_root = tmp_path / "canonical"
    file_uri = "provider=rqdata/kind=continuous/part.parquet"
    manifest_uri = "provider=rqdata/kind=continuous/part.manifest.json"
    file_path = canonical_root / file_uri
    manifest_path = canonical_root / manifest_uri
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"committed-canonical-partition")
    checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
    manifest_payload = {
        "file_checksum": checksum,
        "dataset_key": cli_service._dataset_identity_dict(dataset),
        "partition": {
            "coverage_start": window_start.isoformat(),
            "coverage_end": window_end.isoformat(),
            "file_uri": file_uri,
            "manifest_uri": manifest_uri,
        },
        "schema": "canonical-manifest-v1",
    }
    manifest_digest = hashlib.sha256(
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps({**manifest_payload, "manifest_digest": manifest_digest}),
        encoding="utf-8",
    )
    HistoricalCatalog(session).register_partition(
        dataset,
        PartitionManifest(
            coverage_start=window_start,
            coverage_end=window_end,
            manifest_version="canonical-manifest-v1",
            manifest_uri=manifest_uri,
            manifest_digest=manifest_digest,
            file_uri=file_uri,
            checksum=checksum,
            row_count=1,
        ),
    )
    session.commit()
    progressed_state = historical_migration.build_jm_current_state(
        session,
        start=window_start,
        end=window_end,
    )
    approved_facts = _facts()
    approved_facts["scope"] = {
        **approved_facts["scope"],
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "contract_or_series": ["JM.MAIN", "JM2609"],
    }
    approved_facts["mapping_write_plan"] = {
        **approved_facts["mapping_write_plan"],
        "start_day": "2026-07-01",
        "end_day": "2026-07-01",
        "trading_days": ["2026-07-01"],
        "allowed_contracts": ["JM2609"],
    }
    approved_facts["current_state"] = initial_state

    progress = verify_approved_apply_progress(
        approved_facts,
        {**approved_facts, "current_state": progressed_state},
        verify_partition=lambda actual_dataset, partition: (
            cli_service._verify_partition_evidence(
                canonical_root,
                actual_dataset,
                partition,
            )
        ),
    )

    assert len(progress.completed_datasets) == 1
    evidence = progress.completed_datasets[0]["partition_evidence"][0]
    assert evidence["file_uri"] == file_uri
    assert evidence["manifest_uri"] == manifest_uri
    session.close()
    engine.dispose()


def test_current_state_pre_migration_does_not_query_uncreated_catalog_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window_start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    window_end = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
    session_window = TradingSessionCoverage(
        trading_day=date(2026, 7, 1),
        start=window_start,
        end=window_end,
        expected_bar_ends=(window_end,),
    )

    class UnavailableCatalog:
        def __init__(self, _session: object) -> None:
            pass

        def __getattr__(self, _name: str):
            raise AssertionError("pre-migration plan must not query catalog tables")

    monkeypatch.setattr(historical_migration, "HistoricalCatalog", UnavailableCatalog)
    monkeypatch.setattr(
        historical_migration,
        "jm_provider_sessions_for_state",
        lambda _session, _start, _end: (session_window,),
    )

    state = historical_migration.build_jm_current_state(
        object(),  # type: ignore[arg-type]
        start=window_start,
        end=window_end,
        catalog_ready=False,
    )

    assert state["mapping_complete"] is False
    assert state["missing_mapping_days"] == ["2026-07-01"]
    assert state["mapping_rows"] == []
    assert len(state["catalog_items"]) == 3
    assert len(state["dataset_write_plan"]) == 3
    assert all(item["partitions"] == [] for item in state["catalog_items"])
    assert all(item["gaps"] == [] for item in state["catalog_items"])


@pytest.mark.parametrize(
    ("revision", "expected"),
    (("20260721_0025", False), ("20260730_0027", True)),
)
def test_migrate_plan_accepts_only_supported_pre_or_post_migration_revision(
    revision: str,
    expected: bool,
) -> None:
    class Result:
        def scalar_one(self) -> str:
            return revision

    class Session:
        def execute(self, _statement: object) -> Result:
            return Result()

    assert cli_service._data_core_catalog_ready_for_plan(Session()) is expected


def test_migrate_plan_rejects_partial_migration_revision() -> None:
    class Result:
        def scalar_one(self) -> str:
            return "20260730_0026"

    class Session:
        def execute(self, _statement: object) -> Result:
            return Result()

    with pytest.raises(
        HistoricalApplyGateError,
        match="data_core_plan_revision_not_supported",
    ):
        cli_service._data_core_catalog_ready_for_plan(Session())


def test_migrate_apply_rejects_revision_0025_before_inventory_or_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def scalar_one(self) -> str:
            return "20260721_0025"

    class Session:
        def execute(self, _statement: object) -> Result:
            return Result()

    monkeypatch.setattr(
        cli_service,
        "_loaded_source_root",
        lambda: Path("/tmp/project"),
    )
    monkeypatch.setattr(
        cli_service,
        "inventory_jm_legacy_assets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("revision Gate must run before inventory")
        ),
    )

    with pytest.raises(
        HistoricalApplyGateError,
        match="data_core_migration_revision_not_ready",
    ):
        cli_service.run_data_core_command(
            "migrate.apply",
            Session(),  # type: ignore[arg-type]
            SimpleNamespace(project_root=Path("/tmp/project")),
        )


def test_prepare_apply_rejects_fact_drift_before_executor_dependencies() -> None:
    facts = _facts()
    packet = build_apply_approval_packet(bound_facts=facts)

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        prepare_historical_apply(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts={**facts, "task_head": "c" * 40},
        )


def test_partial_apply_receipt_is_durable_and_resumable_per_dataset(
    tmp_path: Path,
) -> None:
    path = tmp_path / "receipts" / "apply.json"
    store = PartialApplyReceiptStore(path, bound_facts_digest="a" * 64)
    dataset = _dataset_identity_for_test(
        DatasetKind.ACTUAL_DOMINANT,
        "JM2609",
        BarFrequency.M1,
    )

    store.record_mapping(
        status="passed",
        row_count=2,
        mapping_digest="b" * 64,
    )
    store.record_dataset(
        dataset=dataset,
        status="passed",
        planned_windows=(
            (
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
            ),
        ),
        published_window_count=1,
        gap_window_count=0,
    )

    resumed = PartialApplyReceiptStore(path, bound_facts_digest="a" * 64)
    assert resumed.mapping_completed(mapping_digest="b" * 64) is True
    assert resumed.dataset_completed(dataset) is True
    assert resumed.snapshot()["status"] == "in_progress"

    with pytest.raises(ValueError, match="partial_apply_receipt_binding_mismatch"):
        PartialApplyReceiptStore(path, bound_facts_digest="c" * 64)


def test_fresh_process_resume_requires_catalog_manifest_and_checksum_reconciliation(
    tmp_path: Path,
) -> None:
    facts = _facts()
    packet = build_apply_approval_packet(bound_facts=facts)
    prepared = prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
    )
    receipt_path = tmp_path / "receipt.json"
    first_receipt = PartialApplyReceiptStore(
        receipt_path,
        bound_facts_digest=packet["packet_hash"],
    )
    progressed_state = {**facts["current_state"], "catalog_digest": "9" * 64}
    progressed_state.pop("state_digest")
    progress_digest = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    progressed_state["state_digest"] = progress_digest
    completed = _dataset_identity_for_test(
        DatasetKind.CONTINUOUS,
        "JM.MAIN",
        BarFrequency.M1,
    )
    evidence = ({
        "coverage_start": "2026-07-01T00:00:00+00:00",
        "coverage_end": "2026-07-03T00:00:00+00:00",
        "manifest_digest": "3" * 64,
        "checksum": "4" * 64,
        "file_uri": "provider=rqdata/kind=continuous/file.parquet",
        "manifest_uri": "provider=rqdata/kind=continuous/file.manifest.json",
    },)
    mapping_rows = (_mapping(1, "JM2609"), _mapping(2, "JM2610"))

    class InterruptedSynchronizer:
        calls = 0

        def sync_rank1_mapping(self, **_kwargs):
            return MappingSyncResult(False, mapping_rows)

        def sync(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated process interruption")
            window = (kwargs["start"], kwargs["end"])
            return SyncResult(False, (window,), (window,), ())

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        execute_prepared_historical_apply(
            prepared,
            synchronizer=InterruptedSynchronizer(),
            expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
            commit=lambda: None,
            rollback=lambda: None,
            receipt_store=first_receipt,
            capture_progress_state_digest=lambda: progress_digest,
            capture_partition_evidence=lambda _dataset: evidence,
        )

    assert first_receipt.mapping_completed(
        mapping_digest=_mapping_digest(mapping_rows)
    )
    assert first_receipt.completed_dataset(completed) is not None

    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["mapping"]["rows"][0]["actual_contract"] = "JM9999"
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    resumed = PartialApplyReceiptStore(
        receipt_path,
        bound_facts_digest=packet["packet_hash"],
    )
    completed_dataset = completed
    catalog_items = [{
        "dataset": completed_dataset,
        "partitions": [dict(evidence[0])],
        "gaps": [],
    }]
    write_plans = [{
        "dataset": completed_dataset,
        "mapping_valid_windows": [[prepared.start.isoformat(), prepared.end.isoformat()]],
        "missing_windows": [],
    }]
    progressed_state = {
        **facts["current_state"],
        "catalog_items": catalog_items,
        "catalog_digest": hashlib.sha256(
            json.dumps(
                {"items": catalog_items}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "dataset_write_plan": write_plans,
        "dataset_write_plan_digest": hashlib.sha256(
            json.dumps(
                {"plans": write_plans}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    progressed_facts = {**facts, "current_state": progressed_state}
    verified_progress = verify_approved_apply_progress(
        facts,
        progressed_facts,
        verify_partition=lambda _dataset, _partition: True,
    )
    prepared = prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=progressed_facts,
        verified_progress=verified_progress,
    )
    calls = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs):
            raise AssertionError("completed mapping must resume without provider call")

        def sync(self, **kwargs):
            calls.append(kwargs["dataset"])
            window = (kwargs["start"], kwargs["end"])
            return SyncResult(False, (window,), (window,), ())

    result = execute_prepared_historical_apply(
        prepared,
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: None,
        rollback=lambda: None,
        receipt_store=resumed,
        reconcile_mapping=lambda rows: len(rows) == 2,
        reconcile_completed_dataset=lambda dataset, recorded: (
            _dataset_identity_for_test(
                dataset.dataset_kind,
                dataset.contract_or_series,
                dataset.frequency,
            ) == completed
            and tuple(recorded["partition_evidence"]) == evidence
        ),
        capture_progress_state_digest=lambda: progress_digest,
        capture_partition_evidence=lambda _dataset: evidence,
    )

    assert result["status"] == "passed"
    assert completed not in [_dataset_identity_for_test(
        item.dataset_kind, item.contract_or_series, item.frequency
    ) for item in calls]
    assert result["datasets"][0]["resumed_from_receipt"] is True


def test_resume_reconciliation_verifies_manifest_payload_and_physical_checksum(
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "canonical"
    file_path = canonical_root / "dataset" / "part.parquet"
    manifest_path = canonical_root / "dataset" / "part.manifest.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"canonical-bytes")
    checksum = hashlib.sha256(b"canonical-bytes").hexdigest()
    dataset = _prepared().datasets_for_contracts(("JM2609",))[0]
    dataset_identity = cli_service._dataset_identity_dict(dataset)
    manifest_payload = {
        "file_checksum": checksum,
        "dataset_key": dataset_identity,
        "partition": {
            "coverage_start": "2026-07-01T00:00:00+00:00",
            "coverage_end": "2026-07-02T00:00:00+00:00",
            "file_uri": "dataset/part.parquet",
            "manifest_uri": "dataset/part.manifest.json",
        },
        "schema": "canonical-manifest-v1",
    }
    manifest_digest = hashlib.sha256(
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps({**manifest_payload, "manifest_digest": manifest_digest}),
        encoding="utf-8",
    )
    partition = SimpleNamespace(
        coverage_start=datetime(2026, 7, 1, tzinfo=UTC),
        coverage_end=datetime(2026, 7, 2, tzinfo=UTC),
        manifest_digest=manifest_digest,
        checksum=checksum,
        file_uri="dataset/part.parquet",
        manifest_uri="dataset/part.manifest.json",
    )

    class Catalog:
        def list_partitions(self, _dataset):
            return [partition]

    recorded = {
        "partition_evidence": [
            {
                "coverage_start": partition.coverage_start.isoformat(),
                "coverage_end": partition.coverage_end.isoformat(),
                "manifest_digest": manifest_digest,
                "checksum": checksum,
                "file_uri": partition.file_uri,
                "manifest_uri": partition.manifest_uri,
            }
        ]
    }

    assert cli_service._reconcile_completed_dataset(
        Catalog(), canonical_root, dataset, recorded
    )
    assert not cli_service._verify_partition_evidence(
        canonical_root,
        {**dataset_identity, "contract_or_series": "JM9999"},
        recorded["partition_evidence"][0],
    )
    file_path.write_bytes(b"corrupted")
    assert not cli_service._reconcile_completed_dataset(
        Catalog(), canonical_root, dataset, recorded
    )


def test_execute_apply_fetches_only_missing_verified_mapping_days() -> None:
    first = _mapping(1, "JM2609")
    second = _mapping(2, "JM2610")
    prepared = _prepared_from_verified_mapping((first,))
    mapping_calls: list[dict[str, object]] = []
    reconciled: list[tuple[MainMapRow, ...]] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **kwargs: object) -> MappingSyncResult:
            mapping_calls.append(kwargs)
            return MappingSyncResult(dry_run=False, rows=(second,))

        def sync(self, **kwargs: object) -> SyncResult:
            window = (kwargs["start"], kwargs["end"])
            return SyncResult(False, (window,), (window,), ())

    result = execute_prepared_historical_apply(
        prepared,
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: None,
        rollback=lambda: None,
        reconcile_mapping=lambda rows: reconciled.append(tuple(rows)) or True,
    )

    assert reconciled == [(first,)]
    assert len(mapping_calls) == 1
    assert mapping_calls[0]["start_day"] == date(2026, 7, 2)
    assert mapping_calls[0]["end_day"] == date(2026, 7, 2)
    assert mapping_calls[0]["expected_trading_days"] == (date(2026, 7, 2),)
    assert result["mapping_row_count"] == 2
    assert result["dataset_count"] == 7


def test_execute_apply_fetches_non_contiguous_missing_mapping_day_runs() -> None:
    first = _mapping(1, "JM2609")
    middle = _mapping(2, "JM2610")
    last = _mapping(3, "JM2609")
    prepared = replace(
        _prepared_from_verified_mapping((middle,)),
        end=datetime(2026, 7, 4, tzinfo=UTC),
        mapping_trading_days=(
            date(2026, 7, 1),
            date(2026, 7, 2),
            date(2026, 7, 3),
        ),
        mapping_session_windows=tuple(
            (
                date(2026, 7, day),
                datetime(2026, 7, day, 1, 0, tzinfo=UTC),
                datetime(2026, 7, day, 1, 1, tzinfo=UTC),
            )
            for day in (1, 2, 3)
        ),
    )
    provider_rows = (first, middle, last)
    mapping_requests: list[MainMapRequest] = []
    registered: list[MainMapRow] = []

    class Catalog:
        def register_main_contract_mapping(self, row: MainMapRow) -> None:
            registered.append(row)

    class Adapter:
        def fetch_rank1_map(self, request: MainMapRequest) -> tuple[MainMapRow, ...]:
            mapping_requests.append(request)
            return tuple(
                row
                for row in provider_rows
                if request.start_day <= row.trading_day <= request.end_day
            )

    mapping_synchronizer = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=lambda _dataset, _start, _end: (),
        publish_batch=lambda _batch: (_ for _ in ()).throw(AssertionError()),
    )

    class Synchronizer:
        def sync_rank1_mapping(self, **kwargs: object) -> MappingSyncResult:
            return mapping_synchronizer.sync_rank1_mapping(**kwargs)

        def sync(self, **kwargs: object) -> SyncResult:
            window = (kwargs["start"], kwargs["end"])
            return SyncResult(False, (window,), (window,), ())

    result = execute_prepared_historical_apply(
        prepared,
        synchronizer=Synchronizer(),
        expected_trading_days=(
            date(2026, 7, 1),
            date(2026, 7, 2),
            date(2026, 7, 3),
        ),
        commit=lambda: None,
        rollback=lambda: None,
        reconcile_mapping=lambda rows: tuple(rows) == (middle,),
    )

    assert [
        (request.start_day, request.end_day)
        for request in mapping_requests
    ] == [
        (date(2026, 7, 1), date(2026, 7, 1)),
        (date(2026, 7, 3), date(2026, 7, 3)),
    ]
    assert registered == [first, last]
    assert result["mapping_row_count"] == 3


def test_execute_apply_resumes_after_mapping_commit_before_receipt() -> None:
    first = _mapping(1, "JM2609")
    second = _mapping(2, "JM2610")
    partial = _prepared_from_verified_mapping((first,))
    commits: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            return MappingSyncResult(dry_run=False, rows=(second,))

        def sync(self, **kwargs: object) -> SyncResult:
            window = (kwargs["start"], kwargs["end"])
            return SyncResult(False, (window,), (window,), ())

    class CrashingReceipt:
        def record_mapping(self, **_kwargs: object) -> None:
            raise RuntimeError("simulated receipt interruption")

    with pytest.raises(RuntimeError, match="simulated receipt interruption"):
        execute_prepared_historical_apply(
            partial,
            synchronizer=Synchronizer(),
            expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
            commit=lambda: commits.append("mapping committed"),
            rollback=lambda: None,
            receipt_store=CrashingReceipt(),  # type: ignore[arg-type]
            reconcile_mapping=lambda rows: tuple(rows) == (first,),
        )
    assert commits == ["mapping committed"]

    complete = _prepared_from_verified_mapping((first, second))

    class ResumedSynchronizer(Synchronizer):
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            raise AssertionError("complete verified mapping must not be fetched")

    result = execute_prepared_historical_apply(
        complete,
        synchronizer=ResumedSynchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: None,
        rollback=lambda: None,
        reconcile_mapping=lambda rows: tuple(rows) == (first, second),
    )

    assert result["mapping_row_count"] == 2


@pytest.mark.parametrize(
    "row",
    [
        _mapping(3, "JM2609"),
        _mapping(1, "JM9999"),
    ],
)
def test_execute_apply_rejects_unapproved_verified_mapping_rows(row: MainMapRow) -> None:
    prepared = replace(
        _prepared(),
        verified_mapping_rows=(_mapping_identity(row),),
    )

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            raise AssertionError("invalid verified mapping must fail before fetch")

        def sync(self, **_kwargs: object) -> SyncResult:
            raise AssertionError("invalid verified mapping must fail before data sync")

    with pytest.raises(ValueError, match="historical_apply_mapping_reconciliation_failed"):
        execute_prepared_historical_apply(
            prepared,
            synchronizer=Synchronizer(),
            expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
            commit=lambda: None,
            rollback=lambda: None,
            reconcile_mapping=lambda _rows: True,
        )


def test_execute_apply_commits_mapping_before_exact_direct_dataset_set() -> None:
    calls: list[object] = []
    commits: list[str] = []
    rollbacks: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **kwargs: object) -> MappingSyncResult:
            calls.append(("mapping", kwargs))
            return MappingSyncResult(
                dry_run=False,
                rows=(_mapping(1, "JM2609"), _mapping(2, "JM2610")),
            )

        def sync(self, **kwargs: object) -> SyncResult:
            dataset = kwargs["dataset"]
            calls.append(("dataset", dataset))
            return SyncResult(
                dry_run=False,
                planned_windows=((kwargs["start"], kwargs["end"]),),
                published_windows=((kwargs["start"], kwargs["end"]),),
                gap_windows=(),
            )

    result = execute_prepared_historical_apply(
        _prepared(),
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: commits.append("commit"),
        rollback=lambda: rollbacks.append("rollback"),
    )

    datasets = [entry[1] for entry in calls if entry[0] == "dataset"]
    assert [(item.dataset_kind, item.contract_or_series, item.frequency) for item in datasets] == [
        (DatasetKind.CONTINUOUS, "JM.MAIN", BarFrequency.M1),
        (DatasetKind.CONTINUOUS, "JM.MAIN", BarFrequency.D1),
        (DatasetKind.CONTINUOUS, "JM.MAIN", BarFrequency.W1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2609", BarFrequency.M1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2609", BarFrequency.D1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2610", BarFrequency.M1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2610", BarFrequency.D1),
    ]
    assert len(commits) == 8
    assert rollbacks == []
    assert result["status"] == "passed"
    assert result["mapping_row_count"] == 2
    assert result["dataset_count"] == 7
    assert result["gap_dataset_count"] == 0


def test_execute_apply_uses_only_rank1_mapping_valid_segments_for_actual() -> None:
    calls = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            return MappingSyncResult(
                dry_run=False,
                rows=(_mapping(1, "JM2609"), _mapping(2, "JM2610")),
            )

        def sync(self, **kwargs: object) -> SyncResult:
            calls.append(kwargs)
            window = (kwargs["start"], kwargs["end"])
            return SyncResult(
                dry_run=False,
                planned_windows=(window,),
                published_windows=(window,),
                gap_windows=(),
            )

    execute_prepared_historical_apply(
        _prepared(),
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: None,
        rollback=lambda: None,
    )

    actual = [
        call for call in calls
        if call["dataset"].dataset_kind is DatasetKind.ACTUAL_DOMINANT
    ]
    assert [
        (call["dataset"].contract_or_series, call["start"], call["end"])
        for call in actual
    ] == [
        (
            "JM2609",
            datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
            datetime(2026, 7, 1, 1, 1, tzinfo=UTC),
        ),
        (
            "JM2609",
            datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
            datetime(2026, 7, 1, 1, 1, tzinfo=UTC),
        ),
        (
            "JM2610",
            datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
            datetime(2026, 7, 2, 1, 1, tzinfo=UTC),
        ),
        (
            "JM2610",
            datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
            datetime(2026, 7, 2, 1, 1, tzinfo=UTC),
        ),
    ]


def test_execute_apply_persists_gap_result_and_reports_blocked() -> None:
    commits: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            return MappingSyncResult(
                dry_run=False,
                rows=(_mapping(1, "JM2609"), _mapping(2, "JM2610")),
            )

        def sync(self, **kwargs: object) -> SyncResult:
            window = (kwargs["start"], kwargs["end"])
            dataset = kwargs["dataset"]
            return SyncResult(
                dry_run=False,
                planned_windows=(window,),
                published_windows=() if dataset.frequency is BarFrequency.M1 else (window,),
                gap_windows=(window,) if dataset.frequency is BarFrequency.M1 else (),
            )

    result = execute_prepared_historical_apply(
        _prepared(),
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: commits.append("commit"),
        rollback=lambda: (_ for _ in ()).throw(AssertionError("must not roll back committed gaps")),
    )

    assert result["status"] == "blocked"
    assert result["gap_dataset_count"] == 3
    assert len(commits) == 8


def test_execute_apply_rolls_back_current_transaction_on_unexpected_error() -> None:
    rollbacks: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            return MappingSyncResult(
                dry_run=False,
                rows=(_mapping(1, "JM2609"), _mapping(2, "JM2610")),
            )

        def sync(self, **_kwargs: object) -> SyncResult:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        execute_prepared_historical_apply(
            _prepared(),
            synchronizer=Synchronizer(),
                expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
            commit=lambda: None,
            rollback=lambda: rollbacks.append("rollback"),
        )

    assert rollbacks == ["rollback"]


def test_actual_dominant_sessions_keep_only_exact_rank1_contract_days() -> None:
    dataset = next(
        item
        for item in _prepared().datasets_for_contracts(("JM2609",))
        if item.frequency is BarFrequency.M1
        and item.dataset_kind is DatasetKind.ACTUAL_DOMINANT
    )
    sessions = tuple(
        TradingSessionCoverage(
            trading_day=date(2026, 7, day),
            start=datetime(2026, 7, day, 1, 0, tzinfo=UTC),
            end=datetime(2026, 7, day, 1, 1, tzinfo=UTC),
            expected_bar_ends=(datetime(2026, 7, day, 1, 1, tzinfo=UTC),),
        )
        for day in (1, 2)
    )

    filtered = filter_actual_dominant_sessions(
        dataset,
        sessions,
        actual_contract_for_day=lambda trading_day: (
            "JM2609" if trading_day.day == 1 else "JM2610"
        ),
    )

    assert tuple(item.trading_day for item in filtered) == (date(2026, 7, 1),)


def test_apply_executor_writes_only_direct_canonical_partitions_and_mapping(
    tmp_path: Path,
) -> None:
    facts = _facts()
    state = {
        **facts["current_state"],
        "trading_days": ["2026-07-01"],
        "session_windows": [facts["current_state"]["session_windows"][0]],
    }
    state.pop("state_digest")
    state["state_digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    facts["current_state"] = state
    facts["mapping_write_plan"] = {
        **facts["mapping_write_plan"],
        "start_day": "2026-07-01",
        "end_day": "2026-07-01",
        "trading_days": ["2026-07-01"],
    }
    facts["scope"] = {
        **facts["scope"],
        "window": {
            "start": "2026-06-30T00:00:00+00:00",
            "end": "2026-07-03T00:00:00+00:00",
        },
    }
    facts["write_set"] = {
        **facts["write_set"],
        "canonical_root": str(
            tmp_path / "data" / "parquet" / "data-core-v2" / "canonical"
        ),
        "staging_root": str(
            tmp_path / "data" / "parquet" / "data-core-v2" / "staging"
        ),
        "partial_apply_receipt": str(
            tmp_path
            / "data"
            / "parquet"
            / "data-core-v2"
            / "receipts"
            / "apply.json"
        ),
    }
    packet = build_apply_approval_packet(bound_facts=facts)
    prepared = prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
    )
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'metadata.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()

    def sessions(dataset, start, end):
        if dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT:
            bar_end = end
            coverage_start = start
        elif dataset.frequency is BarFrequency.M1:
            bar_end = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
            coverage_start = bar_end - timedelta(minutes=1)
        else:
            bar_end = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
            coverage_start = bar_end - timedelta(microseconds=1)
        return (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=coverage_start,
                end=bar_end,
                expected_bar_ends=(bar_end,),
            ),
        )

    class Adapter:
        def fetch_rank1_map(self, _request):
            return (_mapping(1, "JM2609"),)

        def fetch_bars(self, request):
            bars = tuple(
                CanonicalBar(
                    provider="rqdata",
                    dataset_kind=request.dataset.dataset_kind,
                    symbol="jm",
                    contract_or_series=request.dataset.contract_or_series,
                    frequency=request.dataset.frequency,
                    bar_end=bar_end,
                    trading_day=session_coverage.trading_day,
                    open=Decimal("100"),
                    high=Decimal("102"),
                    low=Decimal("99"),
                    close=Decimal("101"),
                    volume=Decimal("10"),
                    turnover=Decimal("1000"),
                    open_interest=Decimal("20"),
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                )
                for session_coverage in request.sessions
                for bar_end in session_coverage.expected_bar_ends
            )
            return ProviderBarBatch(
                request=request,
                bars=bars,
                data_version=f"fake-{request.dataset.frequency.value}-20260701",
            )

    prepared.canonical_root.parent.parent.mkdir(parents=True)
    prepare_historical_apply_roots(prepared)
    store = CanonicalStore(
        staging_root=prepared.staging_root,
        canonical_root=prepared.canonical_root,
        metadata_session_factory=factory,
    )
    synchronizer = HistoricalSynchronizer(
        catalog=HistoricalCatalog(session),
        adapter=Adapter(),
        session_provider=sessions,
        publish_batch=CanonicalBatchPublisher(store),
    )

    result = execute_prepared_historical_apply(
        prepared,
        synchronizer=synchronizer,
        expected_trading_days=(date(2026, 7, 1),),
        commit=session.commit,
        rollback=session.rollback,
    )

    assert result["status"] == "passed", result
    assert result["dataset_count"] == 5
    assert session.scalar(select(func.count()).select_from(MarketDataset)) == 5
    assert session.scalar(select(func.count()).select_from(MarketPartition)) == 5
    assert session.scalar(select(func.count()).select_from(MainContractMap)) == 1
    assert len(tuple(prepared.canonical_root.rglob("*.parquet"))) == 5
    assert not tuple(prepared.canonical_root.rglob("*5m*"))
    session.close()
    engine.dispose()


def test_migrate_apply_runner_rechecks_facts_before_writer_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts()
    packet = build_apply_approval_packet(bound_facts=facts)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(cli_service, "inventory_jm_legacy_assets", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        cli_service,
        "build_jm_migration_plan",
        lambda _inventory: {"plan_digest": facts["plan_digest"]},
    )
    monkeypatch.setattr(
        cli_service,
        "build_jm_apply_bound_facts",
        lambda *_args, **_kwargs: facts,
    )
    monkeypatch.setattr(
        cli_service,
        "build_jm_current_state",
        lambda *_args, **_kwargs: facts["current_state"],
    )
    monkeypatch.setattr(
        cli_service,
        "_loaded_source_root",
        lambda: Path("/tmp/project"),
    )
    monkeypatch.setattr(
        cli_service,
        "_git_state",
        lambda _root: {"head": facts["task_head"], "clean": True},
    )
    monkeypatch.setattr(
        cli_service,
        "_postgresql_target",
        lambda _session: facts["write_set"]["postgresql_target"],
    )
    monkeypatch.setattr(
        cli_service,
        "_require_data_core_revision",
        lambda _session: calls.append("revision"),
        raising=False,
    )
    monkeypatch.setattr(
        cli_service,
        "_expected_jm_trading_days",
        lambda *_args, **_kwargs: (date(2026, 7, 1), date(2026, 7, 2)),
        raising=False,
    )

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("client")

    class Adapter:
        def __init__(self, _client: object) -> None:
            calls.append("adapter")

    class Store:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("store")

    class Receipt:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("receipt")

        def record_mapping(self, **_kwargs: object) -> None:
            calls.append("receipt_mapping")

        def snapshot(self):
            return {
                "schema_version": 1,
                "bound_facts_digest": packet["packet_hash"],
                "progress_state_digest": None,
                "mapping": None,
                "datasets": {},
            }

        def completed_mapping(self):
            return None

        def completed_dataset(self, _dataset: object):
            return None

        def dataset_completed(self, _dataset: object) -> bool:
            return False

        def record_dataset(self, **_kwargs: object) -> None:
            calls.append("receipt_dataset")

    class Publisher:
        def __init__(self, _store: object) -> None:
            pass

    class Synchronizer:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("synchronizer")

        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            calls.append("mapping")
            return MappingSyncResult(
                dry_run=False,
                rows=(_mapping(1, "JM2609"), _mapping(2, "JM2610")),
            )

        def sync(self, **_kwargs: object) -> SyncResult:
            calls.append("sync")
            return SyncResult(
                dry_run=False,
                planned_windows=(),
                published_windows=(),
                gap_windows=(),
            )

    monkeypatch.setattr(cli_service, "RqDataClient", Client, raising=False)
    monkeypatch.setattr(cli_service, "CanonicalRQDataAdapter", Adapter, raising=False)
    monkeypatch.setattr(cli_service, "CanonicalStore", Store, raising=False)
    monkeypatch.setattr(cli_service, "CanonicalBatchPublisher", Publisher, raising=False)
    monkeypatch.setattr(cli_service, "HistoricalSynchronizer", Synchronizer, raising=False)
    monkeypatch.setattr(cli_service, "PartialApplyReceiptStore", Receipt, raising=False)
    monkeypatch.setattr(
        cli_service,
        "_partition_evidence",
        lambda *_args, **_kwargs: (),
        raising=False,
    )
    monkeypatch.setattr(
        cli_service,
        "_reconcile_mapping",
        lambda *_args, **_kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(
        cli_service,
        "prepare_historical_apply_roots",
        lambda _prepared: calls.append("roots"),
        raising=False,
    )

    class Session:
        def commit(self) -> None:
            calls.append("commit")

        def rollback(self) -> None:
            calls.append("rollback")

        def get_bind(self):
            return object()

    args = SimpleNamespace(
        project_root=Path("/tmp/project"),
        legacy_root=Path("/tmp/legacy"),
        canonical_root=Path(facts["write_set"]["canonical_root"]),
        staging_root=Path(facts["write_set"]["staging_root"]),
        start=facts["scope"]["window"]["start"],
        end=facts["scope"]["window"]["end"],
        approval_packet=packet_path,
        approval_hash=packet["packet_hash"],
    )

    result = cli_service.run_data_core_command(
        "migrate.apply",
        Session(),
        args,
    )

    assert result["status"] == "passed"
    assert calls[:6] == ["revision", "receipt", "roots", "client", "adapter", "store"]
    assert calls.count("sync") == 7
    assert "mapping" not in calls
    assert "receipt_mapping" in calls
    assert "rollback" not in calls


def test_migration_gate_rejects_a_different_checkout_before_inventory_or_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_service,
        "_loaded_source_root",
        lambda: Path("/tmp/loaded-checkout"),
        raising=False,
    )
    monkeypatch.setattr(
        cli_service,
        "inventory_jm_legacy_assets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must fail before inventory")
        ),
    )

    with pytest.raises(
        HistoricalApplyGateError,
        match="loaded_source_checkout_mismatch",
    ):
        cli_service.run_data_core_command(
            "migrate.plan",
            object(),  # type: ignore[arg-type]
            SimpleNamespace(
                project_root=Path("/tmp/caller-supplied-checkout"),
                legacy_root=Path("/tmp/legacy"),
                canonical_root=Path("/tmp/data/parquet/data-core-v2/canonical"),
                staging_root=Path("/tmp/data/parquet/data-core-v2/staging"),
                start="2026-07-01T00:00:00Z",
                end="2026-07-03T00:00:00Z",
            ),
        )
