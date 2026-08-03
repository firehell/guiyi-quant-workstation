from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.data_core import cli_service as cli_service_module
from app.data_core import task07
from app.data_core.task07 import (
    AssetDisposition,
    Task07Asset,
    apply_retirement_plan,
    build_approval_packet,
    build_inventory_index,
    build_migration_plan,
    build_retirement_plan,
    build_write_targets,
    canonical_digest,
    classify_asset,
    collect_task07_assets,
    load_inventory_evidence,
    scan_task07_references,
    verify_exact_approval,
    verify_task07_preflight_receipt,
    write_inventory_evidence,
)
from app.data_core.cli_service import run_data_core_command
from app.db.base import Base
from app.guiyi_cli.main import main
from app.models.data_center import Instrument, TradingCalendar, TradingSession


def _asset(**overrides: object) -> Task07Asset:
    values: dict[str, object] = {
        "market_data_file_id": 1,
        "provider": "rqdata",
        "data_type": "bars",
        "symbol": "jm",
        "contract_or_series": "JM.MAIN",
        "frequency": "1m",
        "data_role": "primary",
        "quality_status": "passed",
        "file_path": "/data/parquet/canonical/bars/jm.parquet",
        "source_scope": "approved_data_root",
        "content_gate_status": "passed",
        "checksum": "a" * 64,
        "file_size_bytes": 10,
        "physical_exists": True,
        "physical_checksum": "a" * 64,
        "catalog_checksum": "a" * 64,
        "dataset_kind": "continuous",
        "coverage_start": "2026-01-01T00:00:00+00:00",
        "coverage_end": "2026-01-02T00:00:00+00:00",
        "row_count": 10,
        "data_version": "legacy-v1",
    }
    values.update(overrides)
    return Task07Asset(**values)


def _write_targets(root: Path = Path("/tmp/task07-test")) -> dict[str, object]:
    return {
        "staging_root": str((root / "staging").resolve(strict=False)),
        "canonical_root": str((root / "canonical").resolve(strict=False)),
        "postgresql_target": {
            "drivername": "postgresql+psycopg",
            "username": "task07_test",
            "host": "localhost",
            "port": 5432,
            "database": "task07_test",
        },
        "protected_roots": [str((root / "evidence").resolve(strict=False))],
    }


def test_parquet_content_gate_reads_file_inside_hive_style_directories(
    tmp_path: Path,
) -> None:
    path = tmp_path / "provider=rqdata" / "period=1m" / "bars.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "provider": ["rqdata"],
                "period": ["1m"],
                "datetime": [datetime(2026, 7, 31, 9, 1)],
                "trading_day": [date(2026, 7, 31)],
            }
        ),
        path,
    )

    assert (
        task07._parquet_content_gate(path, data_type="bars", frequency="1m")
        == "passed"
    )


def test_inventory_classifies_only_passed_rqdata_direct_bars_as_trusted() -> None:
    assets = [
        _asset(market_data_file_id=1),
        _asset(market_data_file_id=2, quality_status="warning"),
        _asset(market_data_file_id=3, frequency="15m"),
        _asset(market_data_file_id=4, provider="tqsdk"),
        _asset(
            market_data_file_id=5,
            file_path="/Volumes/扩展盘/GuiyiApprovals/task/file.parquet",
            source_scope="protected_evidence_root",
        ),
        _asset(market_data_file_id=6, physical_checksum="b" * 64),
        _asset(market_data_file_id=7, data_role="candidate"),
        _asset(
            market_data_file_id=8,
            symbol="rb",
            contract_or_series="JM2609",
            dataset_kind="actual_dominant",
        ),
        _asset(market_data_file_id=9, content_gate_status="trading_day_weekend_conflict"),
    ]

    index = build_inventory_index(assets, base_sha="1" * 40, database_revision="20260802_0031")

    assert [item["disposition"] for item in index["assets"]] == [
        AssetDisposition.KEEP_CANONICAL_VERIFIED,
        AssetDisposition.REGISTER_DATA_GAP,
        AssetDisposition.EXCLUDE_DERIVED,
        AssetDisposition.RETIREMENT_CANDIDATE,
        AssetDisposition.PROTECTED_EVIDENCE_SOURCE,
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.RETIREMENT_CANDIDATE,
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.REGISTER_DATA_GAP,
    ]
    assert index["eligible_asset_count"] == 1
    assert index["blocked_asset_count"] == 2
    assert index["deletion_authorized"] is False


def test_protected_evidence_stays_protected_when_physical_content_is_missing() -> None:
    index = build_inventory_index(
        [
            _asset(
                file_path="/Volumes/扩展盘/GuiyiApprovals/task/file.parquet",
                source_scope="protected_evidence_root",
                physical_exists=False,
                physical_checksum=None,
            )
        ],
        base_sha="1" * 40,
        database_revision="20260802_0031",
    )

    assert index["assets"][0]["disposition"] == AssetDisposition.PROTECTED_EVIDENCE_SOURCE
    assert index["eligible_asset_count"] == 0


def test_protected_evidence_never_becomes_a_retirement_candidate() -> None:
    protected = _asset(
        source_scope="protected_evidence_root",
        provider="unknown",
        frequency="5m",
        quality_status="failed",
        physical_exists=False,
        checksum=None,
        physical_checksum=None,
    )

    assert classify_asset(protected) == AssetDisposition.PROTECTED_EVIDENCE_SOURCE


