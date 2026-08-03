from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.data_core import task07
from app.data_core.task07 import (
    AssetDisposition,
    Task07Asset,
    build_approval_packet,
    _build_inventory_index as build_inventory_index,
    build_migration_plan,
    build_write_targets,
    canonical_digest,
    classify_asset,
    collect_task07_assets,
    _load_inventory_evidence as load_inventory_evidence,
    _scan_task07_references as scan_task07_references,
    verify_exact_approval,
    verify_task07_preflight_receipt,
    _write_inventory_evidence as write_inventory_evidence,
    write_kline_manifest_evidence,
)
from app.data_core.cli_service import run_data_core_command
from app.db.base import Base
from app.guiyi_cli.main import main
from app.models.data_center import (
    DataQualityReport,
    Instrument,
    MarketDataFile,
    TradingCalendar,
    TradingSession,
)


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


def _aggregate_asset(**overrides: object) -> Task07Asset:
    values: dict[str, object] = {
        "frequency": "5m",
        "catalog_checksum": None,
        "content_gate_status": "passed",
        "physical_row_count": 10,
        "declared_periods": ("5m",),
        "source_intervals": ("1m",),
        "registration_wall_clock_matches": True,
        "quality_evidence_digest": "b" * 64,
        "quality_evidence_count": 1,
        "quality_evidence_statuses": ("passed",),
    }
    values.update(overrides)
    return _asset(**values)


def _registered_file_from_plan_source(source: dict[str, object]) -> MarketDataFile:
    snapshot = source["registration_snapshot"]
    assert isinstance(snapshot, dict)
    return MarketDataFile(
        id=int(snapshot["id"]),
        provider=str(snapshot["provider"]),
        data_type=str(snapshot["data_type"]),
        instrument_symbol=str(snapshot["symbol"]),
        contract_code=str(snapshot["contract_or_series"]),
        period=str(snapshot["frequency"]),
        start_time=datetime.fromisoformat(str(snapshot["coverage_start"])),
        end_time=datetime.fromisoformat(str(snapshot["coverage_end"])),
        file_path=str(snapshot["file_path"]),
        row_count=int(snapshot["row_count"]),
        file_size_bytes=int(snapshot["file_size_bytes"]),
        checksum=str(snapshot["checksum"]),
        data_version=str(snapshot["data_version"]),
        data_role=str(snapshot["data_role"]),
        quality_status=str(snapshot["quality_status"]),
    )


def _reference_report(tmp_path: Path, *, active: bool = False) -> dict[str, object]:
    checkout = tmp_path / "checkout"
    runtime = tmp_path / "runtime"
    checkout.mkdir(exist_ok=True)
    runtime.mkdir(exist_ok=True)
    if active:
        consumer = runtime / "services" / "quant-api" / "app" / "consumer.py"
        consumer.parent.mkdir(parents=True, exist_ok=True)
        consumer.write_text("reader = MarketDataReader()\n", encoding="utf-8")
    return scan_task07_references(
        [("checkout", checkout), ("detached_runtime", runtime)]
    )


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
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.REGISTER_DATA_GAP,
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.PROTECTED_EVIDENCE_SOURCE,
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.CONFLICT_BLOCKED,
        AssetDisposition.CONFLICT_BLOCKED,
    ]
    assert index["eligible_asset_count"] == 1
    assert index["blocked_asset_count"] == 6
    assert index["deletion_authorized"] is False


def test_inventory_marks_verified_aggregate_minute_source_for_schema_only_reuse() -> None:
    aggregate = _aggregate_asset(
        frequency="15m",
        declared_periods=("15m",),
    )

    assert classify_asset(aggregate).value == "REUSE_VERIFIED_AGGREGATE"


def test_inventory_keeps_verified_canonical_aggregate_partition() -> None:
    canonical = _asset(
        frequency="30m",
        data_type="v2_canonical",
        source_scope="approved_canonical_root",
        catalog_checksum="a" * 64,
    )

    assert classify_asset(canonical) == AssetDisposition.CONFLICT_BLOCKED


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
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER, manifest_version TEXT DEFAULT 'legacy-v1', "
            "manifest_uri TEXT DEFAULT 'missing.manifest.json', manifest_digest TEXT DEFAULT '0000000000000000000000000000000000000000000000000000000000000000')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE data_quality_reports (id INTEGER PRIMARY KEY, file_id INTEGER, task_id INTEGER, "
            "provider TEXT, data_type TEXT, instrument_symbol TEXT, contract_code TEXT, period TEXT, "
            "start_time TEXT, end_time TEXT, status TEXT, missing_bars INTEGER, duplicated_bars INTEGER, "
            "abnormal_price_count INTEGER, abnormal_volume_count INTEGER, details TEXT, created_at TEXT)"
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
    assert classify_asset(assets[0]) == AssetDisposition.CONFLICT_BLOCKED


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
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER, manifest_version TEXT DEFAULT 'legacy-v1', "
            "manifest_uri TEXT DEFAULT 'missing.manifest.json', manifest_digest TEXT DEFAULT '0000000000000000000000000000000000000000000000000000000000000000')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE data_quality_reports (id INTEGER PRIMARY KEY, file_id INTEGER, task_id INTEGER, "
            "provider TEXT, data_type TEXT, instrument_symbol TEXT, contract_code TEXT, period TEXT, "
            "start_time TEXT, end_time TEXT, status TEXT, missing_bars INTEGER, duplicated_bars INTEGER, "
            "abnormal_price_count INTEGER, abnormal_volume_count INTEGER, details TEXT, created_at TEXT)"
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


