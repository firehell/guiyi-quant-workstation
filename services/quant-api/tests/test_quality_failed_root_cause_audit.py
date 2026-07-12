from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.quality_failed_root_cause_audit import audit_quality_failed_root_causes
from app.services.rqdata_ingest.parquet import sha256_file


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=bb/contract=bb.MAIN/bb_MAIN_1d.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "datetime": pd.date_range("2020-01-02", periods=3, freq="D"),
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [10, 11, 12],
            "open_interest": [100, 101, 102],
        }
    ).to_parquet(parquet_path, index=False)
    manifest = tmp_path / "data/manifests/rqdata_bb_v2_history_20200102_20260710.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": "1d",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "warning",
                "row_count": 3,
                "min_datetime": "2020-01-02T00:00:00",
                "max_datetime": "2020-01-04T00:00:00",
                "checksum": sha256_file(parquet_path),
                "standard_path": str(parquet_path),
                "data_version": "test_bb_1d",
                "status": "success",
            }
        ]
    ).to_csv(manifest, index=False)
    processed = tmp_path / "data/processed/v1b/bb/bb_v2_parquet_20200102_20260710.json"
    processed.parent.mkdir(parents=True, exist_ok=True)
    processed.write_text(
        json.dumps(
            {
                "symbol": "bb",
                "contract": "bb.MAIN",
                "periods": {
                    "1d": {
                        "quality_status": "failed",
                        "data_version": "test_bb_1d",
                        "standard": {
                            "path": str(parquet_path),
                            "row_count": 3,
                            "checksum": sha256_file(parquet_path),
                            "min_datetime": "2020-01-02T00:00:00",
                            "max_datetime": "2020-01-04T00:00:00",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    matrix = tmp_path / "target_coverage_matrix.csv"
    pd.DataFrame(
        [
            {
                "product": "bb",
                "symbol_or_contract": "bb.MAIN",
                "period": "1d",
                "year": year,
                "issue_type": "quality_failed",
                "standard_path": str(parquet_path),
            }
            for year in range(2020, 2027)
        ]
    ).to_csv(matrix, index=False)
    return parquet_path, matrix


def _add_warning_file(session: Session, path: Path) -> None:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="bb",
        contract_code="bb.MAIN",
        period="1d",
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2020, 1, 4, tzinfo=UTC),
        file_path=str(path),
        row_count=3,
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version="test_bb_1d",
        data_role="primary",
        quality_status="warning",
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="bb",
            contract_code="bb.MAIN",
            period="1d",
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status="warning",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=2,
            abnormal_volume_count=0,
            details={"original_quality_status": "failed"},
        )
    )


def test_quality_failed_root_cause_deduplicates_stale_processed_summary(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path, matrix = _fixture(tmp_path)
    with SessionLocal() as session:
        _add_warning_file(session, parquet_path)
        session.commit()
        before = session.scalar(select(func.count(MarketDataFile.id)))
        result = audit_quality_failed_root_causes(session=session, project_root=tmp_path, target_coverage_matrix=matrix)
        after = session.scalar(select(func.count(MarketDataFile.id)))

    assert result["candidate_target_row_count"] == 7
    assert result["unique_path_count"] == 1
    assert result["classification_counts"]["stale_processed_summary_failed"] == 1
    assert result["database_counts_unchanged"] is True
    assert before == after == 1
    assert result["ledger"][0]["processed_quality_statuses"] == "failed"
    assert result["ledger"][0]["db_quality_statuses"] == "warning"