def test_protected_evidence_never_enters_a_migration_batch() -> None:
    index = build_inventory_index(
        [
            _asset(market_data_file_id=1, catalog_checksum=None),
            _asset(
                market_data_file_id=2,
                file_path="/Volumes/扩展盘/GuiyiApprovals/task/file.parquet",
                source_scope="protected_evidence_root",
                catalog_checksum=None,
            ),
        ],
        base_sha="1" * 40,
        database_revision="20260802_0031",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert plan["protected_evidence_count"] == 1
    assert plan["batches"][0]["source_ids"] == [1]
    assert plan["batches"][0]["protected_evidence_ids"] == []


def test_source_outside_approved_roots_is_not_hashed_or_migrated(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"outside")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, provider TEXT, data_type TEXT, "
            "instrument_symbol TEXT, contract_code TEXT, period TEXT, start_time TEXT, end_time TEXT, "
            "file_path TEXT, file_size_bytes INTEGER, checksum TEXT, data_version TEXT, row_count INTEGER, "
            "data_role TEXT, quality_status TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, provider TEXT, dataset_kind TEXT, symbol TEXT, "
            "contract_or_series TEXT, frequency TEXT, adjustment TEXT, schema_version TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, dataset_id INTEGER, file_uri TEXT, checksum TEXT, "
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER)"
        )
        connection.execute(
            text(
                "INSERT INTO market_data_files VALUES "
                "(1,'rqdata','bars','jm','JM.MAIN','1m','2026-01-01','2026-01-02',:path,7,:checksum,'legacy-v1',1,'primary','passed')"
            ),
            {"path": str(outside), "checksum": "a" * 64},
        )

    with Session(engine) as session:
        assets = list(
            collect_task07_assets(
                session,
                data_root=approved,
                canonical_root=approved,
                inspect_content=False,
            )
        )

    assert len(assets) == 1
    assert assets[0].source_scope == "outside_approved_roots"
    assert assets[0].physical_checksum is None
    assert classify_asset(assets[0]) == AssetDisposition.RETIREMENT_CANDIDATE


def test_symlink_inside_protected_root_cannot_become_a_migration_source(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    canonical_root = tmp_path / "canonical"
    protected_root = tmp_path / "protected-evidence"
    for path in (data_root, canonical_root, protected_root):
        path.mkdir()
    target = data_root / "bars.parquet"
    payload = b"trusted-looking-bars"
    target.write_bytes(payload)
    registered = protected_root / "linked.parquet"
    registered.symlink_to(target)
    checksum = sha256(payload).hexdigest()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, provider TEXT, data_type TEXT, "
            "instrument_symbol TEXT, contract_code TEXT, period TEXT, start_time TEXT, end_time TEXT, "
            "file_path TEXT, file_size_bytes INTEGER, checksum TEXT, data_version TEXT, row_count INTEGER, "
            "data_role TEXT, quality_status TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, provider TEXT, dataset_kind TEXT, symbol TEXT, "
            "contract_or_series TEXT, frequency TEXT, adjustment TEXT, schema_version TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, dataset_id INTEGER, file_uri TEXT, checksum TEXT, "
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER)"
        )
        connection.execute(
            text(
                "INSERT INTO market_data_files VALUES "
                "(1,'rqdata','bars','jm','JM.MAIN','1m','2026-01-01','2026-01-02',"
                ":path,:size,:checksum,'legacy-v1',1,'primary','passed')"
            ),
            {"path": str(registered), "size": len(payload), "checksum": checksum},
        )

    with Session(engine) as session:
        asset = next(
            iter(
                collect_task07_assets(
                    session,
                    data_root=data_root,
                    canonical_root=canonical_root,
                    protected_roots=(protected_root,),
                    inspect_content=False,
                )
            )
        )

    assert asset.source_scope == "protected_evidence_root"
    assert classify_asset(asset) == AssetDisposition.PROTECTED_EVIDENCE_SOURCE


def test_inventory_evidence_is_sharded_with_recomputable_index(tmp_path: Path) -> None:
    index = write_inventory_evidence(
        [_asset(market_data_file_id=value, checksum=f"{value:064x}", physical_checksum=f"{value:064x}", catalog_checksum=f"{value:064x}") for value in range(1, 6)],
        evidence_root=tmp_path,
        base_sha="1" * 40,
        database_revision="20260802_0031",
        shard_size=2,
    )

    assert index["asset_count"] == 5
    assert [item["row_count"] for item in index["shards"]] == [2, 2, 1]
    assert all(len(item["sha256"]) == 64 for item in index["shards"])
    assert json.loads((tmp_path / "inventory-index.json").read_text())["inventory_digest"] == index["inventory_digest"]
    assert sum(1 for path in tmp_path.glob("assets-*.jsonl")) == 3


def test_reference_scan_separates_runtime_tests_and_historical_docs(tmp_path: Path) -> None:
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "consumer.py").write_text(
        "from app.models.data_center import ProfileActiveBinding\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_legacy.py").write_text(
        "assert ProfileActiveBinding\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "snapshot.md").write_text(
        "ProfileActiveBinding historical snapshot\n",
        encoding="utf-8",
    )

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["truncated"] is False
    assert report["state_counts"] == {
        "active": 1,
        "historical_non_active": 2,
        "review_required": 0,
    }
    assert len(report["references_digest"]) == 64
    assert all("line_text" not in item for item in report["records"])
    assert all(item["classification_reason"] for item in report["records"])