def test_plan_revalidates_inventory_shard_after_initial_load(tmp_path: Path) -> None:
    write_inventory_evidence(
        [_asset(catalog_checksum=None)],
        evidence_root=tmp_path,
        base_sha="1" * 40,
        database_revision="20260802_0031",
        shard_size=1,
    )
    loaded = load_inventory_evidence(tmp_path / "inventory-index.json")
    shard_path = tmp_path / str(loaded["shards"][0]["path"])
    replacement = json.loads(shard_path.read_text(encoding="utf-8"))
    replacement["symbol"] = "rb"
    shard_path.write_text(
        json.dumps(
            replacement,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="TASK07_INVENTORY_SHARD_HASH_MISMATCH"):
        build_migration_plan(loaded, write_targets=_write_targets(tmp_path))


def test_catalog_page_cache_only_contains_exact_current_page_paths(
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE market_datasets ("
            "id INTEGER PRIMARY KEY, provider TEXT, dataset_kind TEXT, symbol TEXT, "
            "contract_or_series TEXT, frequency TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE market_partitions ("
            "id INTEGER PRIMARY KEY, dataset_id INTEGER, file_uri TEXT, checksum TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO market_datasets VALUES "
            "(1, 'rqdata', 'continuous', 'jm', 'JM.MAIN', '1m')"
        )
        connection.execute(
            text(
                "WITH RECURSIVE seq(id) AS ("
                "VALUES(1) UNION ALL SELECT id + 1 FROM seq WHERE id < 1000) "
                "INSERT INTO market_partitions "
                "SELECT id, 1, printf('jm/part-%04d.parquet', id), :checksum FROM seq"
            ),
            {"checksum": "a" * 64},
        )
    requested = canonical_root / "jm" / "part-0500.parquet"
    rows = [
        {
            "provider": "rqdata",
            "instrument_symbol": "jm",
            "contract_code": "JM.MAIN",
            "period": "1m",
            "file_path": str(requested),
        }
    ]

    with Session(engine) as session:
        matches = task07._catalog_matches_for_market_page(
            session,
            rows=rows,
            canonical_root=canonical_root,
            page_size=25,
        )

    assert matches == {
        (
            "rqdata",
            "jm",
            "JM.MAIN",
            "1m",
            str(requested.absolute()),
        ): (("continuous", "a" * 64),)
    }


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


def test_reference_scan_classifies_exact_sdd_task_evidence_as_historical(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / ".superpowers" / "sdd" / "task07"
    evidence.mkdir(parents=True)
    (evidence / "task-4-brief.md").write_text(
        "Remove profile_id from the active request.\n",
        encoding="utf-8",
    )
    (evidence / "task-4-report.md").write_text(
        "Verified market_data_file_id is historical only.\n",
        encoding="utf-8",
    )

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["state_counts"] == {
        "active": 0,
        "historical_non_active": 2,
        "review_required": 0,
    }
    assert {
        item["classification_reason"] for item in report["records"]
    } == {"sdd_task_evidence"}


def test_reference_scan_does_not_treat_non_parquet_glob_as_market_data_glob(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "engineering" / "lean_matrix" / "workspace.py"
    script.parent.mkdir(parents=True)
    script.write_text('files = directory.glob("*.json")\n', encoding="utf-8")

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["record_count"] == 0


def test_reference_scan_keeps_real_executable_selector_and_parquet_glob_active(
    tmp_path: Path,
) -> None:
    source = tmp_path / "services" / "quant-api" / "app" / "consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'profile_id = request.profile_id\nfiles = root.glob("*.parquet")\n',
        encoding="utf-8",
    )

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["state_counts"] == {
        "active": 1,
        "historical_non_active": 0,
        "review_required": 1,
    }
    assert {item["marker"] for item in report["records"]} == {
        "legacy_selector",
        "parquet_glob",
    }


def test_reference_scan_does_not_blanket_hide_unlisted_operational_script(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scripts" / "new_operational_consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'profile_id = request.profile_id\nfiles = root.glob("*.parquet")\n',
        encoding="utf-8",
    )

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["state_counts"] == {
        "active": 0,
        "historical_non_active": 0,
        "review_required": 2,
    }
    assert {
        item["classification_reason"] for item in report["records"]
    } == {"unclassified_reference", "selector_requires_manual_reachability_review"}


def test_reference_scan_operational_backup_rule_cannot_hide_new_active_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scripts" / "backup" / "core.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "reader = MarketDataReader()\nprofile_id = historical_row.profile_id\n",
        encoding="utf-8",
    )

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["state_counts"] == {
        "active": 0,
        "historical_non_active": 0,
        "review_required": 2,
    }
    assert {
        item["marker"]: item["reference_state"] for item in report["records"]
    } == {
        "legacy_reader": "review_required",
        "legacy_selector": "review_required",
    }


def test_reference_scan_rejects_duplicated_approved_snapshot_line(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scripts" / "backup" / "core.py"
    source.parent.mkdir(parents=True)
    approved_line = (
        '        market_data_file_id = binding.get("market_data_file_id")\n'
    )
    source.write_text(approved_line * 2, encoding="utf-8")

    report = scan_task07_references([("checkout", tmp_path)])

    assert report["state_counts"] == {
        "active": 0,
        "historical_non_active": 0,
        "review_required": 2,
    }
    assert {
        item["classification_reason"] for item in report["records"]
    } == {"selector_requires_manual_reachability_review"}


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/consumer_contract_final_closeout_006.py",
        "scripts/rqdata_v1b_jm_asset.py",
        "scripts/signal_review_lineage_gate_003.py",
    ],
)
def test_reference_scan_exact_script_manifest_never_hides_detached_runtime(
    tmp_path: Path,
    relative: str,
) -> None:
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("profile_id = request.profile_id\n", encoding="utf-8")

    report = scan_task07_references([("detached_runtime", tmp_path)])

    assert report["state_counts"] == {
        "active": 0,
        "historical_non_active": 0,
        "review_required": 1,
    }


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
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER, manifest_version TEXT DEFAULT 'legacy-v1', "
            "manifest_uri TEXT DEFAULT 'missing.manifest.json', manifest_digest TEXT DEFAULT '0000000000000000000000000000000000000000000000000000000000000000')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE data_quality_reports (id INTEGER PRIMARY KEY, file_id INTEGER, task_id INTEGER, "
            "provider TEXT, data_type TEXT, instrument_symbol TEXT, contract_code TEXT, period TEXT, "
            "start_time TEXT, end_time TEXT, status TEXT, missing_bars INTEGER, duplicated_bars INTEGER, "
            "abnormal_price_count INTEGER, abnormal_volume_count INTEGER, details TEXT, created_at TEXT)"
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
            text(
                "INSERT INTO market_partitions "
                "(id,dataset_id,file_uri,checksum,coverage_start,coverage_end,row_count) "
                "VALUES (1,1,'source.parquet',:checksum,'2026-01-01','2026-01-02',1)"
            ),
            {"checksum": checksum},
        )

    catalog_page_queries = 0

    @event.listens_for(engine, "before_cursor_execute")
    def count_catalog_keyset_queries(
        _conn, _cursor, statement, _parameters, _context, _many
    ) -> None:
        nonlocal catalog_page_queries
        if "FROM market_datasets d JOIN market_partitions p" in statement:
            assert "p.id >" in statement
            catalog_page_queries += 1

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
    assert catalog_page_queries >= 2


