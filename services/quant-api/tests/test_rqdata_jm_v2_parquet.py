from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.jm_v2_parquet import build_jm_v2_parquet_assets
from app.services.rqdata_ingest.jm_v2_register import register_jm_v2_quality


class FakeJmV2Client:
    calls: list[tuple[str, date, date, str]] = []

    @staticmethod
    def underlying_symbol(product: str) -> str:
        return product.upper()

    @staticmethod
    def dominant_contracts(product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        assert product == "JM"
        assert rank == 1
        return pd.DataFrame(
            [
                {"date": start_date, "dominant": "JM2305"},
                {"date": date(2023, 1, 4), "dominant": "JM2305"},
                {"date": end_date, "dominant": "JM2309"},
            ]
        )

    @classmethod
    def contract_bars(cls, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        cls.calls.append((contract, start_date, end_date, frequency))
        rows = []
        if frequency == "1m":
            for day in pd.date_range(start_date, end_date, freq="D"):
                for minute in range(60):
                    rows.append(
                        {
                            "datetime": pd.Timestamp(day.date()) + pd.Timedelta(hours=9, minutes=minute),
                            "open": 100.0 + minute,
                            "high": 102.0 + minute,
                            "low": 99.0 + minute,
                            "close": 101.0 + minute,
                            "volume": 10,
                            "open_interest": 1000,
                        }
                    )
        else:
            for day in pd.date_range(start_date, end_date, freq="D"):
                rows.append(
                    {
                        "datetime": pd.Timestamp(day.date()) + pd.Timedelta(hours=15),
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.0,
                        "volume": 10,
                        "open_interest": 1000,
                    }
                )
        frame = pd.DataFrame(rows)
        frame["order_book_id"] = contract
        return frame


def test_build_jm_v2_parquet_assets_writes_raw_and_standard_without_db(tmp_path: Path) -> None:
    FakeJmV2Client.calls = []
    summary = build_jm_v2_parquet_assets(
        client=FakeJmV2Client(),
        output_root=tmp_path,
        start_date=date(2023, 1, 3),
        end_date=date(2023, 1, 5),
        periods=("1m", "30m"),
    )

    assert summary["mode"] == "jm-v2-parquet"
    assert summary["writes_database"] is False
    assert list(summary["periods"]) == ["1m", "30m"]
    assert {call[-1] for call in FakeJmV2Client.calls} == {"1m"}

    one_minute = summary["periods"]["1m"]
    assert one_minute["data_version"] == "rqdata_jm_standard_1m_20230103_20230105_v2"
    assert one_minute["derivation_mode"] == "rqdata_direct"
    assert one_minute["raw"]["path"].endswith("jm_1m_dominant_raw_20230103_20230105_v2.parquet")
    assert one_minute["standard"]["path"].endswith("jm_MAIN_1m_20230103_20230105_v2.parquet")
    assert one_minute["standard"]["row_count"] == 180
    assert len(one_minute["standard"]["checksum"]) == 64

    thirty_minute = summary["periods"]["30m"]
    assert thirty_minute["derivation_mode"] == "aggregated_from_1m"
    assert thirty_minute["standard"]["row_count"] == 6

    standard_frame = pd.read_parquet(one_minute["standard"]["path"])
    assert standard_frame["provider"].unique().tolist() == ["rqdata"]
    assert standard_frame["data_role"].unique().tolist() == ["primary"]
    assert standard_frame["quality_status"].unique().tolist() == ["passed"]

    aggregated_frame = pd.read_parquet(thirty_minute["standard"]["path"])
    assert aggregated_frame["source_interval"].unique().tolist() == ["1m"]


def test_register_jm_v2_quality_records_market_files_reports_and_manifest(tmp_path: Path) -> None:
    FakeJmV2Client.calls = []
    summary = build_jm_v2_parquet_assets(
        client=FakeJmV2Client(),
        output_root=tmp_path,
        start_date=date(2023, 1, 3),
        end_date=date(2023, 1, 5),
        periods=("1m", "30m"),
    )
    summary_path = tmp_path / "processed" / "v1b" / "jm" / "summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    manifest_path = tmp_path / "manifests" / "rqdata_jm_v2_history_20230103_20230105.csv"

    with TestingSessionLocal() as session:
        result = register_jm_v2_quality(session=session, summary_path=summary_path, manifest_path=manifest_path)
        session.commit()

        files = list(session.scalars(select(MarketDataFile).order_by(MarketDataFile.period)))
        reports = list(session.scalars(select(DataQualityReport).order_by(DataQualityReport.period)))

    assert result["writes_database"] is True
    assert manifest_path.exists()
    manifest = pd.read_csv(manifest_path)
    assert sorted(manifest["period"].tolist()) == ["1m", "30m"]
    assert sorted(manifest["quality_status"].tolist()) == ["passed", "passed"]
    assert len(files) == 2
    assert len(reports) == 2
    assert {item.period for item in files} == {"1m", "30m"}
    assert {item.provider for item in files} == {"rqdata"}
    assert {item.data_role for item in files} == {"primary"}
    assert {item.quality_status for item in files} == {"passed"}
    assert {item.status for item in reports} == {"passed"}
    assert all(item.checksum and len(item.checksum) == 64 for item in files)
