from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile
from app.services.profile_binding_candidate_generator import (
    build_sealing_evidence_index,
    generate_profile_binding_candidates,
    load_products_file,
    write_candidate_generation_outputs,
)
from app.services.profile_target_resolver import ProfileEvidencePaths


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _seed_sealing_dir(tmp_path: Path, *, file_id: int, file_path: Path) -> Path:
    sealing_dir = tmp_path / "sealing"
    _write_csv(
        sealing_dir / "disposition_register.csv",
        [
            {
                "standard_path": str(file_path),
                "disposition": "active_passed",
            }
        ],
    )
    _write_csv(
        sealing_dir / "checksum_matrix.csv",
        [
            {
                "physical_path": str(file_path),
                "checksum_status": "checksum_matched",
            }
        ],
    )
    _write_csv(
        sealing_dir / "asset_physical_inventory.csv",
        [
            {
                "physical_path": str(file_path),
                "physical_exists": "true",
            }
        ],
    )
    _write_csv(
        sealing_dir / "target_coverage_matrix.csv",
        [
            {
                "product": "jm",
                "symbol_or_contract": "jm.MAIN",
                "period": "1d",
                "sealing_status": "sealing_passed",
                "db_market_data_file_id": str(file_id),
            }
        ],
    )
    _write_csv(sealing_dir / "duplicate_inventory.csv", [])
    _write_csv(
        sealing_dir / "target_asset_catalog.csv",
        [
            {
                "product": "jm",
                "symbol_or_contract": "jm.MAIN",
                "period": "1d",
                "contract_role": "dominant_main",
            }
        ],
    )
    return sealing_dir


def test_load_products_file(tmp_path: Path) -> None:
    products_file = tmp_path / "products.txt"
    products_file.write_text("jm\n# comment\nrb\n", encoding="utf-8")
    assert load_products_file(products_file) == {"jm", "rb"}


def test_generate_profile_binding_candidates_for_jm(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = tmp_path / "jm_MAIN_1d.parquet"
    pd.DataFrame({"datetime": [datetime(2023, 1, 3)]}).to_parquet(parquet_path, index=False)
    sealing_dir = _seed_sealing_dir(tmp_path, file_id=1, file_path=parquet_path)
    expected_windows = tmp_path / "audit_v2_expected_windows.csv"
    _write_csv(
        expected_windows,
        [
            {
                "product": "jm",
                "contract_role": "dominant_main",
                "period": "1d",
                "source_role": "derived_from_1m",
                "target_start": "2023-01-03",
                "target_end": "2026-07-10",
                "boundary_status": "start_boundary_supported",
            }
        ],
    )
    config_path = tmp_path / "intraday.json"
    config_path.write_text(
        '{"target_policy":{"rules":[{"source":"audit_v2_expected_windows",'
        '"contract_role":"dominant_main","periods":["1d"],'
        '"source_role":"derived_from_1m"}]}}',
        encoding="utf-8",
    )

    with SessionLocal() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research V1",
                description="test",
                contract_roles=["dominant_main"],
                periods=["1d"],
                quality_policy="passed_only",
                provider="rqdata",
                config_path=str(config_path),
            )
        )
        session.add(
            MarketDataFile(
                id=1,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                start_time=datetime(2023, 1, 3, tzinfo=UTC),
                end_time=datetime(2026, 7, 10, tzinfo=UTC),
                file_path=str(parquet_path),
                row_count=1,
                checksum="a" * 64,
                data_version="20260711_v2",
                data_role="primary",
                quality_status="passed",
            )
        )
        session.commit()

        result = generate_profile_binding_candidates(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            sealing_dir=sealing_dir,
            project_root=tmp_path,
            evidence_paths=ProfileEvidencePaths(expected_windows=expected_windows),
        )
        current = [row for row in result.binding_candidates if row["candidate_status"] == "current"]
        assert len(current) == 1
        assert current[0]["market_data_file_id"] == 1
        assert current[0]["target_start"] == "2023-01-03"
        assert current[0]["target_end"] == "2026-07-10"
        assert current[0]["covers_target"] is True
        assert current[0]["selection_reason"] == "covers_target_canonical_current"

        output_dir = tmp_path / "output"
        paths = write_candidate_generation_outputs(output_dir, result)
        assert paths["binding_candidates"].exists()
        assert paths["blocked_ledger"].exists()
        assert paths["target_matrix"].exists()
        with pytest.raises(FileExistsError):
            write_candidate_generation_outputs(output_dir, result)


def test_build_sealing_evidence_index_reads_repair_classification(tmp_path: Path) -> None:
    sealing_dir = _seed_sealing_dir(tmp_path, file_id=10, file_path=tmp_path / "file.parquet")
    residual_dir = tmp_path / "residual"
    _write_csv(
        residual_dir / "repair_classification.csv",
        [
            {
                "anomaly_type": "duplicate_path_versions",
                "physical_path": str(tmp_path / "file.parquet"),
                "repair_type": "supersede",
                "needs_new_data_version": "false",
                "followup_task": "DIRECTION-A3-APPLY-DUP-SUPERSEDE",
                "canonical_file_id": "10",
            }
        ],
    )
    index = build_sealing_evidence_index(sealing_dir=sealing_dir, residual_dir=residual_dir)
    assert index.canonical_file_id_by_path[str(tmp_path / "file.parquet")] == 10