def test_database_inventory_promotes_only_physically_verified_aggregate_with_quality_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "aggregate.parquet"
    pq.write_table(
        pa.table(
            {
                "datetime": [
                    datetime(2026, 3, 31, 21, 5),
                    datetime(2026, 3, 31, 21, 10),
                ],
                "trading_day": [date(2026, 4, 1), date(2026, 4, 1)],
                "open": ["100.10", "100.20"],
                "high": ["100.50", "100.60"],
                "low": ["99.90", "100.00"],
                "close": ["100.30", "100.40"],
                "volume": ["12", "13"],
                "turnover": ["1203.60", "1305.20"],
                "open_interest": ["30", "31"],
                "period": ["5m", "5m"],
                "source_interval": ["1m", "1m"],
            }
        ),
        source,
    )
    checksum = sha256(source.read_bytes()).hexdigest()
    engine = create_engine("sqlite://")
    _task07_inventory_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO market_data_files VALUES "
                "(1,'rqdata','bars','a','A.MAIN','5m','2026-03-31 21:05:00+00:00',"
                "'2026-03-31 21:10:00+00:00',:path,:size,:checksum,'legacy-v1',2,'primary','passed')"
            ),
            {
                "path": str(source),
                "size": source.stat().st_size,
                "checksum": checksum,
            },
        )
        connection.execute(
            text(
                "INSERT INTO data_quality_reports VALUES "
                "(11,1,NULL,'rqdata','bars','a','A.MAIN','5m',"
                "'2026-03-31 21:05:00+00:00','2026-03-31 21:10:00+00:00',"
                "'passed',0,0,0,0,'{}','2026-07-08 00:00:00+00:00')"
            )
        )

    with Session(engine) as session:
        asset = next(
            iter(
                collect_task07_assets(
                    session,
                    data_root=tmp_path,
                    canonical_root=tmp_path,
                    page_size=1,
                )
            )
        )

    assert classify_asset(asset).value == "REUSE_VERIFIED_AGGREGATE"
    assert getattr(asset, "quality_evidence_count", None) == 1
    assert getattr(asset, "quality_evidence_statuses", None) == ("passed",)
    assert getattr(asset, "source_intervals", None) == ("1m",)
    assert getattr(asset, "declared_periods", None) == ("5m",)
    assert getattr(asset, "physical_row_count", None) == 2
    assert getattr(asset, "registration_wall_clock_matches", None) is True


def test_aggregate_inventory_content_gate_streams_parquet_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "aggregate.parquet"
    pq.write_table(
        pa.table(
            {
                "datetime": [datetime(2026, 3, 31, 21, 5)],
                "trading_day": [date(2026, 4, 1)],
                "open": ["100.10"],
                "high": ["100.50"],
                "low": ["99.90"],
                "close": ["100.30"],
                "volume": ["12"],
                "turnover": ["1203.60"],
                "open_interest": ["30"],
                "period": ["5m"],
                "source_interval": ["1m"],
            }
        ),
        source,
    )
    physical = pq.ParquetFile(source)

    class StreamingOnlyParquet:
        schema_arrow = physical.schema_arrow
        metadata = physical.metadata

        @staticmethod
        def read(*_args, **_kwargs):
            raise AssertionError("full-table read is forbidden")

        @staticmethod
        def iter_batches(*args, **kwargs):
            return physical.iter_batches(*args, **kwargs)

    monkeypatch.setattr(
        task07.pq,
        "ParquetFile",
        lambda _path: StreamingOnlyParquet(),
    )

    with Session(create_engine("sqlite://")) as session:
        evidence = task07._aggregate_parquet_content_gate(
            session,
            registered_path=source,
            physical_path=source,
            frequency="5m",
            registered_row_count=1,
            registered_start="2026-03-31 21:05:00+00:00",
            registered_end="2026-03-31 21:05:00+00:00",
            dataset_kind="continuous",
            symbol="a",
            contract="A.MAIN",
        )

    assert evidence["status"] == "passed"
    assert evidence["physical_row_count"] == 1


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
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER, manifest_version TEXT DEFAULT 'legacy-v1', "
            "manifest_uri TEXT DEFAULT 'missing.manifest.json', manifest_digest TEXT DEFAULT '0000000000000000000000000000000000000000000000000000000000000000')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE data_quality_reports (id INTEGER PRIMARY KEY, file_id INTEGER, task_id INTEGER, "
            "provider TEXT, data_type TEXT, instrument_symbol TEXT, contract_code TEXT, period TEXT, "
            "start_time TEXT, end_time TEXT, status TEXT, missing_bars INTEGER, duplicated_bars INTEGER, "
            "abnormal_price_count INTEGER, abnormal_volume_count INTEGER, details TEXT, created_at TEXT)"
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
        assert "assets" not in loaded
        plans.append(build_migration_plan(loaded, write_targets=_write_targets(tmp_path)))
        assert index["asset_count"] == 600_001
        assert loaded["asset_count"] == 600_001
        assert len(index["shards"]) == 13
        assert index["truncated"] is False

    assert page_queries == 28
    assert plans[0]["assets_digest"] == plans[1]["assets_digest"]
    assert plans[0]["plan_digest"] == plans[1]["plan_digest"]


@pytest.mark.parametrize("record_kind", ["eligible", "provider_request"])
def test_migration_plan_fails_closed_before_unbounded_record_growth(
    monkeypatch: pytest.MonkeyPatch,
    record_kind: str,
) -> None:
    asset = (
        _asset(catalog_checksum=None)
        if record_kind == "eligible"
        else _asset(physical_checksum="b" * 64, catalog_checksum=None)
    )
    template = task07._asset_record(asset)
    index = build_inventory_index(
        [],
        base_sha="2" * 40,
        database_revision="20260802_0031",
    )

    monkeypatch.setattr(
        task07,
        "_iter_inventory_assets",
        lambda _index: (
            {**template, "market_data_file_id": value}
            for value in range(1, task07._TASK07_PLAN_RECORD_LIMIT + 2)
        ),
    )

    with pytest.raises(
        ValueError,
        match="TASK07_PLAN_SOURCE_SHARDING_REQUIRED",
    ):
        build_migration_plan(index, write_targets=_write_targets())


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
    ]
    assert plan["batches"][0]["sources"][0]["row_count"] == 10
    assert plan["batches"][0]["sources"][0]["data_version"] == "legacy-v1"
    assert plan["batches"][0]["sources"][0]["contract_or_series"] == "JM.MAIN"
    assert plan["calls_rqdata"] is False
    assert plan["writes_authorized"] is False
    assert plan["migration_envelope"]["batch_manifest"] == [
        {
            "batch_key": batch["batch_key"],
            "batch_digest": batch["batch_digest"],
        }
        for batch in plan["batches"]
    ]
    assert plan["migration_envelope"]["batch_count"] == 1
    assert len(plan["plan_digest"]) == 64