def test_detached_runtime_executable_reference_is_not_hidden_as_history(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    target = runtime / "services" / "quant-api" / "app" / "api"
    target.mkdir(parents=True)
    (target / "market.py").write_text("reader = MarketDataReader()\n", encoding="utf-8")

    report = scan_task07_references([("detached_runtime", runtime)])

    assert report["state_counts"] == {
        "active": 1,
        "historical_non_active": 0,
        "review_required": 0,
    }
    assert report["records"][0]["classification_reason"] == "detached_runtime_executable_reference"


def test_detached_runtime_frozen_module_rule_cannot_hide_executable_reader(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    target = runtime / "services" / "quant-api" / "app" / "services"
    target.mkdir(parents=True)
    (target / "htdy_realtime_snapshot.py").write_text(
        "from app.services.market_data_reader import MarketDataReader\n",
        encoding="utf-8",
    )

    report = scan_task07_references([("detached_runtime", runtime)])

    assert report["state_counts"]["active"] == 1
    assert report["records"][0]["classification_reason"] == "detached_runtime_executable_reference"


def test_write_targets_bind_exact_database_and_reject_protected_overlap(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    staging = tmp_path / "staging"
    evidence = tmp_path / "evidence"
    database = _write_targets(tmp_path)["postgresql_target"]
    targets = build_write_targets(
        staging_root=staging,
        canonical_root=canonical,
        postgresql_target=database,
        inventory_scope={
            "canonical_root": str(canonical),
            "protected_roots": [str(evidence)],
        },
    )
    assert targets == _write_targets(tmp_path)

    with pytest.raises(ValueError, match="TASK07_PROTECTED_WRITE_TARGET"):
        build_write_targets(
            staging_root=evidence / "staging",
            canonical_root=canonical,
            postgresql_target=database,
            inventory_scope={
                "canonical_root": str(canonical),
                "protected_roots": [str(evidence)],
            },
        )


def test_reference_report_is_hash_bound_to_inventory_evidence(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "consumer.py").write_text("MarketDataReader\n", encoding="utf-8")
    evidence_root = tmp_path / "evidence"
    report = scan_task07_references([("checkout", source_root)])
    write_inventory_evidence(
        [_asset()],
        evidence_root=evidence_root,
        base_sha="1" * 40,
        database_revision="20260802_0031",
        reference_report=report,
    )

    loaded = load_inventory_evidence(evidence_root / "inventory-index.json")

    assert loaded["reference_index"]["record_count"] == 1
    assert len(loaded["references"]) == 1


def test_database_inventory_uses_stable_keyset_and_physical_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"trusted-bars")
    checksum = "b0f116d8d12dd3c480dd7e391b8c3edd04190b56259071ec96bec52b8c3c8ee8"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, provider TEXT, data_type TEXT, "
            "instrument_symbol TEXT, contract_code TEXT, period TEXT, start_time TEXT, end_time TEXT, "
            "file_path TEXT, file_size_bytes INTEGER, checksum TEXT, data_version TEXT, row_count INTEGER, "
            "data_role TEXT, quality_status TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, provider TEXT, dataset_kind TEXT, symbol TEXT, "
            "contract_or_series TEXT, frequency TEXT, adjustment TEXT, schema_version TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, dataset_id INTEGER, file_uri TEXT, checksum TEXT, "
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER)"
        )
        connection.execute(
            text(
                "INSERT INTO market_data_files VALUES "
                "(2,'rqdata','bars','rb','RB.MAIN','1m','2026-01-01','2026-01-02',:path,12,:checksum,'legacy-v1',1,'primary','passed'),"
                "(1,'rqdata','bars','jm','JM.MAIN','1m','2026-01-01','2026-01-02',:path,12,:checksum,'legacy-v1',1,'primary','passed')"
            ),
            {"path": str(source), "checksum": checksum},
        )
        connection.exec_driver_sql(
            "INSERT INTO market_datasets VALUES (1,'rqdata','continuous','jm','JM.MAIN','1m','none','canonical-bar-v1')"
        )
        connection.execute(
            text("INSERT INTO market_partitions VALUES (1,1,'source.parquet',:checksum,'2026-01-01','2026-01-02',1)"),
            {"checksum": checksum},
        )

    with Session(engine) as session:
        assets = list(
            collect_task07_assets(
                session,
                data_root=tmp_path,
                canonical_root=tmp_path,
                page_size=1,
                inspect_content=False,
            )
        )

    assert [item.market_data_file_id for item in assets] == [1, 2, 2_000_000_001]
    assert assets[0].catalog_checksum == checksum
    assert assets[1].catalog_checksum is None
    assert all(item.physical_checksum == checksum for item in assets)
    assert classify_asset(assets[2]) == AssetDisposition.KEEP_CANONICAL_VERIFIED


def test_inventory_keyset_jsonl_reload_and_plan_digest_are_stable_above_six_hundred_thousand_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shared.parquet"
    source.write_bytes(b"derived")
    (tmp_path / "canonical").mkdir()
    checksum = sha256(source.read_bytes()).hexdigest()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, provider TEXT, data_type TEXT, "
            "instrument_symbol TEXT, contract_code TEXT, period TEXT, start_time TEXT, end_time TEXT, "
            "file_path TEXT, file_size_bytes INTEGER, checksum TEXT, data_version TEXT, row_count INTEGER, "
            "data_role TEXT, quality_status TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, provider TEXT, dataset_kind TEXT, symbol TEXT, "
            "contract_or_series TEXT, frequency TEXT, adjustment TEXT, schema_version TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, dataset_id INTEGER, file_uri TEXT, checksum TEXT, "
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER)"
        )
        connection.execute(
            text(
                "WITH RECURSIVE seq(id) AS (VALUES(1) UNION ALL SELECT id+1 FROM seq WHERE id<600001) "
                "INSERT INTO market_data_files "
                "SELECT id,'rqdata','bars','jm','JM.MAIN','5m','2026-01-01','2026-01-02',"
                ":path,7,:checksum,'legacy-v1',1,'primary','passed' FROM seq"
            ),
            {"path": str(source), "checksum": checksum},
        )

    page_queries = 0

    @event.listens_for(engine, "before_cursor_execute")
    def count_keyset_queries(_conn, _cursor, statement, _parameters, _context, _many) -> None:
        nonlocal page_queries
        if "FROM market_data_files WHERE id >" in statement and "ORDER BY id" in statement:
            page_queries += 1

    monkeypatch.setattr(
        task07,
        "_asset_record",
        lambda asset: {
            "market_data_file_id": asset.market_data_file_id,
            "disposition": AssetDisposition.EXCLUDE_DERIVED.value,
        },
    )

    plans = []
    for name in ("first", "second"):
        with Session(engine) as session:
            index = write_inventory_evidence(
                collect_task07_assets(
                    session,
                    data_root=tmp_path,
                    canonical_root=tmp_path / "canonical",
                    page_size=50_000,
                    inspect_content=False,
                ),
                evidence_root=tmp_path / name,
                base_sha="2" * 40,
                database_revision="20260802_0031",
                shard_size=50_000,
            )
        loaded = load_inventory_evidence(tmp_path / name / "inventory-index.json")
        plans.append(build_migration_plan(loaded, write_targets=_write_targets(tmp_path)))
        assert index["asset_count"] == 600_001
        assert loaded["asset_count"] == 600_001
        assert len(index["shards"]) == 13
        assert index["truncated"] is False

    assert page_queries == 28
    assert plans[0]["assets_digest"] == plans[1]["assets_digest"]
    assert plans[0]["plan_digest"] == plans[1]["plan_digest"]


