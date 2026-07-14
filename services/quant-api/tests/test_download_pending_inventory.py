from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MainContractMap, MarketDataFile
from app.services.rqdata_ingest.download_pending_inventory import (
    audit_dominant_main_inventory,
    audit_roll_segment_inventory,
    classify_segment_coverage,
    classify_window_coverage,
    expected_rqdata_start,
    run_download_pending_inventory,
    write_pending_inventory_reports,
)
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_parquet(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_expected_rqdata_start_uses_listed_date_and_rq_floor() -> None:
    window = ProductWindow(
        product="al",
        window_start=date(2020, 1, 2),
        listed_date=date(1999, 1, 4),
        effective_1d_start=date(2020, 1, 2),
        note="",
    )
    assert expected_rqdata_start(window) == date(2000, 1, 4)
    assert expected_rqdata_start(window, period="1d") == date(2000, 1, 4)
    assert expected_rqdata_start(window, period="1w") == date(2000, 1, 4)
    assert expected_rqdata_start(window, period="1m") == date(2010, 1, 4)


def test_expected_rqdata_start_1m_uses_listed_when_after_minute_floor() -> None:
    window = ProductWindow(
        product="jm",
        window_start=date(2020, 1, 2),
        listed_date=date(2013, 3, 22),
        effective_1d_start=date(2020, 1, 2),
        note="",
    )
    assert expected_rqdata_start(window, period="1m") == date(2013, 3, 22)


@pytest.mark.parametrize(
    ("actual_min", "actual_max", "expected_status"),
    [
        (date(2000, 1, 4), date(2026, 7, 10), "covered"),
        (date(2020, 1, 2), date(2026, 7, 10), "partial_start"),
        (date(2000, 1, 4), date(2026, 6, 1), "partial_end"),
        (None, None, "missing"),
    ],
)
def test_classify_window_coverage(actual_min, actual_max, expected_status) -> None:
    status, _, _ = classify_window_coverage(
        expected_start=date(2000, 1, 4),
        expected_end=date(2026, 7, 10),
        actual_min=actual_min,
        actual_max=actual_max,
    )
    assert status == expected_status


def test_classify_segment_coverage_marks_missing_without_files() -> None:
    assert (
        classify_segment_coverage(
            segment_start=date(2024, 1, 1),
            segment_end=date(2024, 3, 1),
            actual_min=None,
            actual_max=None,
        )
        == "missing_segment"
    )


def test_audit_dominant_main_inventory_detects_pre2020_gap(tmp_path) -> None:
    parquet_path = tmp_path / "data" / "parquet" / "rb_MAIN_1d_v2.parquet"
    _write_parquet(
        parquet_path,
        [
            {"datetime": datetime(2020, 1, 2, tzinfo=UTC), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            {"datetime": datetime(2026, 7, 10, tzinfo=UTC), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        ],
    )
    market_files = [
        MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="1d",
            start_time=datetime(2020, 1, 2, tzinfo=UTC),
            end_time=datetime(2026, 7, 10, tzinfo=UTC),
            file_path=str(parquet_path),
            row_count=1,
            data_version="v2",
            data_role="primary",
            quality_status="passed",
        )
    ]
    windows = {
        "rb": ProductWindow(
            product="rb",
            window_start=date(2020, 1, 2),
            listed_date=date(2009, 3, 27),
            effective_1d_start=date(2020, 1, 2),
            note="",
        )
    }
    rows = audit_dominant_main_inventory(
        project_root=tmp_path,
        products=["rb"],
        product_windows=windows,
        market_files=market_files,
        audit_end=date(2026, 7, 10),
    )
    row_1d = next(item for item in rows if item["period"] == "1d")
    assert row_1d["status"] == "partial_start"
    assert row_1d["recommended_action"] == "daily_pre2020_backfill"


def test_audit_roll_segment_inventory_flags_missing_segment(tmp_path) -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        session.add_all(
            [
                MainContractMap(
                    provider="rqdata",
                    instrument_symbol="rb",
                    contract_code="RB2501",
                    rank=1,
                    trade_date=date(2024, 1, 2),
                    data_version="test-v1",
                ),
                MainContractMap(
                    provider="rqdata",
                    instrument_symbol="rb",
                    contract_code="RB2501",
                    rank=1,
                    trade_date=date(2024, 3, 1),
                    data_version="test-v1",
                ),
            ]
        )
        session.commit()
        market_files: list[MarketDataFile] = []
        windows = {
            "rb": ProductWindow(
                product="rb",
                window_start=date(2020, 1, 2),
                listed_date=date(2009, 3, 27),
                effective_1d_start=date(2020, 1, 2),
                note="",
            )
        }
        rows = audit_roll_segment_inventory(
            session=session,
            project_root=tmp_path,
            products=["rb"],
            product_windows=windows,
            market_files=market_files,
            audit_end=date(2026, 7, 10),
        )
        row_1w = next(item for item in rows if item["period"] == "1w")
        assert row_1w["status"] == "missing_segment"
        assert row_1w["recommended_action"] == "actual_contract_roll_write"


def test_write_pending_inventory_reports_outputs_required_files(tmp_path) -> None:
    result = run_download_pending_inventory(
        session=None,
        project_root=tmp_path,
        products=["rb"],
        product_windows={
            "rb": ProductWindow(
                product="rb",
                window_start=date(2020, 1, 2),
                listed_date=date(2009, 3, 27),
                effective_1d_start=date(2020, 1, 2),
                note="",
            )
        },
        audit_end=date(2026, 7, 10),
    )
    paths = write_pending_inventory_reports(result, output_dir=tmp_path / "out")
    assert paths["pending_download_matrix"].exists()
    assert paths["pending_download_summary"].exists()
    assert paths["pending_download_evidence"].exists()
    assert paths["download_queue_commands"].exists()