def test_migration_plan_binds_verified_aggregate_origin_and_quality_lineage() -> None:
    index = build_inventory_index(
        [_aggregate_asset()],
        base_sha="3" * 40,
        database_revision="20260803_0032",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert plan["approval_eligible"] is True
    assert plan["provider_request_proposal"]["request_count"] == 0
    assert plan["batches"][0]["batch_key"] == "jm:continuous:5m"
    assert plan["batches"][0]["dataset_origin"] == "preaggregated_from_1m"
    assert plan["batches"][0]["required_database_revision"] == "20260803_0032"
    assert plan["batches"][0]["sources"][0]["quality_evidence_digest"] == "b" * 64
    assert plan["batches"][0]["sources"][0]["source_frequency"] == "1m"
    assert plan["batches"][0]["sources"][0]["manifest_format"] == "canonical-manifest-v2"
    assert plan["batches"][0]["sources"][0]["dataset_origin"] == "preaggregated_from_1m"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality_evidence_digest", "c" * 63),
        ("registration_wall_clock_matches", False),
        ("manifest_version", "tampered-v1"),
    ],
)
def test_aggregate_plan_integrity_rejects_tampered_source_gate_fields(
    field: str,
    value: object,
) -> None:
    plan = build_migration_plan(
        build_inventory_index(
            [_aggregate_asset()],
            base_sha="3" * 40,
            database_revision="20260803_0032",
        ),
        write_targets=_write_targets(),
    )
    plan["batches"][0]["sources"][0][field] = value
    batch_body = {
        key: item
        for key, item in plan["batches"][0].items()
        if key != "batch_digest"
    }
    plan["batches"][0]["batch_digest"] = canonical_digest(batch_body)
    plan["migration_envelope"] = task07.build_migration_envelope(
        plan["batches"]
    )

    with pytest.raises(ValueError, match="TASK07_BATCH_ORIGIN_INVALID"):
        task07._validate_migration_plan_integrity(plan)