def test_migration_plan_batches_deterministically_and_never_requests_rqdata() -> None:
    index = build_inventory_index(
        [
            _asset(
                market_data_file_id=1,
                row_count=10,
                data_version="legacy-v1",
                catalog_checksum=None,
            ),
            _asset(market_data_file_id=2, symbol="rb", contract_or_series="RB.MAIN"),
        ],
        base_sha="3" * 40,
        database_revision="20260802_0031",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert [batch["batch_key"] for batch in plan["batches"]] == [
        "jm:continuous:1m",
        "rb:continuous:1m",
    ]
    assert plan["batches"][0]["sources"][0]["row_count"] == 10
    assert plan["batches"][0]["sources"][0]["data_version"] == "legacy-v1"
    assert plan["batches"][0]["sources"][0]["contract_or_series"] == "JM.MAIN"
    assert plan["calls_rqdata"] is False
    assert plan["writes_authorized"] is False
    assert len(plan["plan_digest"]) == 64


def test_migration_plan_with_any_conflict_cannot_emit_approval_eligible_scope() -> None:
    index = build_inventory_index(
        [_asset(physical_checksum="b" * 64)],
        base_sha="3" * 40,
        database_revision="20260802_0031",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert plan["blocked_asset_count"] == 1
    assert plan["approval_eligible"] is False
    assert plan["gate_status"] == "BLOCKED_AT_KLINE_DATA_GATE"
    assert plan["provider_request_proposal"]["request_count"] == 1
    assert plan["provider_request_proposal"]["provider_call_authorized"] is False
    assert plan["provider_request_proposal"]["requests"][0]["window"] == {
        "start": "2026-01-01T00:00:00+00:00",
        "end": "2026-01-02T00:00:00+00:00",
    }


def test_kline_approval_packet_is_bound_to_one_deterministic_batch_and_write_target(
    tmp_path: Path,
) -> None:
    index = build_inventory_index(
        [
            _asset(market_data_file_id=1, catalog_checksum=None),
            _asset(
                market_data_file_id=2,
                symbol="rb",
                contract_or_series="RB.MAIN",
                catalog_checksum=None,
            ),
        ],
        base_sha="3" * 40,
        database_revision="20260802_0031",
    )
    plan = build_migration_plan(index, write_targets=_write_targets(tmp_path))

    packet = build_approval_packet(
        plan,
        command="data.task07.apply",
        batch_key="jm:continuous:1m",
    )

    assert packet["bound_facts"]["batch_key"] == "jm:continuous:1m"
    assert packet["bound_facts"]["batch_digest"] == plan["batches"][0]["batch_digest"]
    assert packet["bound_facts"]["write_targets"] == _write_targets(tmp_path)
    assert "rb:continuous:1m" not in json.dumps(packet)

    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    drifted_facts = deepcopy(packet["bound_facts"])
    drifted_facts["write_targets"]["canonical_root"] = str(tmp_path / "other")
    with pytest.raises(ValueError, match="TASK07_APPROVAL_FACTS_DRIFT"):
        verify_exact_approval(
            packet_path,
            approval_hash=canonical_digest(packet),
            expected_command="data.task07.apply",
            current_facts=drifted_facts,
        )

    tampered = deepcopy(plan)
    tampered["batches"][0]["sources"][0]["file_path"] = "/tampered.parquet"
    try:
        build_approval_packet(
            tampered,
            command="data.task07.apply",
            batch_key="jm:continuous:1m",
        )
    except ValueError as exc:
        assert str(exc) == "TASK07_BATCH_DIGEST_MISMATCH"
    else:  # pragma: no cover
        raise AssertionError("tampered batch must fail")


def test_batch_approval_rejects_tampered_kline_gate_controls() -> None:
    index = build_inventory_index(
        [
            _asset(market_data_file_id=1, catalog_checksum=None),
            _asset(
                market_data_file_id=2,
                physical_checksum="b" * 64,
                catalog_checksum=None,
            ),
        ],
        base_sha="3" * 40,
        database_revision="20260802_0031",
    )
    plan = build_migration_plan(index)
    assert plan["approval_eligible"] is False

    tampered = deepcopy(plan)
    tampered["approval_eligible"] = True
    tampered["gate_status"] = "exact_owner_approval_required"
    try:
        build_approval_packet(
            tampered,
            command="data.task07.apply",
            batch_key="jm:continuous:1m",
        )
    except ValueError as exc:
        assert str(exc) in {"TASK07_PLAN_CONTROL_DRIFT", "TASK07_PLAN_DIGEST_MISMATCH"}
    else:  # pragma: no cover
        raise AssertionError("tampered K-line gate must fail")


def test_retirement_plan_treats_completed_history_as_non_active_and_binds_before_image() -> None:
    plan = build_retirement_plan(
        base_sha="4" * 40,
        database_revision="20260802_0031",
        relations=[
            {"table": "backtest_tasks", "id": 1, "status": "success"},
            {
                "table": "profile_active_bindings",
                "id": 2,
                "binding_status": "active",
                "superseded_at": None,
            },
            {"table": "signal_scan_tasks", "id": 3, "status": "pending"},
            {"table": "strategy_signals", "id": 4, "status": "entry_signal", "is_active": True},
        ],
    )

    assert plan["historical_non_active_count"] == 1
    assert [item["table"] for item in plan["updates"]] == [
        "profile_active_bindings",
        "signal_scan_tasks",
        "strategy_signals",
    ]
    assert plan["deletes"] == []
    assert plan["deletion_authorized"] is False
    assert len(plan["before_image_digest"]) == 64


def test_exact_approval_fails_on_any_bound_fact_drift(tmp_path: Path) -> None:
    packet = {
        "schema_version": 1,
        "command": "data.task07.apply",
        "writes_authorized": True,
        "bound_facts": {"base_sha": "5" * 40, "plan_digest": "a" * 64},
    }
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    approval_hash = verify_exact_approval.digest_packet(packet)
    verified = verify_exact_approval(
        packet_path,
        approval_hash=approval_hash,
        expected_command="data.task07.apply",
        current_facts=packet["bound_facts"],
    )
    assert verified == packet

    drifted = {"base_sha": "5" * 40, "plan_digest": "b" * 64}
    try:
        verify_exact_approval(
            packet_path,
            approval_hash=approval_hash,
            expected_command="data.task07.apply",
            current_facts=drifted,
        )
    except ValueError as exc:
        assert str(exc) == "TASK07_APPROVAL_FACTS_DRIFT"
    else:  # pragma: no cover - mutation guard
        raise AssertionError("drift must fail closed")


def test_apply_gate_rejects_tampered_preflight_receipt(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"source")
    checksum = "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d"
    plan = build_migration_plan(
        build_inventory_index(
            [
                _asset(
                    catalog_checksum=None,
                    file_path=str(source),
                    checksum=checksum,
                    physical_checksum=checksum,
                )
            ],
            base_sha="5" * 40,
            database_revision="20260802_0031",
        ),
        write_targets=_write_targets(tmp_path),
    )
    packet = build_approval_packet(
        plan,
        command="data.task07.apply",
        batch_key="jm:continuous:1m",
    )
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    receipt = task07.build_preflight_receipt(
        plan,
        packet_path=packet_path,
        approval_hash=verify_exact_approval.digest_packet(packet),
        current_base_sha="5" * 40,
        current_database_revision="20260802_0031",
        batch_key="jm:continuous:1m",
        current_write_targets=_write_targets(tmp_path),
    )
    receipt["source_count"] = 99
    receipt_path = tmp_path / "preflight.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="TASK07_PREFLIGHT_RECEIPT_DRIFT"):
        verify_task07_preflight_receipt(
            receipt_path,
            receipt_hash=canonical_digest(receipt),
            plan=plan,
            batch_key="jm:continuous:1m",
            current_base_sha="5" * 40,
            current_database_revision="20260802_0031",
            current_write_targets=_write_targets(tmp_path),
        )


def test_retirement_apply_updates_only_exact_rows_and_preserves_history(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE profile_active_bindings "
            "(id INTEGER PRIMARY KEY, binding_status TEXT, superseded_at TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE signal_scan_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.exec_driver_sql("CREATE TABLE data_download_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.exec_driver_sql("CREATE TABLE strategy_signals (id INTEGER PRIMARY KEY, status TEXT, is_active BOOLEAN)")
        connection.exec_driver_sql(
            "INSERT INTO profile_active_bindings VALUES (2,'active',NULL)"
        )
        connection.exec_driver_sql("INSERT INTO signal_scan_tasks VALUES (3,'pending')")
        connection.exec_driver_sql("INSERT INTO strategy_signals VALUES (4,'entry_signal',1)")
    plan = build_retirement_plan(
        base_sha="6" * 40,
        database_revision="20260802_0031",
        relations=[
            {
                "table": "profile_active_bindings",
                "id": 2,
                "binding_status": "active",
                "superseded_at": None,
            },
            {"table": "signal_scan_tasks", "id": 3, "status": "pending"},
            {"table": "strategy_signals", "id": 4, "status": "entry_signal", "is_active": True},
        ],
    )
    packet = {
        "schema_version": 1,
        "command": "data.task07.retirement-apply",
        "writes_authorized": True,
        "bound_facts": {
            "base_sha": plan["base_sha"],
            "database_revision": plan["database_revision"],
            "plan_digest": plan["plan_digest"],
            "before_image_digest": plan["before_image_digest"],
        },
    }
    packet_path = tmp_path / "retirement-approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with Session(engine) as session:
        receipt = apply_retirement_plan(
            session,
            plan,
            packet_path=packet_path,
            approval_hash=verify_exact_approval.digest_packet(packet),
            current_base_sha="6" * 40,
            current_database_revision="20260802_0031",
        )
        assert session.execute(text("SELECT binding_status FROM profile_active_bindings WHERE id=2")).scalar_one() == "superseded"
        assert session.execute(text("SELECT status FROM signal_scan_tasks WHERE id=3")).scalar_one() == "cancelled"
        assert session.execute(text("SELECT is_active FROM strategy_signals WHERE id=4")).scalar_one() == 0
        assert session.execute(text("SELECT COUNT(*) FROM strategy_signals")).scalar_one() == 1

    assert receipt["updated_row_count"] == 3
    assert receipt["deleted_row_count"] == 0
    assert receipt["deletion_authorized"] is False


def test_retirement_apply_rolls_back_every_update_when_one_row_drifted(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE profile_active_bindings "
            "(id INTEGER PRIMARY KEY, binding_status TEXT, superseded_at TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE signal_scan_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.exec_driver_sql("CREATE TABLE data_download_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.exec_driver_sql("CREATE TABLE strategy_signals (id INTEGER PRIMARY KEY, status TEXT, is_active BOOLEAN)")
        connection.exec_driver_sql(
            "INSERT INTO profile_active_bindings VALUES (1,'active',NULL)"
        )
        connection.exec_driver_sql("INSERT INTO signal_scan_tasks VALUES (2,'completed')")
    plan = build_retirement_plan(
        base_sha="7" * 40,
        database_revision="20260802_0031",
        relations=[
            {
                "table": "profile_active_bindings",
                "id": 1,
                "binding_status": "active",
                "superseded_at": None,
            },
            {"table": "signal_scan_tasks", "id": 2, "status": "pending"},
        ],
    )
    packet = {
        "schema_version": 1,
        "command": "data.task07.retirement-apply",
        "writes_authorized": True,
        "bound_facts": {
            "base_sha": plan["base_sha"], "database_revision": plan["database_revision"],
            "plan_digest": plan["plan_digest"], "before_image_digest": plan["before_image_digest"],
        },
    }
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with Session(engine) as session:
        try:
            apply_retirement_plan(
                session, plan, packet_path=packet_path,
                approval_hash=verify_exact_approval.digest_packet(packet),
                current_base_sha="7" * 40, current_database_revision="20260802_0031",
            )
        except ValueError as exc:
            assert str(exc) == "TASK07_RETIREMENT_ROW_SET_DRIFT"
        else:  # pragma: no cover
            raise AssertionError("drift must fail")
        assert session.execute(text("SELECT binding_status FROM profile_active_bindings WHERE id=1")).scalar_one() == "active"


def test_retirement_apply_rejects_new_active_row_outside_approved_row_set(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE profile_active_bindings "
            "(id INTEGER PRIMARY KEY, binding_status TEXT, superseded_at TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE signal_scan_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.exec_driver_sql("CREATE TABLE data_download_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.exec_driver_sql("CREATE TABLE strategy_signals (id INTEGER PRIMARY KEY, status TEXT, is_active BOOLEAN)")
        connection.exec_driver_sql(
            "INSERT INTO profile_active_bindings VALUES (1,'active',NULL)"
        )
    plan = build_retirement_plan(
        base_sha="8" * 40,
        database_revision="20260802_0031",
        relations=[
            {
                "table": "profile_active_bindings",
                "id": 1,
                "binding_status": "active",
                "superseded_at": None,
            }
        ],
    )
    packet = build_approval_packet(plan, command="data.task07.retirement-apply")
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO profile_active_bindings VALUES (2,'active',NULL)"
        )

    with Session(engine) as session:
        try:
            apply_retirement_plan(
                session,
                plan,
                packet_path=packet_path,
                approval_hash=verify_exact_approval.digest_packet(packet),
                current_base_sha="8" * 40,
                current_database_revision="20260802_0031",
            )
        except ValueError as exc:
            assert str(exc) == "TASK07_RETIREMENT_ROW_SET_DRIFT"
        else:  # pragma: no cover
            raise AssertionError("new active row must fail")
        assert session.execute(text("SELECT COUNT(*) FROM profile_active_bindings WHERE binding_status='active'")).scalar_one() == 2


def test_task07_apply_is_blocked_before_opening_database_without_exact_gate() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["data", "task07", "apply", "--plan", "/tmp/task07-plan.json"],
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("must not open database")),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 78
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == "TASK07_EXACT_APPROVAL_REQUIRED"


def test_task07_inventory_allows_omitted_external_protected_root() -> None:
    stdout = StringIO()
    stderr = StringIO()
    engine = create_engine("sqlite://")

    exit_code = main(
        [
            "data",
            "task07",
            "inventory",
            "--project-root",
            "/tmp/project",
            "--data-root",
            "/tmp/data",
            "--canonical-root",
            "/tmp/canonical",
            "--evidence-root",
            "/tmp/evidence",
        ],
        session_factory=lambda: Session(engine),
        data_core_runner=lambda command, _session, args: {
            "status": "passed",
            "command": command,
            "protected_roots": [str(path) for path in args.protected_root],
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "command": "task07.inventory",
        "protected_roots": [],
        "status": "passed",
    }


def test_task07_inventory_service_automatically_protects_evidence_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    canonical_root = tmp_path / "canonical"
    evidence_root = tmp_path / "evidence"
    for path in (project_root, data_root, canonical_root):
        path.mkdir()
    captured: dict[str, tuple[Path, ...]] = {}

    monkeypatch.setattr(
        cli_service_module,
        "_require_loaded_source_checkout",
        lambda _project_root: None,
    )
    monkeypatch.setattr(
        cli_service_module,
        "_git_state",
        lambda _project_root: {"head": "8" * 40, "clean": True},
    )
    monkeypatch.setattr(
        cli_service_module,
        "begin_task07_readonly_snapshot",
        lambda _session: None,
    )
    monkeypatch.setattr(
        cli_service_module,
        "_data_core_revision",
        lambda _session: "20260802_0031",
    )
    monkeypatch.setattr(
        cli_service_module,
        "scan_task07_references",
        lambda _roots: {"records": [], "truncated": False},
    )

    def collect_assets(
        _session: object,
        *,
        data_root: Path,
        canonical_root: Path,
        protected_roots: object,
    ) -> list[Task07Asset]:
        del data_root, canonical_root
        captured["protected_roots"] = tuple(protected_roots)
        return []

    monkeypatch.setattr(cli_service_module, "collect_task07_assets", collect_assets)

    result = run_data_core_command(
        "task07.inventory",
        object(),
        SimpleNamespace(
            project_root=project_root,
            data_root=data_root,
            canonical_root=canonical_root,
            evidence_root=evidence_root,
            runtime_root=[],
            protected_root=[],
            database_revision=None,
        ),
    )

    expected = evidence_root.resolve(strict=False)
    assert captured["protected_roots"] == (expected,)
    assert result["inventory_scope"]["protected_roots"] == [str(expected)]


def test_task07_apply_requires_hash_bound_preflight_before_opening_database() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data", "task07", "apply",
            "--plan", "/tmp/task07-plan.json",
            "--approval-packet", "/tmp/approval.json",
            "--approval-hash", "a" * 64,
            "--batch-key", "jm:continuous:1m",
        ],
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("must not open database")),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 78
    assert json.loads(stderr.getvalue())["error"]["code"] == "TASK07_EXACT_APPROVAL_REQUIRED"


def test_task07_retirement_apply_does_not_require_kline_preflight_arguments() -> None:
    stdout = StringIO()
    stderr = StringIO()
    engine = create_engine("sqlite://")

    exit_code = main(
        [
            "data",
            "task07",
            "retirement-apply",
            "--plan",
            "/tmp/task07-retirement-plan.json",
            "--approval-packet",
            "/tmp/approval.json",
            "--approval-hash",
            "a" * 64,
        ],
        session_factory=lambda: Session(engine),
        data_core_runner=lambda command, _session, _args: {
            "status": "passed",
            "command": command,
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["command"] == "task07.retirement-apply"


def test_task07_preflight_apply_and_verify_use_real_canonical_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.parquet"
    pq.write_table(
        pa.table(
            {
                "datetime": [datetime(2026, 7, 31, 21, 1)],
                "trading_day": [date(2026, 8, 3)],
                "open": ["100.1"],
                "high": ["101.2"],
                "low": ["99.8"],
                "close": ["100.7"],
                "volume": ["12"],
                "turnover": ["1208.4"],
                "open_interest": ["30"],
            }
        ),
        source,
    )
    checksum = sha256(source.read_bytes()).hexdigest()
    plan = build_migration_plan(
        build_inventory_index(
            [
                _asset(
                    catalog_checksum=None,
                    file_path=str(source),
                    physical_checksum=checksum,
                    checksum=checksum,
                    coverage_start="2026-07-31T13:00:00+00:00",
                    coverage_end="2026-07-31T13:01:00+00:00",
                    row_count=1,
                )
            ],
            base_sha="9" * 40,
            database_revision="20260802_0031",
        ),
        write_targets=_write_targets(tmp_path),
    )
    packet = build_approval_packet(
        plan,
        command="data.task07.apply",
        batch_key="jm:continuous:1m",
    )
    plan_path = tmp_path / "plan.json"
    packet_path = tmp_path / "approval.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = verify_exact_approval.digest_packet(packet)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('20260802_0031')")
    with Session(engine) as session:
        session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE"))
        session.add_all(
            [
                TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 31), is_trading_day=True, has_night_session=True),
                TradingCalendar(exchange_code="DCE", trade_date=date(2026, 8, 3), is_trading_day=True, has_night_session=True),
                TradingSession(exchange_code="DCE", instrument_symbol="jm", session_name="night", start_time=time(21, 0), end_time=time(21, 1), crosses_midnight=False, is_active=True),
            ]
        )
        session.commit()

    monkeypatch.setattr(
        "app.data_core.cli_service._git_state",
        lambda _root: {"head": "9" * 40, "clean": True},
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._postgresql_target",
        lambda _session: _write_targets(tmp_path)["postgresql_target"],
    )
    preflight_args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        batch_key="jm:continuous:1m",
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._git_state",
        lambda _root: {"head": "9" * 40, "clean": False},
    )
    with Session(engine) as session, pytest.raises(
        ValueError,
        match="TASK07_TASK_HEAD_NOT_CLEAN",
    ):
        run_data_core_command("task07.preflight", session, preflight_args)
    monkeypatch.setattr(
        "app.data_core.cli_service._git_state",
        lambda _root: {"head": "9" * 40, "clean": True},
    )
    with Session(engine) as session:
        preflight = run_data_core_command("task07.preflight", session, preflight_args)
    assert preflight["status"] == "passed"
    assert preflight["validation"][0]["row_count"] == 1
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    apply_args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        preflight_receipt=preflight_path,
        preflight_hash=canonical_digest(preflight),
        batch_key="jm:continuous:1m",
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
    )
    with Session(engine) as session:
        receipt = run_data_core_command("task07.apply", session, apply_args)
    assert receipt["status"] == "passed"
    assert receipt["published_source_count"] == 1

    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    verify_args = SimpleNamespace(
        plan=plan_path,
        receipt=receipt_path,
        batch_key="jm:continuous:1m",
        canonical_root=tmp_path / "canonical",
    )
    with Session(engine) as session:
        verified = run_data_core_command("task07.verify", session, verify_args)
    assert verified["status"] == "passed"
    assert verified["verified_source_count"] == 1


