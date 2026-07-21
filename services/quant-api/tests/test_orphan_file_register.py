from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.orphan_file_register import build_orphan_file_register_plan


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_orphan_plan_expects_warning_for_bb(tmp_path: Path) -> None:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=bb/contract=bb.MAIN/bb_MAIN_1d_20230103_20260707_v2.parquet"
    parquet_path.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "symbol": ["bb"] * 2,
            "contract": ["bb.MAIN"] * 2,
            "exchange": ["DCE"] * 2,
            "datetime": pd.to_datetime(["2023-01-03", "2023-01-04"], utc=True),
            "trading_day": pd.to_datetime(["2023-01-03", "2023-01-04"]).date,
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10, 11],
            "open_interest": [1000, 1001],
            "turnover": [10000, 11000],
            "period": ["1d", "1d"],
            "provider": ["rqdata", "rqdata"],
            "data_version": ["v2", "v2"],
            "data_role": ["primary", "primary"],
            "quality_status": ["passed", "passed"],
        }
    )
    frame.to_parquet(parquet_path, index=False)
    orphan_csv = tmp_path / "orphan_files.csv"
    orphan_csv.write_text(
        f"physical_path,product,period,contract,file_size_bytes,issue_class,disposition\n"
        f"{parquet_path.resolve()},bb,1d,bb.MAIN,1,orphan_file,register_or_archive\n",
        encoding="utf-8",
    )
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = build_orphan_file_register_plan(
            session=session,
            project_root=tmp_path,
            orphan_csv=orphan_csv,
            apply=False,
        )
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["expected_quality_status"] == "warning"
    assert result["candidates"][0]["decision"] == "ready"


def test_orphan_apply_registers_warning_without_upgrading(tmp_path: Path) -> None:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1w/exchange=DCE/symbol=bb/contract=bb.MAIN/bb_MAIN_1w_20230103_20260707_v2.parquet"
    parquet_path.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "symbol": ["bb"] * 3,
            "contract": ["bb.MAIN"] * 3,
            "exchange": ["DCE"] * 3,
            "datetime": pd.to_datetime(["2023-01-06", "2023-01-13", "2023-01-20"], utc=True),
            "trading_day": pd.to_datetime(["2023-01-06", "2023-01-13", "2023-01-20"]).date,
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10, 11, 12],
            "open_interest": [1000, 1001, 1002],
            "turnover": [10000, 11000, 12000],
            "period": ["1w"] * 3,
            "provider": ["rqdata"] * 3,
            "data_version": ["v2"] * 3,
            "data_role": ["primary"] * 3,
            "quality_status": ["passed"] * 3,
        }
    )
    frame.to_parquet(parquet_path, index=False)
    orphan_csv = tmp_path / "orphan_files.csv"
    orphan_csv.write_text(
        f"physical_path,product,period,contract,file_size_bytes,issue_class,disposition\n"
        f"{parquet_path.resolve()},bb,1w,bb.MAIN,1,orphan_file,register_or_archive\n",
        encoding="utf-8",
    )
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = build_orphan_file_register_plan(
            session=session,
            project_root=tmp_path,
            orphan_csv=orphan_csv,
            apply=True,
            confirm=True,
        )
        session.commit()
        registered = session.scalar(select(MarketDataFile).where(MarketDataFile.file_path == str(parquet_path.resolve())))

    assert result["apply_rows"][0]["quality_status"] == "warning"
    assert registered is not None
    assert registered.quality_status == "warning"