def test_aggregate_gap_or_conflict_never_emits_provider_request_proposal() -> None:
    index = build_inventory_index(
        [
            _aggregate_asset(
                market_data_file_id=1,
                quality_evidence_digest=None,
                quality_evidence_count=0,
                quality_evidence_statuses=(),
            ),
            _aggregate_asset(
                market_data_file_id=2,
                source_intervals=("5m",),
            ),
        ],
        base_sha="3" * 40,
        database_revision="20260803_0032",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert plan["classification_counts"]["REGISTER_DATA_GAP"] == 1
    assert plan["classification_counts"]["CONFLICT_BLOCKED"] == 1
    assert plan["provider_request_proposal"]["request_count"] == 0


def test_conflicts_emit_only_exact_unauthorized_repair_actions() -> None:
    index = build_inventory_index(
        [
            _asset(
                market_data_file_id=1,
                physical_checksum="b" * 64,
                catalog_checksum=None,
            ),
            _aggregate_asset(
                market_data_file_id=2,
                physical_checksum="c" * 64,
                catalog_checksum=None,
            ),
        ],
        base_sha="1" * 40,
        database_revision="20260803_0032",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert [item["action"] for item in plan["repair_actions"]] == [
        "rqdata_redownload",
        "canonical_1m_reaggregate",
    ]
    assert all(item["authorized"] is False for item in plan["repair_actions"])
    assert plan["repair_actions"][0]["frequency"] == "1m"
    assert plan["repair_actions"][1]["source_dataset"]["frequency"] == "1m"
    assert plan["repair_actions"][1]["frequency"] == "5m"
    assert plan["repair_actions"][0]["manifest_digest"] == index["assets_digest"]
    assert plan["repair_actions"][0]["validation_gates"] == [
        "schema",
        "bar_end_strictly_increasing",
        "duplicate_identity",
        "trading_session",
        "partition_readability",
    ]
    assert plan["repair_actions"][1]["failure_policy"] == {
        "preserve_existing_canonical": True,
        "register_data_gap": True,
        "delete_existing": False,
    }


def test_runtime_cutover_minimal_plan_and_receipt_fail_closed_on_drift() -> None:
    tags = {"v1.0.0": "1" * 40, "v0.9.0": "2" * 40}
    plan = task07.build_runtime_cutover_plan(
        target_release_tag="v1.0.0",
        previous_release_tag="v0.9.0",
        tag_resolver=tags.__getitem__,
    )
    body = {
        "schema_version": 1,
        "command": "data.task07.runtime-cutover",
        "status": "passed",
        "target_release": {"tag": "v1.0.0", "sha": "1" * 40},
        "database_revision": "20260803_0032",
        "feature_flags": dict(plan["required_feature_flags"]),
        "auto_order": False,
        "health": {"status": "passed"},
        "smoke": {"status": "passed"},
        "rollback": {"tag": "v0.9.0", "sha": "2" * 40, "ready": True},
        "post_cutover_reference_assertion": {
            "scope": "checkout_and_runtime",
            "complete": True,
            "active": 0,
            "review_required": 0,
        },
        "plan_digest": plan["plan_digest"],
    }
    receipt = {**body, "canonical_receipt_digest": canonical_digest(body)}

    verified = task07.verify_runtime_cutover_receipt(
        plan,
        receipt,
        tag_resolver=tags.__getitem__,
    )

    assert verified["status"] == "passed"
    assert set(receipt).isdisjoint(
        {"pid", "environment_digest", "web_bundle_digest", "active_row_set_digest"}
    )
    assert (
        plan["required_feature_flags"][
            "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED"
        ]
        is False
    )
    drifted = deepcopy(receipt)
    drifted["feature_flags"]["GUIYI_LIVE_RUNTIME_ENABLED"] = True
    bounded_wecom_enabled = deepcopy(receipt)
    bounded_wecom_enabled["feature_flags"][
        "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED"
    ] = True
    drift_cases = [
        drifted,
        bounded_wecom_enabled,
        {**deepcopy(receipt), "database_revision": "20260802_0031"},
        {**deepcopy(receipt), "health": {"status": "failed"}},
        {**deepcopy(receipt), "smoke": {"status": "failed"}},
        {
            **deepcopy(receipt),
            "rollback": {"tag": "v0.9.0", "sha": "2" * 40, "ready": False},
        },
        {
            **deepcopy(receipt),
            "post_cutover_reference_assertion": {
                "scope": "checkout_and_runtime",
                "complete": True,
                "active": 1,
                "review_required": 0,
            },
        },
    ]
    for drift_case in drift_cases:
        drift_body = {
            key: value
            for key, value in drift_case.items()
            if key != "canonical_receipt_digest"
        }
        drift_case["canonical_receipt_digest"] = canonical_digest(drift_body)
        with pytest.raises(
            ValueError,
            match="TASK07_RUNTIME_CUTOVER_RECEIPT_DRIFT",
        ):
            task07.verify_runtime_cutover_receipt(
                plan,
                drift_case,
                tag_resolver=tags.__getitem__,
            )
    moved_tags = {**tags, "v1.0.0": "3" * 40}
    with pytest.raises(ValueError, match="TASK07_RUNTIME_CUTOVER_PLAN_DRIFT"):
        task07.verify_runtime_cutover_receipt(
            plan,
            receipt,
            tag_resolver=moved_tags.__getitem__,
        )
    assert plan["calls_rqdata"] is False


@pytest.mark.parametrize(
    ("leaf_count", "expected_root"),
    [
        (0, "dbc1b4c900ffe48d575b5da5c638040125f65db0fe3e24494b76ea986457d986"),
        (1, "3b3841f61f68dcf28bb8d6da61ae30591d0324adcad1b0d407f993775e2c4a4e"),
        (2, "6aa46e222f8efb47e12d21a24f2a84c2bf7a0b333f4efa6addc0b9a5bd61b6da"),
        (5, "ec069e5739ef49b8e9cd614118d3ba77d2fbbe3af7ad7a04ca22359b98acfbbd"),
    ],
)
def test_migration_merkle_literal_vectors_define_empty_and_odd_leaf_semantics(
    leaf_count: int,
    expected_root: str,
) -> None:
    leaves = [
        {"batch_key": key, "batch_digest": digest * 32}
        for key, digest in zip("abcde", ("11", "22", "33", "44", "55"), strict=True)
    ]

    envelope = task07.build_migration_envelope(reversed(leaves[:leaf_count]))

    assert envelope["schema_version"] == 2
    assert envelope["empty_domain"] == "02"
    assert envelope["odd_leaf_rule"] == "duplicate_last_at_each_level"
    assert envelope["batch_manifest"] == leaves[:leaf_count]
    assert envelope["batch_count"] == leaf_count
    assert envelope["merkle_root"] == expected_root
    assert len(envelope["envelope_digest"]) == 64


def test_task07_plan_schema_v1_is_rejected_instead_of_silently_reinterpreted() -> None:
    plan = build_migration_plan(
        build_inventory_index(
            [_asset(catalog_checksum=None)],
            base_sha="3" * 40,
            database_revision="20260802_0031",
        ),
        write_targets=_write_targets(),
    )

    assert plan["schema_version"] == 2
    assert plan["migration_envelope"]["schema_version"] == 2
    old_shape = deepcopy(plan)
    old_shape["schema_version"] = 1
    with pytest.raises(ValueError, match="TASK07_PLAN_SCHEMA_INVALID"):
        build_approval_packet(old_shape, command="data.task07.apply")


def test_migration_plan_has_no_reference_retirement_or_deletion_inventory(
    tmp_path: Path,
) -> None:
    index = build_inventory_index(
        [_asset(catalog_checksum=None)],
        base_sha="3" * 40,
        database_revision="20260802_0031",
    )
    report = _reference_report(tmp_path, active=True)
    index["reference_index"] = {
        key: value for key, value in report.items() if key != "records"
    }

    plan = build_migration_plan(index, write_targets=_write_targets(tmp_path))

    assert plan["approval_eligible"] is True
    assert plan["gate_status"] == "exact_owner_approval_required"
    assert not {
        "active_reference_gate",
        "reference_snapshot",
        "retirement_eligible",
        "deletion_eligible",
        "deletion_candidate_manifest",
    } & plan.keys()
    assert build_approval_packet(plan, command="data.task07.apply")[
        "bound_facts"
    ]["migration_envelope"] == plan["migration_envelope"]


def test_migration_plan_preserves_conflict_without_blocking_other_exact_batch() -> None:
    index = build_inventory_index(
        [
            _asset(market_data_file_id=1, catalog_checksum=None),
            _asset(market_data_file_id=2, physical_checksum="b" * 64),
        ],
        base_sha="3" * 40,
        database_revision="20260802_0031",
    )

    plan = build_migration_plan(index, write_targets=_write_targets())

    assert plan["blocked_asset_count"] == 1
    assert plan["approval_eligible"] is True
    assert plan["gate_status"] == "exact_owner_approval_required"
    assert plan["batches"][0]["source_ids"] == [1]
    assert plan["provider_request_proposal"]["request_count"] == 1
    assert plan["provider_request_proposal"]["provider_call_authorized"] is False
    assert plan["provider_request_proposal"]["requests"][0]["window"] == {
        "start": "2026-01-01T00:00:00+00:00",
        "end": "2026-01-02T00:00:00+00:00",
    }


def test_kline_approval_packet_is_one_envelope_for_every_batch_and_write_target(
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
    )

    assert packet["bound_facts"]["migration_envelope"] == plan["migration_envelope"]
    assert packet["bound_facts"]["write_targets"] == _write_targets(tmp_path)
    assert packet["bound_facts"]["migration_envelope"]["batch_manifest"] == [
        {
            "batch_key": batch["batch_key"],
            "batch_digest": batch["batch_digest"],
        }
        for batch in plan["batches"]
    ]
    assert "rb:continuous:1m" in json.dumps(packet)

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
        )
    except ValueError as exc:
        assert str(exc) == "TASK07_BATCH_DIGEST_MISMATCH"
    else:  # pragma: no cover
        raise AssertionError("tampered batch must fail")


def test_migration_envelope_rejects_missing_extra_reordered_or_tampered_batches(
    tmp_path: Path,
) -> None:
    plan = build_migration_plan(
        build_inventory_index(
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
        ),
        write_targets=_write_targets(tmp_path),
    )
    mutations = []
    missing = deepcopy(plan)
    missing["migration_envelope"]["batch_manifest"].pop()
    mutations.append(missing)
    extra = deepcopy(plan)
    extra["migration_envelope"]["batch_manifest"].append(
        {"batch_key": "zn:continuous:1m", "batch_digest": "a" * 64}
    )
    mutations.append(extra)
    reordered = deepcopy(plan)
    reordered["batches"].reverse()
    mutations.append(reordered)
    tampered = deepcopy(plan)
    tampered["migration_envelope"]["merkle_root"] = "0" * 64
    mutations.append(tampered)

    for mutated in mutations:
        with pytest.raises(
            ValueError,
            match="TASK07_(?:MIGRATION_ENVELOPE|BATCH_ORDER|PLAN_DIGEST)",
        ):
            build_approval_packet(mutated, command="data.task07.apply")


def test_same_migration_envelope_hash_preflights_every_exact_member_batch(
    tmp_path: Path,
) -> None:
    assets = []
    for source_id, symbol in ((1, "jm"), (2, "rb")):
        source = tmp_path / f"{symbol}.parquet"
        source.write_bytes(symbol.encode())
        checksum = sha256(source.read_bytes()).hexdigest()
        assets.append(
            _asset(
                market_data_file_id=source_id,
                symbol=symbol,
                contract_or_series=f"{symbol.upper()}.MAIN",
                file_path=str(source),
                checksum=checksum,
                physical_checksum=checksum,
                catalog_checksum=None,
            )
        )
    plan = build_migration_plan(
        build_inventory_index(
            assets,
            base_sha="3" * 40,
            database_revision="20260802_0031",
        ),
        write_targets=_write_targets(tmp_path),
    )
    packet = build_approval_packet(plan, command="data.task07.apply")
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = canonical_digest(packet)

    receipts = [
        task07.build_preflight_receipt(
            plan,
            packet_path=packet_path,
            approval_hash=approval_hash,
            current_base_sha="3" * 40,
            current_database_revision="20260802_0031",
            batch_key=batch["batch_key"],
            current_write_targets=_write_targets(tmp_path),
        )
        for batch in plan["batches"]
    ]

    assert [receipt["batch_key"] for receipt in receipts] == [
        "jm:continuous:1m",
        "rb:continuous:1m",
    ]
    assert {receipt["migration_approval_hash"] for receipt in receipts} == {
        approval_hash
    }


def test_runtime_cutover_receipt_has_no_public_synthetic_claim_builder() -> None:
    assert not hasattr(task07, "build_migration_verification_receipt")


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
        )
    except ValueError as exc:
        assert str(exc) in {"TASK07_PLAN_CONTROL_DRIFT", "TASK07_PLAN_DIGEST_MISMATCH"}
    else:  # pragma: no cover
        raise AssertionError("tampered K-line gate must fail")


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