def test_multisource_batch_failure_writes_partial_journal_and_resumes_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = []
    for source_id in (1, 2):
        path = tmp_path / f"source-{source_id}.parquet"
        path.write_bytes(f"source-{source_id}".encode())
        checksum = sha256(path.read_bytes()).hexdigest()
        sources.append(
            _asset(
                market_data_file_id=source_id,
                catalog_checksum=None,
                file_path=str(path),
                checksum=checksum,
                physical_checksum=checksum,
            )
        )
    plan = build_migration_plan(
        build_inventory_index(
            sources,
            base_sha="8" * 40,
            database_revision="20260802_0031",
        ),
        write_targets=_write_targets(tmp_path),
    )
    packet = build_approval_packet(
        plan,
        command="data.task07.apply",
        batch_key="jm:continuous:1m",
    )
    plan_path = tmp_path / "plan.json"
    packet_path = tmp_path / "approval.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)
    validation = [
        {"market_data_file_id": source_id, "target_state": []}
        for source_id in (1, 2)
    ]
    preflight = task07.build_preflight_receipt(
        plan,
        packet_path=packet_path,
        approval_hash=approval_hash,
        current_base_sha="8" * 40,
        current_database_revision="20260802_0031",
        batch_key="jm:continuous:1m",
        current_write_targets=_write_targets(tmp_path),
    )
    preflight_body = {
        key: value for key, value in preflight.items() if key != "preflight_digest"
    }
    preflight_body["validation"] = validation
    preflight_body["validation_digest"] = canonical_digest(validation)
    preflight = {
        **preflight_body,
        "preflight_digest": canonical_digest(preflight_body),
    }
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('20260802_0031')")
    monkeypatch.setattr(
        "app.data_core.cli_service._git_state",
        lambda _root: {"head": "8" * 40, "clean": True},
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._postgresql_target",
        lambda _session: _write_targets(tmp_path)["postgresql_target"],
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._task07_validate_batch_readonly",
        lambda _session, *, batch: (
            validation,
            [(source, int(source["market_data_file_id"])) for source in batch["sources"]],
        ),
    )
    monkeypatch.setattr(
        "app.data_core.cli_service.verify_task07_published_batch",
        lambda receipt, **_kwargs: {"status": "passed", "source": receipt["market_data_file_id"]},
    )
    attempts: list[int] = []

    def first_attempt(prepared, **_kwargs):
        attempts.append(prepared)
        if prepared == 2:
            raise RuntimeError("injected second-source failure")
        body = {
            "market_data_file_id": prepared,
            "status": "passed",
            "batch_key": f"jm:continuous:1m:{prepared}",
            "plan_digest": plan["plan_digest"],
            "batch_digest": plan["batches"][0]["batch_digest"],
        }
        return {**body, "receipt_digest": canonical_digest(body)}

    monkeypatch.setattr(
        "app.data_core.cli_service.execute_task07_prepared_batch",
        first_attempt,
    )
    args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        preflight_receipt=preflight_path,
        preflight_hash=canonical_digest(preflight),
        batch_key="jm:continuous:1m",
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
    )
    with Session(engine) as session, pytest.raises(ValueError, match="TASK07_BATCH_PARTIAL"):
        run_data_core_command("task07.apply", session, args)
    journal_path = (
        tmp_path
        / "staging"
        / "task07-batch-journals"
        / plan["plan_digest"]
        / "jm_continuous_1m.json"
    )
    partial = json.loads(journal_path.read_text(encoding="utf-8"))
    assert partial["status"] == "partial_failed"
    assert partial["completed_source_ids"] == [1]
    assert partial["failure"]["source_id"] == 2
    assert attempts == [1, 2]

    attempts.clear()

    def resumed_attempt(prepared, **_kwargs):
        attempts.append(prepared)
        body = {
            "market_data_file_id": prepared,
            "status": "passed",
            "batch_key": f"jm:continuous:1m:{prepared}",
            "plan_digest": plan["plan_digest"],
            "batch_digest": plan["batches"][0]["batch_digest"],
        }
        return {**body, "receipt_digest": canonical_digest(body)}

    monkeypatch.setattr(
        "app.data_core.cli_service.execute_task07_prepared_batch",
        resumed_attempt,
    )
    with Session(engine) as session:
        receipt = run_data_core_command("task07.apply", session, args)
    assert attempts == [2]
    assert receipt["published_source_count"] == 2
    completed = json.loads(journal_path.read_text(encoding="utf-8"))
    assert completed["status"] == "completed"
    assert completed["completed_source_ids"] == [1, 2]


