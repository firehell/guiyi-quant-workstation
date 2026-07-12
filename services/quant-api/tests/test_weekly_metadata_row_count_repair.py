from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.weekly_metadata_row_count_repair import (
    EXPECTED_REPAIRS,
    apply_weekly_metadata_row_count_repair,
    build_weekly_metadata_row_count_repair_plan,
)
from app.services.rqdata_ingest.weekly_row_count_reconcile import DbMarketFileSnapshot


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_weekly_parquet(path: Path, *, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-02", periods=rows, freq="W-FRI"),
            "open": range(rows),
            "high": range(rows),
            "low": range(rows),
            "close": range(rows),
            "volume": range(rows),
            "open_interest": range(rows),
        }
    )
    frame.to_parquet(path, index=False)


def _asset_path(project_root: Path, product: str, file_name: str) -> Path:
    return (
        project_root
        / "data"
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / "period=1w"
        / "exchange=TEST"
        / f"symbol={product}"
        / f"contract={product}.MAIN"
        / file_name
    )


def _sibling_file_name(product: str) -> str:
    return f"{product}_MAIN_1w_20230103_20260711_v2.parquet"


def _build_project(project_root: Path, *, manifest_mismatch_product: str | None = None, products: list[str] | None = None) -> dict[str, Path]:
    products = products or [item.product for item in EXPECTED_REPAIRS]
    paths: dict[str, Path] = {}
    for expected in EXPECTED_REPAIRS:
        if expected.product not in products:
            continue
        old_path = _asset_path(project_root, expected.product, expected.file_name)
        sibling_path = _asset_path(project_root, expected.product, _sibling_file_name(expected.product))
        _write_weekly_parquet(old_path, rows=expected.target_row_count)
        _write_weekly_parquet(sibling_path, rows=expected.target_row_count + 1)
        paths[expected.product] = old_path

        manifest_rows = [
            {
                "period": "1w",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": expected.target_row_count - 1 if expected.product == manifest_mismatch_product else expected.target_row_count,
                "standard_path": str(old_path),
                "actual_contract": f"{expected.product}.MAIN",
                "status": "success",
                "data_version": f"test_{expected.product}_old",
            },
            {
                "period": "1w",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": expected.target_row_count + 1,
                "standard_path": str(sibling_path),
                "actual_contract": f"{expected.product}.MAIN",
                "status": "success",
                "data_version": f"test_{expected.product}_new",
            },
        ]
        manifest = project_root / "data" / "manifests" / f"rqdata_{expected.product}_v2_history_20230103_20260711.csv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(manifest_rows).to_csv(manifest, index=False)

        summary = project_root / "data" / "processed" / "v1b" / expected.product / f"{expected.product}_v2_parquet_20230103_20260707.json"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(
            f"""
{{
  "symbol": "{expected.product}",
  "contract": "{expected.product}.MAIN",
  "periods": {{
    "1w": {{
      "quality_status": "passed",
      "standard": {{
        "path": "{old_path}",
        "row_count": {expected.target_row_count}
      }}
    }}
  }}
}}
""".strip(),
            encoding="utf-8",
        )
    return paths


def _seed_market_files(session: Session, paths: dict[str, Path], project_root: Path) -> None:
    for expected in EXPECTED_REPAIRS:
        if expected.product not in paths:
            continue
        session.add(
            MarketDataFile(
                id=expected.db_file_id,
                provider="rqdata",
                data_type="bars",
                instrument_symbol=expected.product,
                contract_code=f"{expected.product}.MAIN",
                period="1w",
                start_time=datetime(2023, 1, 3, tzinfo=UTC),
                end_time=datetime(2026, 7, 7, tzinfo=UTC),
                file_path=str(paths[expected.product]),
                row_count=expected.old_row_count,
                file_size_bytes=123,
                checksum=f"checksum-{expected.product}",
                data_version=f"version-{expected.product}",
                data_role="primary",
                quality_status="passed",
            )
        )
        session.add(
            MarketDataFile(
                id=expected.db_file_id + 100000,
                provider="rqdata",
                data_type="bars",
                instrument_symbol=expected.product,
                contract_code=f"{expected.product}.MAIN",
                period="1w",
                start_time=datetime(2023, 1, 3, tzinfo=UTC),
                end_time=datetime(2026, 7, 11, tzinfo=UTC),
                file_path=str(_asset_path(project_root, expected.product, _sibling_file_name(expected.product))),
                row_count=expected.target_row_count + 1,
                file_size_bytes=456,
                checksum=f"sibling-{expected.product}",
                data_version=f"sibling-version-{expected.product}",
                data_role="primary",
                quality_status="passed",
            )
        )
    session.commit()