def test_task07_kline_manifest_has_no_external_protected_root_argument() -> None:
    stdout = StringIO()
    stderr = StringIO()
    engine = create_engine("sqlite://")

    exit_code = main(
        [
            "data",
            "task07",
            "kline-manifest",
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
            "has_protected_root": hasattr(args, "protected_root"),
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "command": "task07.kline-manifest",
        "has_protected_root": False,
        "status": "passed",
    }


def _task07_inventory_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)"
        )
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
            "coverage_start TEXT, coverage_end TEXT, row_count INTEGER, manifest_version TEXT DEFAULT 'legacy-v1', "
            "manifest_uri TEXT DEFAULT 'missing.manifest.json', manifest_digest TEXT DEFAULT '0000000000000000000000000000000000000000000000000000000000000000')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE data_quality_reports (id INTEGER PRIMARY KEY, file_id INTEGER, task_id INTEGER, "
            "provider TEXT, data_type TEXT, instrument_symbol TEXT, contract_code TEXT, period TEXT, "
            "start_time TEXT, end_time TEXT, status TEXT, missing_bars INTEGER, duplicated_bars INTEGER, "
            "abnormal_price_count INTEGER, abnormal_volume_count INTEGER, details TEXT, created_at TEXT)"
        )
        connection.execute(
            text("INSERT INTO alembic_version VALUES ('20260802_0031')")
        )


def _task07_service_args(
    *, data_root: Path, canonical_root: Path, evidence_root: Path
) -> SimpleNamespace:
    return SimpleNamespace(
        project_root=Path(__file__).resolve().parents[4],
        data_root=data_root,
        canonical_root=canonical_root,
        evidence_root=evidence_root,
        database_revision=None,
    )


def test_task07_collection_reads_only_seven_frequency_kline_rows(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    canonical_root = tmp_path / "canonical"
    data_root.mkdir()
    canonical_root.mkdir()
    source = data_root / "source.parquet"
    source.write_bytes(b"bars")
    checksum = sha256(source.read_bytes()).hexdigest()
    engine = create_engine("sqlite://")
    _task07_inventory_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO market_data_files VALUES "
                "(1,'rqdata','bars','jm','JM.MAIN','1m','2026-01-01','2026-01-02',:path,4,:checksum,'v1',1,'primary','passed'),"
                "(2,'rqdata','bars','jm','JM.MAIN','4h','2026-01-01','2026-01-02',:path,4,:checksum,'v1',1,'primary','passed'),"
                "(3,'rqdata','indicator','jm','JM.MAIN','1m','2026-01-01','2026-01-02',:path,4,:checksum,'v1',1,'primary','passed')"
            ),
            {"path": str(source), "checksum": checksum},
        )

    with Session(engine) as session:
        assets = list(
            collect_task07_assets(
                session,
                data_root=data_root,
                canonical_root=canonical_root,
                inspect_content=False,
            )
        )

    assert [asset.market_data_file_id for asset in assets] == [1]
    assert assets[0].frequency == "1m"
    assert assets[0].data_type == "bars"