def test_batch_journal_fsyncs_file_and_directory_and_rejects_forged_source_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.data_core.cli_service as cli_module

    fsync_calls: list[int] = []
    monkeypatch.setattr(cli_module.os, "fsync", lambda fd: fsync_calls.append(fd))
    bound_facts = {
        "base_sha": "6" * 40,
        "database_revision": "20260802_0031",
        "plan_digest": "a" * 64,
        "inventory_digest": "b" * 64,
        "batch_key": "jm:continuous:1m",
        "batch_digest": "c" * 64,
        "write_targets": _write_targets(tmp_path),
    }
    path = tmp_path / "journal.json"
    journal = cli_module._load_or_initialize_task07_batch_journal(
        path,
        bound_facts=bound_facts,
        source_ids=[1, 2],
    )
    assert len(fsync_calls) == 2

    forged_receipt_body = {
        "market_data_file_id": 2,
        "batch_key": "jm:continuous:1m:2",
        "plan_digest": "a" * 64,
        "batch_digest": "c" * 64,
    }
    forged_receipt = {
        **forged_receipt_body,
        "receipt_digest": canonical_digest(forged_receipt_body),
    }
    cli_module._write_task07_batch_journal(
        path,
        {
            **journal,
            "status": "partial_failed",
            "completed_source_ids": [2],
            "source_receipts": [forged_receipt],
            "current_source_id": 1,
        },
    )
    with pytest.raises(ValueError, match="TASK07_BATCH_JOURNAL_DRIFT"):
        cli_module._load_or_initialize_task07_batch_journal(
            path,
            bound_facts=bound_facts,
            source_ids=[1, 2],
        )