def _snapshots(session: Session) -> list[DbMarketFileSnapshot]:
    rows = session.scalars(select(MarketDataFile)).all()
    return [
        DbMarketFileSnapshot(
            id=row.id,
            file_path=row.file_path,
            row_count=row.row_count,
            start_time=row.start_time.isoformat(),
            end_time=row.end_time.isoformat(),
            checksum=row.checksum or "",
            data_role=row.data_role,
            quality_status=row.quality_status,
            data_version=row.data_version or "",
        )
        for row in rows
    ]


def test_repair_dry_run_does_not_update_database(tmp_path: Path) -> None:
    paths = _build_project(tmp_path)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_files(session, paths, tmp_path)
        plan = build_weekly_metadata_row_count_repair_plan(
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            db_status="available",
            db_rows=_snapshots(session),
        )

        assert plan["operation"] == "dry-run"
        assert plan["ready_to_apply"] is True
        assert plan["writes_database"] is False
        assert {row["decision"] for row in plan["candidates"]} == {"ready"}
        assert session.get(MarketDataFile, 44115).row_count == 47


def test_repair_apply_requires_confirmation(tmp_path: Path) -> None:
    paths = _build_project(tmp_path)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_files(session, paths, tmp_path)
        plan = build_weekly_metadata_row_count_repair_plan(
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            db_status="available",
            db_rows=_snapshots(session),
            apply=True,
            confirm=False,
        )

    assert plan["ready_to_apply"] is False
    assert "confirmation_required" in plan["blocked_reasons"]


def test_repair_rejects_candidate_count_not_three(tmp_path: Path) -> None:
    paths = _build_project(tmp_path, products=["ad"])
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_files(session, paths, tmp_path)
        plan = build_weekly_metadata_row_count_repair_plan(
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            db_status="available",
            db_rows=_snapshots(session),
        )

    assert plan["ready_to_apply"] is False
    assert "candidate_count_not_3" in plan["blocked_reasons"]


def test_repair_rejects_manifest_duckdb_mismatch(tmp_path: Path) -> None:
    paths = _build_project(tmp_path, manifest_mismatch_product="ad")
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_files(session, paths, tmp_path)
        plan = build_weekly_metadata_row_count_repair_plan(
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            db_status="available",
            db_rows=_snapshots(session),
        )

    ad = next(row for row in plan["candidates"] if row["product"] == "ad")
    assert plan["ready_to_apply"] is False
    assert "classification_not_old_version_metadata_stale" in ad["blocked_reasons"]


def test_repair_apply_updates_only_row_count(tmp_path: Path) -> None:
    paths = _build_project(tmp_path)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_market_files(session, paths, tmp_path)
        plan = build_weekly_metadata_row_count_repair_plan(
            project_root=tmp_path,
            output_dir=tmp_path / "reports",
            db_status="available",
            db_rows=_snapshots(session),
            apply=True,
            confirm=True,
        )
        result = apply_weekly_metadata_row_count_repair(session=session, plan=plan)
        session.commit()

        ad = session.get(MarketDataFile, 44115)
        sibling = session.get(MarketDataFile, 144115)

    assert result["writes_database"] is True
    assert {row["applied"] for row in result["apply_rows"]} == {True}
    assert ad.row_count == 55
    assert ad.checksum == "checksum-ad"
    assert ad.data_version == "version-ad"
    assert ad.data_role == "primary"
    assert ad.quality_status == "passed"
    assert sibling.row_count == 56