def test_task07_kline_manifest_service_creates_fresh_evidence_root(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    canonical_root = tmp_path / "canonical"
    evidence_root = tmp_path / "fresh-evidence"
    data_root.mkdir()
    canonical_root.mkdir()
    engine = create_engine("sqlite://")
    _task07_inventory_schema(engine)

    with Session(engine) as session:
        result = run_data_core_command(
            "task07.kline-manifest",
            session,
            _task07_service_args(
                data_root=data_root,
                canonical_root=canonical_root,
                evidence_root=evidence_root,
            ),
        )

    assert evidence_root.is_dir()
    assert (evidence_root / "kline-manifest-index.json").is_file()
    assert result["asset_count"] == 0
    assert result["manifest_scope"] == {
        "project_root": str(Path(__file__).resolve().parents[4]),
        "data_root": str(data_root),
        "canonical_root": str(canonical_root),
    }


def test_task07_kline_manifest_blocks_registered_path_outside_data_roots(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    canonical_root = tmp_path / "canonical"
    registered_root = tmp_path / "registered"
    evidence_root = tmp_path / "evidence"
    for path in (data_root, canonical_root, registered_root):
        path.mkdir()
    payload = b"trusted-looking-bars"
    target = data_root / "bars.parquet"
    target.write_bytes(payload)
    registered = registered_root / "linked.parquet"
    registered.symlink_to(target)
    engine = create_engine("sqlite://")
    _task07_inventory_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO market_data_files VALUES "
                "(1,'rqdata','bars','jm','JM.MAIN','1m','2026-01-01','2026-01-02',"
                ":path,:size,:checksum,'legacy-v1',1,'primary','passed')"
            ),
            {
                "path": str(registered),
                "size": len(payload),
                "checksum": sha256(payload).hexdigest(),
            },
        )

    with Session(engine) as session:
        result = run_data_core_command(
            "task07.kline-manifest",
            session,
            _task07_service_args(
                data_root=data_root,
                canonical_root=canonical_root,
                evidence_root=evidence_root,
            ),
        )

    asset = json.loads((evidence_root / "kline-assets-000001.jsonl").read_text())
    assert asset["source_scope"] == "approved_data_root"
    assert asset["physical_is_symlink"] is True
    assert asset["disposition"] == AssetDisposition.CONFLICT_BLOCKED
    assert result["classification_counts"][AssetDisposition.CONFLICT_BLOCKED] == 1


def test_task07_plan_service_emits_the_exact_hash_verified_by_owner_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_root = tmp_path / "canonical"
    evidence_root = tmp_path / "evidence"
    staging_root = tmp_path / "staging"
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    canonical_root.mkdir()
    project_root.mkdir()
    data_root.mkdir()
    index = write_kline_manifest_evidence(
        [_asset(catalog_checksum=None)],
        evidence_root=evidence_root,
        base_sha="9" * 40,
        database_revision="20260802_0031",
        manifest_scope={
            "project_root": str(project_root),
            "data_root": str(data_root),
            "canonical_root": str(canonical_root),
        },
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._postgresql_target",
        lambda _session: _write_targets(tmp_path)["postgresql_target"],
    )

    with Session(create_engine("sqlite://")) as session:
        result = run_data_core_command(
            "task07.plan",
            session,
            SimpleNamespace(
                manifest=evidence_root / "kline-manifest-index.json",
                staging_root=staging_root,
                canonical_root=canonical_root,
            ),
        )

    packet = result["approval_packet"]
    assert index["status"] == "complete"
    assert packet is not None
    assert result["approval_packet_hash"] == canonical_digest(packet)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    assert verify_exact_approval(
        packet_path,
        approval_hash=result["approval_packet_hash"],
        expected_command="data.task07.apply",
        current_facts=packet["bound_facts"],
    ) == packet


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