def test_multisource_real_canonical_commit_then_journal_crash_resumes_as_exact_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = []
    for source_id, minute in ((1, 1), (2, 2)):
        source = tmp_path / f"legacy-{source_id}.parquet"
        pq.write_table(
            pa.table(
                {
                    "datetime": [datetime(2026, 7, 31, 21, minute)],
                    "trading_day": [date(2026, 8, 3)],
                    "open": [f"10{source_id}.1"],
                    "high": [f"10{source_id}.2"],
                    "low": [f"10{source_id}.0"],
                    "close": [f"10{source_id}.15"],
                    "volume": ["12"],
                    "turnover": ["1208.4"],
                    "open_interest": ["30"],
                }
            ),
            source,
        )
        checksum = sha256(source.read_bytes()).hexdigest()
        assets.append(
            _asset(
                market_data_file_id=source_id,
                catalog_checksum=None,
                file_path=str(source),
                checksum=checksum,
                physical_checksum=checksum,
                coverage_start=f"2026-07-31T13:0{minute - 1}:00+00:00",
                coverage_end=f"2026-07-31T13:0{minute}:00+00:00",
                row_count=1,
            )
        )
    plan = build_migration_plan(
        build_inventory_index(
            assets,
            base_sha="7" * 40,
            database_revision="20260802_0031",
        ),
        write_targets=_write_targets(tmp_path),
    )
    packet = build_approval_packet(
        plan,
        command="data.task07.apply",
        batch_key="jm:continuous:1m",
    )
    plan_path = tmp_path / "real-plan.json"
    packet_path = tmp_path / "real-approval.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('20260802_0031')")
    with Session(engine) as session:
        session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE"))
        session.add_all(
            [
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 31),
                    is_trading_day=True,
                    has_night_session=True,
                ),
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2026, 8, 3),
                    is_trading_day=True,
                    has_night_session=True,
                ),
                TradingSession(
                    exchange_code="DCE",
                    instrument_symbol="jm",
                    session_name="night",
                    start_time=time(21, 0),
                    end_time=time(21, 2),
                    crosses_midnight=False,
                    is_active=True,
                ),
            ]
        )
        session.commit()
    monkeypatch.setattr(
        "app.data_core.cli_service._git_state",
        lambda _root: {"head": "7" * 40, "clean": True},
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._postgresql_target",
        lambda _session: _write_targets(tmp_path)["postgresql_target"],
    )
    preflight_args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        batch_key="jm:continuous:1m",
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
    )
    with Session(engine) as session:
        preflight = run_data_core_command("task07.preflight", session, preflight_args)
    preflight_path = tmp_path / "real-preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    apply_args = SimpleNamespace(
        **vars(preflight_args),
        preflight_receipt=preflight_path,
        preflight_hash=canonical_digest(preflight),
    )

    import app.data_core.cli_service as cli_module

    original_execute = cli_module.execute_task07_prepared_batch
    crashed_receipt: dict[str, object] | None = None

    def crash_after_second_publish(prepared, **kwargs):
        nonlocal crashed_receipt
        receipt = original_execute(prepared, **kwargs)
        if receipt["market_data_file_id"] == 2:
            crashed_receipt = receipt
            raise RuntimeError("simulated crash after canonical commit")
        return receipt

    monkeypatch.setattr(
        "app.data_core.cli_service.execute_task07_prepared_batch",
        crash_after_second_publish,
    )
    with Session(engine) as session, pytest.raises(ValueError, match="TASK07_BATCH_PARTIAL"):
        run_data_core_command("task07.apply", session, apply_args)
    assert crashed_receipt is not None
    with Session(engine) as session:
        assert session.execute(text("SELECT COUNT(*) FROM market_partitions")).scalar_one() == 2

    monkeypatch.setattr(
        "app.data_core.cli_service.execute_task07_prepared_batch",
        original_execute,
    )
    with Session(engine) as session:
        receipt = run_data_core_command("task07.apply", session, apply_args)
    assert receipt["published_source_count"] == 2
    assert receipt["source_receipts"][1]["publication_status"] == "reused"
