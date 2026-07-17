from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.full_history_physical_inventory import (
    InventoryConfig,
    normalize_inventory_path,
    run_full_history_physical_inventory,
    scan_physical_asset,
    write_inventory_reports,
)


def test_normalize_absolute_and_relative_paths_to_same_key(tmp_path: Path) -> None:
    relative = Path("data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=a/contract=a.MAIN/a.parquet")
    absolute = tmp_path / relative

    relative_result = normalize_inventory_path(tmp_path, str(relative))
    absolute_result = normalize_inventory_path(tmp_path, str(absolute))

    assert relative_result.absolute_path == absolute_result.absolute_path
    assert relative_result.project_relative_path == relative.as_posix()
    assert absolute_result.project_relative_path == relative.as_posix()
    assert relative_result.outside_project_root is False


@pytest.fixture
def inventory_fixture(tmp_path: Path) -> tuple[Path, Session, Path]:
    path = (
        tmp_path
        / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=a/contract=a.MAIN/a_MAIN_1d.parquet"
    )
    path.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-02", "2026-07-10"]),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10, 20],
            "open_interest": [100.0, 200.0],
            "turnover": [1000.0, 2000.0],
            "symbol": ["a", "a"],
            "contract": ["a.MAIN", "a.MAIN"],
            "period": ["1d", "1d"],
            "provider": ["rqdata", "rqdata"],
            "data_role": ["primary", "primary"],
            "quality_status": ["passed", "passed"],
            "data_version": ["a_test_v1", "a_test_v1"],
            "trading_day": pd.to_datetime(["2020-01-02", "2026-07-10"]).date,
            "source_interval": ["1m", "1m"],
        }
    )
    frame.to_parquet(path, index=False)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest_root = tmp_path / "data/manifests"
    manifest_root.mkdir(parents=True)
    manifest_row = {
        "period": "1d",
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "row_count": 2,
        "min_datetime": "2020-01-02T00:00:00",
        "max_datetime": "2026-07-10T00:00:00",
        "checksum": checksum,
        "standard_path": str(path),
        "market_data_file_id": 1,
        "data_quality_report_id": 1,
        "data_version": "a_test_v1",
        "status": "success",
    }
    pd.DataFrame([manifest_row]).to_csv(manifest_root / "window-one.csv", index=False)
    pd.DataFrame([manifest_row]).to_csv(manifest_root / "window-two.csv", index=False)

    processed = tmp_path / "data/processed/v1b/a/a_summary.json"
    processed.parent.mkdir(parents=True)
    processed.write_text(
        json.dumps(
            {
                "symbol": "a",
                "contract": "a.MAIN",
                "periods": {
                    "1d": {
                        "data_version": "a_test_v1",
                        "quality_status": "failed",
                        "standard": {
                            "path": str(path),
                            "row_count": 2,
                            "min_datetime": "2020-01-02T00:00:00",
                            "max_datetime": "2026-07-10T00:00:00",
                            "checksum": checksum,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    db_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="a",
        contract_code="a.MAIN",
        period="1d",
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2026, 7, 10, tzinfo=UTC),
        file_path=str(path),
        row_count=2,
        file_size_bytes=path.stat().st_size,
        checksum=checksum,
        data_version="a_test_v1",
        data_role="primary",
        quality_status="warning",
    )
    session.add(db_file)
    session.flush()
    for status in ("passed", "warning"):
        session.add(
            DataQualityReport(
                file_id=db_file.id,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="a",
                contract_code="a.MAIN",
                period="1d",
                start_time=db_file.start_time,
                end_time=db_file.end_time,
                status=status,
                missing_bars=0,
                duplicated_bars=0,
                abnormal_price_count=0,
                abnormal_volume_count=0,
                details={},
            )
        )
    session.commit()
    return tmp_path, session, path


def test_inventory_aggregates_all_evidence_without_expected_matrix(
    inventory_fixture: tuple[Path, Session, Path],
) -> None:
    project_root, session, path = inventory_fixture
    result = run_full_history_physical_inventory(
        InventoryConfig(
            project_root=project_root,
            audit_end=date(2026, 7, 10),
            scan_mode="quick",
            products=("a",),
            require_postgresql=False,
        ),
        session,
    )

    row = next(item for item in result.physical_inventory if item["physical_path"] == str(path))
    assert row["manifest_record_count"] == 2
    assert row["processed_summary_record_count"] == 1
    assert row["db_record_count"] == 1
    assert json.loads(row["quality_report_ids"])
    assert json.loads(row["quality_statuses"]) == ["failed", "passed", "warning"]
    assert json.loads(row["quality_statuses_manifest"]) == ["passed"]
    assert json.loads(row["quality_statuses_processed"]) == ["failed"]
    assert json.loads(row["quality_statuses_db"]) == ["passed", "warning"]
    assert row["checksum_status"] == "not_computed"
    assert row["source_interval"] == '["1m"]'
    assert result.summary["status"] == "FULL_HISTORY_PHYSICAL_INVENTORY_SMOKE_READY"
    assert result.summary["expected_matrix_generated"] is False
    assert result.summary["representative_product_samples"]["a"]["db_record_count"] == 1
    assert result.summary["path_drift"]["missing_physical_rows"] == 0
    assert "expected" not in row
    assert "recommended_next_task" not in row


def test_direct_postgresql_requirement_fails_closed_on_sqlite(
    inventory_fixture: tuple[Path, Session, Path],
) -> None:
    project_root, session, _ = inventory_fixture

    with pytest.raises(RuntimeError, match="ENV_BLOCKED_DB"):
        run_full_history_physical_inventory(
            InventoryConfig(project_root=project_root, products=("a",)),
            session,
        )


def test_unfiltered_scope_cannot_be_ready_without_all_representative_products(
    inventory_fixture: tuple[Path, Session, Path],
) -> None:
    project_root, session, _ = inventory_fixture

    result = run_full_history_physical_inventory(
        InventoryConfig(project_root=project_root, require_postgresql=False),
        session,
    )

    assert result.summary["scope"] == "full"
    assert result.summary["status"] == "FULL_HISTORY_PHYSICAL_INVENTORY_PARTIAL"


def test_orphan_physical_and_db_only_missing_path_are_retained(
    inventory_fixture: tuple[Path, Session, Path],
) -> None:
    project_root, session, path = inventory_fixture
    orphan = path.with_name("a_orphan_1d.parquet")
    orphan.write_bytes(path.read_bytes())
    missing = path.with_name("a_missing_1d.parquet")
    session.add(
        MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="a",
            contract_code="a.MAIN",
            period="1d",
            start_time=datetime(2019, 1, 2, tzinfo=UTC),
            end_time=datetime(2019, 1, 3, tzinfo=UTC),
            file_path=str(missing),
            row_count=1,
            file_size_bytes=1,
            checksum="1" * 64,
            data_version="a_missing_v1",
            data_role="primary",
            quality_status="warning",
        )
    )
    session.commit()

    result = run_full_history_physical_inventory(
        InventoryConfig(project_root=project_root, products=("a",), require_postgresql=False),
        session,
    )

    orphan_row = next(item for item in result.physical_inventory if item["physical_path"] == str(orphan))
    missing_row = next(item for item in result.physical_inventory if item["physical_path"] == str(missing))
    assert orphan_row["physical_exists"] is True
    assert orphan_row["manifest_record_count"] == 0
    assert orphan_row["db_record_count"] == 0
    assert missing_row["physical_exists"] is False
    assert missing_row["physical_status"] == "missing_file"
    assert missing_row["db_record_count"] == 1


def test_full_scan_computes_checksum_and_detects_mismatch(inventory_fixture: tuple[Path, Session, Path]) -> None:
    project_root, session, path = inventory_fixture
    session.query(MarketDataFile).update({MarketDataFile.checksum: "0" * 64})
    session.commit()
    result = run_full_history_physical_inventory(
        InventoryConfig(
            project_root=project_root,
            audit_end=date(2026, 7, 10),
            scan_mode="full",
            products=("a",),
            require_postgresql=False,
        ),
        session,
    )
    row = next(item for item in result.physical_inventory if item["physical_path"] == str(path))
    assert row["checksum_actual"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert row["checksum_status"] == "declared_conflict"


def test_scan_records_empty_corrupt_and_schema_mismatch(tmp_path: Path) -> None:
    empty = tmp_path / "empty.parquet"
    empty.touch()
    corrupt = tmp_path / "corrupt.parquet"
    corrupt.write_bytes(b"not parquet")
    mismatched = tmp_path / "mismatched.parquet"
    pd.DataFrame({"datetime": pd.to_datetime(["2020-01-02"]), "close": [1.0]}).to_parquet(mismatched)

    assert scan_physical_asset(empty, scan_mode="quick")["physical_status"] == "empty_file"
    assert scan_physical_asset(corrupt, scan_mode="quick")["physical_status"] == "parquet_read_failed"
    mismatch = scan_physical_asset(mismatched, scan_mode="quick")
    assert mismatch["physical_status"] == "readable"
    assert mismatch["schema_status"] == "schema_mismatch"


def test_distinct_paths_and_schema_inconsistency_remain_separate(
    inventory_fixture: tuple[Path, Session, Path],
) -> None:
    project_root, session, path = inventory_fixture
    second = path.with_name("a_MAIN_1d_copy.parquet")
    second_frame = pd.read_parquet(path)
    second_frame["extra_column"] = "schema_variant"
    second_frame.to_parquet(second, index=False)
    manifest = project_root / "data/manifests/window-two.csv"
    evidence = pd.read_csv(manifest)
    second_row = evidence.iloc[0].copy()
    second_row["standard_path"] = str(second)
    evidence = pd.concat([evidence, second_row.to_frame().T], ignore_index=True)
    evidence.to_csv(manifest, index=False)
    result = run_full_history_physical_inventory(
        InventoryConfig(project_root=project_root, audit_end=date(2026, 7, 10), products=("a",), require_postgresql=False),
        session,
    )
    rows = [item for item in result.physical_inventory if item["asset_identity_key"].startswith("a|")]
    assert {item["physical_path"] for item in rows} >= {str(path), str(second)}
    assert max(item["duplicate_identity_count"] for item in rows) == 2
    assert {
        item["schema_consistency_status"]
        for item in rows
        if item["physical_path"] in {str(path), str(second)}
    } == {"inconsistent"}


def test_same_path_with_multiple_version_identities_is_flagged(
    inventory_fixture: tuple[Path, Session, Path],
) -> None:
    project_root, session, path = inventory_fixture
    manifest = project_root / "data/manifests/window-two.csv"
    evidence = pd.read_csv(manifest)
    conflicting = evidence.iloc[0].copy()
    conflicting["data_version"] = "a_conflicting_v2"
    pd.concat([evidence, conflicting.to_frame().T], ignore_index=True).to_csv(manifest, index=False)

    result = run_full_history_physical_inventory(
        InventoryConfig(project_root=project_root, products=("a",), require_postgresql=False),
        session,
    )
    rows = [item for item in result.physical_inventory if item["physical_path"] == str(path)]
    assert len({item["asset_identity_key"] for item in rows}) == 2
    assert all(item["identity_conflict"] is True for item in rows)


def test_writer_refuses_to_overwrite_existing_output(inventory_fixture: tuple[Path, Session, Path]) -> None:
    project_root, session, _ = inventory_fixture
    result = run_full_history_physical_inventory(
        InventoryConfig(project_root=project_root, audit_end=date(2026, 7, 10), products=("a",), require_postgresql=False),
        session,
    )
    output = project_root / "reports"
    write_inventory_reports(result, output)
    with pytest.raises(FileExistsError):
        write_inventory_reports(result, output)