def test_task07_migration_verify_cli_forwards_exact_ordered_apply_receipts(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    stderr = StringIO()
    engine = create_engine("sqlite://")
    observed: dict[str, object] = {}

    def runner(command, _session, args):
        observed["command"] = command
        observed["apply_receipt"] = args.apply_receipt
        return {"status": "passed", "command": command}

    receipt_one = tmp_path / "batch-1.json"
    receipt_two = tmp_path / "batch-2.json"
    exit_code = main(
        [
            "data",
            "task07",
            "migration-verify",
            "--plan",
            str(tmp_path / "plan.json"),
            "--approval-packet",
            str(tmp_path / "approval.json"),
            "--approval-hash",
            "a" * 64,
            "--canonical-root",
            str(tmp_path / "canonical"),
            "--apply-receipt",
            str(receipt_one),
            "--apply-receipt",
            str(receipt_two),
        ],
        session_factory=lambda: Session(engine),
        data_core_runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert observed == {
        "command": "task07.migration-verify",
        "apply_receipt": [receipt_one, receipt_two],
    }


def test_retirement_plan_cli_rejects_arbitrary_runtime_root_argument(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "task07",
            "retirement-plan",
            "--project-root",
            str(tmp_path),
            "--runtime-root",
            str(tmp_path / "arbitrary-runtime"),
        ],
        session_factory=lambda: (_ for _ in ()).throw(
            AssertionError("invalid CLI must not open database")
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


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
        session.add(
            _registered_file_from_plan_source(plan["batches"][0]["sources"][0])
        )
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

    migration_verify_args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        canonical_root=tmp_path / "canonical",
        apply_receipt=[receipt_path],
    )
    with Session(engine) as session, pytest.raises(
        ValueError,
        match="TASK07_MIGRATION_APPLY_RECEIPT_SET_INVALID",
    ):
        run_data_core_command(
            "task07.migration-verify",
            session,
            SimpleNamespace(
                **{
                    **vars(migration_verify_args),
                    "apply_receipt": [receipt_path, receipt_path],
                }
            ),
        )
    with Session(engine) as session:
        migration_verified = run_data_core_command(
            "task07.migration-verify",
            session,
            migration_verify_args,
        )
    assert migration_verified["status"] == "passed"
    assert migration_verified["verified_batch_count"] == 1
    assert migration_verified["runtime_cutover_eligible"] is True
    assert migration_verified["migration_approval_hash"] == approval_hash


def test_task07_aggregate_preflight_uses_schema_only_converter_without_provider_or_aggregation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.data_core.cli_service as cli_module

    source = tmp_path / "aggregate.parquet"
    pq.write_table(
        pa.table(
            {
                "datetime": [datetime(2026, 3, 31, 21, 5)],
                "trading_day": [date(2026, 4, 1)],
                "open": ["100.10"],
                "high": ["100.50"],
                "low": ["99.90"],
                "close": ["100.30"],
                "volume": ["12"],
                "turnover": ["1203.60"],
                "open_interest": ["30"],
                "period": ["5m"],
                "source_interval": ["1m"],
            }
        ),
        source,
    )
    checksum = sha256(source.read_bytes()).hexdigest()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            MarketDataFile(
                id=1,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="a",
                contract_code="A.MAIN",
                period="5m",
                start_time=datetime(2026, 3, 31, 21, 5, tzinfo=UTC),
                end_time=datetime(2026, 3, 31, 21, 5, tzinfo=UTC),
                file_path=str(source),
                row_count=1,
                file_size_bytes=source.stat().st_size,
                checksum=checksum,
                data_version="legacy-aggregate-v1",
                data_role="primary",
                quality_status="passed",
            )
        )
        session.add(
            DataQualityReport(
                id=11,
                file_id=1,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="a",
                contract_code="A.MAIN",
                period="5m",
                start_time=datetime(2026, 3, 31, 21, 5, tzinfo=UTC),
                end_time=datetime(2026, 3, 31, 21, 5, tzinfo=UTC),
                status="passed",
                missing_bars=0,
                duplicated_bars=0,
                abnormal_price_count=0,
                abnormal_volume_count=0,
                details={},
                created_at=datetime(2026, 7, 8, tzinfo=UTC),
            )
        )
        session.commit()
        quality_records = task07.read_task07_quality_evidence(
            session,
            market_data_file_id=1,
        )
    quality_digest = canonical_digest(quality_records)
    registration_snapshot = {
        "id": 1,
        "provider": "rqdata",
        "data_type": "bars",
        "symbol": "a",
        "contract_or_series": "A.MAIN",
        "frequency": "5m",
        "data_role": "primary",
        "quality_status": "passed",
        "file_path": str(source),
        "file_size_bytes": source.stat().st_size,
        "checksum": checksum,
        "coverage_start": "2026-03-31T21:05:00+00:00",
        "coverage_end": "2026-03-31T21:05:00+00:00",
        "row_count": 1,
        "data_version": "legacy-aggregate-v1",
    }
    batch = {
        "batch_key": "a:continuous:5m",
        "dataset_kind": "continuous",
        "symbol": "a",
        "frequency": "5m",
        "dataset_origin": "preaggregated_from_1m",
        "sources": [
            {
                "market_data_file_id": 1,
                "contract_or_series": "A.MAIN",
                "file_path": str(source),
                "physical_checksum": checksum,
                "disposition": "REUSE_VERIFIED_AGGREGATE",
                "coverage_start": "2026-03-31T21:05:00+00:00",
                "coverage_end": "2026-03-31T21:05:00+00:00",
                "row_count": 1,
                "data_version": "legacy-aggregate-v1",
                "source_frequency": "1m",
                "manifest_format": "canonical-manifest-v2",
                "manifest_version": "task07-aggregate-migration-v1",
                "quality_evidence_digest": quality_digest,
                "main_map_digest": None,
                "registered_min_datetime": "2026-03-31T21:05:00+00:00",
                "registered_max_datetime": "2026-03-31T21:05:00+00:00",
                "physical_row_count": 1,
                "physical_min_datetime": "2026-03-31T21:05:00",
                "physical_max_datetime": "2026-03-31T21:05:00",
                "declared_periods": ["5m"],
                "source_intervals": ["1m"],
                "registration_wall_clock_matches": True,
                "registration_snapshot": registration_snapshot,
                "registration_snapshot_digest": canonical_digest(
                    registration_snapshot
                ),
            }
        ],
    }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("aggregate preflight must not aggregate or call RQData")

    monkeypatch.setattr(cli_module, "aggregate_bars", forbidden)
    monkeypatch.setattr(cli_module, "CanonicalRQDataAdapter", forbidden)
    with Session(engine) as session:
        validation, prepared = cli_module._task07_validate_batch_readonly(
            session,
            batch=batch,
        )

    assert validation[0]["dataset"]["frequency"] == "5m"
    assert validation[0]["dataset_origin"] == "preaggregated_from_1m"
    assert validation[0]["quality_evidence_digest"] == quality_digest
    assert prepared[0][1].evidence.schema_conversion_only is True

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE market_data_files SET data_role = 'candidate' WHERE id = 1")
        )
    with Session(engine) as session, pytest.raises(
        ValueError,
        match="TASK07_SOURCE_REGISTRATION_DRIFT",
    ):
        cli_module._task07_validate_batch_readonly(session, batch=batch)

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE market_data_files SET data_role = 'primary' WHERE id = 1")
        )
        connection.execute(
            text("UPDATE data_quality_reports SET missing_bars = 1 WHERE id = 11")
        )
    with Session(engine) as session:
        invalid_quality = task07.read_task07_quality_evidence(
            session,
            market_data_file_id=1,
        )
    batch["sources"][0]["quality_evidence_digest"] = canonical_digest(
        invalid_quality
    )
    with Session(engine) as session, pytest.raises(
        ValueError,
        match="TASK07_QUALITY_EVIDENCE_INVALID",
    ):
        cli_module._task07_validate_batch_readonly(session, batch=batch)


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
        lambda _session, *, batch, canonical_root=None: (
            validation,
            [
                (
                    source,
                    SimpleNamespace(
                        lineage=None,
                        source_id=int(source["market_data_file_id"]),
                    ),
                )
                for source in batch["sources"]
            ],
        ),
    )
    monkeypatch.setattr(
        "app.data_core.cli_service.verify_task07_published_batch",
        lambda receipt, **_kwargs: {"status": "passed", "source": receipt["market_data_file_id"]},
    )
    attempts: list[int] = []

    def first_attempt(prepared, **_kwargs):
        attempts.append(prepared.source_id)
        if prepared.source_id == 2:
            raise RuntimeError("injected second-source failure")
        body = {
            "market_data_file_id": prepared.source_id,
            "status": "passed",
            "batch_key": f"jm:continuous:1m:{prepared.source_id}",
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
        attempts.append(prepared.source_id)
        body = {
            "market_data_file_id": prepared.source_id,
            "status": "passed",
            "batch_key": f"jm:continuous:1m:{prepared.source_id}",
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
        verified_partition_readbacks=[],
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
            verified_partition_readbacks=[],
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
                _registered_file_from_plan_source(source)
                for source in plan["batches"][0]["sources"]
            ]
        )
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
