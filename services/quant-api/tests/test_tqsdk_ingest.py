from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.manifest import CsvManifest
from app.services.tqsdk_ingest.db import TqSdkIngestRecorder
from app.services.tqsdk_ingest.downloader import download_main_1m_csv
from app.services.tqsdk_ingest.products import DEFAULT_CORE_PRODUCTS, product_spec
from app.services.tqsdk_ingest.quality import evaluate_1m_quality
from app.services.tqsdk_ingest.transformer import (
    build_month_chunks,
    canonical_path,
    raw_path,
    transform_downloader_csv,
)


def _write_downloader_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "datetime,datetime_nano,KQ.m@SHFE.rb.open,KQ.m@SHFE.rb.high,KQ.m@SHFE.rb.low,KQ.m@SHFE.rb.close,KQ.m@SHFE.rb.volume,KQ.m@SHFE.rb.open_oi,KQ.m@SHFE.rb.close_oi",
                "2026-05-06 09:01:00.000000000,1778029260000000000,3000,3010,2990,3005,100,1000,1005",
                "2026-05-06 09:02:00.000000000,1778029320000000000,3005,3015,3001,3012,120,1005,1010",
            ]
        ),
        encoding="utf-8",
    )


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_core_products_and_month_chunks_are_plan_aligned() -> None:
    assert DEFAULT_CORE_PRODUCTS == [
        "rb",
        "hc",
        "i",
        "j",
        "jm",
        "TA",
        "MA",
        "EG",
        "l",
        "pp",
        "v",
        "SA",
        "FG",
        "sc",
        "fu",
        "bu",
        "pg",
        "cu",
        "al",
        "zn",
        "pb",
        "ni",
        "sn",
        "au",
        "ag",
    ]
    assert product_spec("rb").download_symbol == "KQ.m@SHFE.rb"
    assert product_spec("TA").download_symbol == "KQ.m@CZCE.TA"

    chunks = build_month_chunks(date(2026, 5, 20), date(2026, 7, 3))

    assert [(chunk.start, chunk.end, chunk.key_suffix) for chunk in chunks] == [
        (date(2026, 5, 20), date(2026, 5, 31), "2026-05"),
        (date(2026, 6, 1), date(2026, 6, 30), "2026-06"),
        (date(2026, 7, 1), date(2026, 7, 3), "2026-07"),
    ]


def test_transformer_writes_plan_fields_and_paths(tmp_path) -> None:
    csv_path = tmp_path / "rb_2026_05.csv"
    _write_downloader_csv(csv_path)
    spec = product_spec("rb")

    raw_frame, canonical_frame = transform_downloader_csv(csv_path, spec=spec, year=2026, month=5)

    assert raw_frame["download_symbol"].unique().tolist() == ["KQ.m@SHFE.rb"]
    assert raw_frame["product"].unique().tolist() == ["rb"]
    assert canonical_frame[["symbol", "contract", "exchange", "period", "provider"]].iloc[0].to_dict() == {
        "symbol": "rb",
        "contract": "rb.MAIN",
        "exchange": "SHFE",
        "period": "1m",
        "provider": "tqsdk",
    }
    assert canonical_frame["source_contract"].unique().tolist() == ["KQ.m@SHFE.rb"]
    assert canonical_frame["is_main_continuous"].unique().tolist() == [True]
    assert canonical_frame["open_interest"].tolist() == [1005.0, 1010.0]
    assert canonical_frame["data_version"].unique().tolist() == ["tqsdk_main_1m_rb_2026_05_canonical_v1"]

    assert raw_path(tmp_path, spec, 2026, 5).as_posix().endswith(
        "raw/tqsdk/main_continuous_1m/product=rb/year=2026/month=05/part-000.parquet"
    )
    assert canonical_path(tmp_path, spec, 2026, 5).as_posix().endswith(
        "parquet/canonical/bars/provider=tqsdk/period=1m/exchange=SHFE/symbol=rb/contract=rb.MAIN/year=2026/month=05/part-000.parquet"
    )


def test_downloader_uses_data_downloader_for_main_1m_csv(tmp_path) -> None:
    calls = {}

    class FakeApi:
        def __init__(self) -> None:
            self.wait_count = 0

        def wait_update(self) -> None:
            self.wait_count += 1

    class FakeDownloader:
        def __init__(self, api, symbol_list, dur_sec, start_dt, end_dt, csv_file_name):
            calls["api"] = api
            calls["symbol_list"] = symbol_list
            calls["dur_sec"] = dur_sec
            calls["start_dt"] = start_dt
            calls["end_dt"] = end_dt
            calls["csv_file_name"] = csv_file_name
            self.finished = False

        def is_finished(self) -> bool:
            if not self.finished:
                self.finished = True
                return False
            return True

    api = FakeApi()
    output_path = tmp_path / "downloads/rb.csv"

    result = download_main_1m_csv(
        api=api,
        spec=product_spec("rb"),
        start=date(2026, 5, 1),
        end=date(2026, 5, 31),
        output_path=output_path,
        downloader_cls=FakeDownloader,
    )

    assert result == output_path
    assert calls["symbol_list"] == "KQ.m@SHFE.rb"
    assert calls["dur_sec"] == 60
    assert calls["start_dt"] == date(2026, 5, 1)
    assert calls["end_dt"] == date(2026, 5, 31)
    assert calls["csv_file_name"] == str(output_path)
    assert api.wait_count == 1


def test_quality_detects_duplicates_gaps_and_abnormal_rows() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2026-05-06 09:01:00",
                    "2026-05-06 09:01:00",
                    "2026-05-06 09:04:00",
                ]
            ),
            "open": [3000.0, 3000.0, 3020.0],
            "high": [3010.0, 3010.0, 3010.0],
            "low": [2990.0, 2990.0, 3030.0],
            "close": [3005.0, 3005.0, 3025.0],
            "volume": [100, 100, -1],
            "open_interest": [1000.0, 1000.0, -5.0],
        }
    )

    quality = evaluate_1m_quality(frame)

    assert quality.status == "failed"
    assert quality.missing_bars == 2
    assert quality.duplicated_bars == 1
    assert quality.abnormal_price_count == 1
    assert quality.abnormal_volume_count == 1
    assert quality.details["abnormal_open_interest_count"] == 1
    assert quality.details["check_rule_version"] == "tqsdk_main_1m_v0"


def test_recorder_upserts_raw_and_canonical_files_and_replaces_quality(tmp_path) -> None:
    csv_path = tmp_path / "rb_2026_05.csv"
    _write_downloader_csv(csv_path)
    spec = product_spec("rb")
    raw_frame, canonical_frame = transform_downloader_csv(csv_path, spec=spec, year=2026, month=5)
    raw_file = tmp_path / "data/raw/tqsdk/main_continuous_1m/product=rb/year=2026/month=05/part-000.parquet"
    canonical_file = (
        tmp_path
        / "data/parquet/canonical/bars/provider=tqsdk/period=1m/exchange=SHFE/symbol=rb/contract=rb.MAIN/year=2026/month=05/part-000.parquet"
    )

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        recorder = TqSdkIngestRecorder(session=session, project_root=tmp_path)
        task = recorder.start_task(spec=spec, chunk_start=date(2026, 5, 1), chunk_end=date(2026, 5, 31))
        recorder.record_chunk(
            task=task,
            spec=spec,
            year=2026,
            month=5,
            chunk_start=date(2026, 5, 1),
            chunk_end=date(2026, 5, 31),
            raw_path=raw_file,
            raw_frame=raw_frame,
            canonical_path=canonical_file,
            canonical_frame=canonical_frame,
            source_csv=csv_path,
        )
        recorder.finish_task(task, status="success", row_count=len(canonical_frame))
        session.commit()

        recorder = TqSdkIngestRecorder(session=session, project_root=tmp_path)
        task = recorder.start_task(spec=spec, chunk_start=date(2026, 5, 1), chunk_end=date(2026, 5, 31))
        recorder.record_chunk(
            task=task,
            spec=spec,
            year=2026,
            month=5,
            chunk_start=date(2026, 5, 1),
            chunk_end=date(2026, 5, 31),
            raw_path=raw_file,
            raw_frame=raw_frame,
            canonical_path=canonical_file,
            canonical_frame=canonical_frame,
            source_csv=csv_path,
        )
        recorder.finish_task(task, status="success", row_count=len(canonical_frame))
        session.commit()

        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 2
        assert session.scalar(select(func.count()).select_from(DataQualityReport)) == 1
        canonical = session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "main_continuous_kline"))
        assert canonical is not None
        assert canonical.provider == "tqsdk"
        assert canonical.period == "1m"
        assert canonical.contract_code == "rb.MAIN"
        assert canonical.quality_status == "passed"
        assert duckdb.sql(f"select count(*) from read_parquet('{canonical.file_path}')").fetchone()[0] == 2


def test_manifest_resume_and_retry_failed_behavior(tmp_path) -> None:
    manifest = CsvManifest(tmp_path / "tqsdk_bars_1m.csv")

    assert manifest.should_run("rb:1m:2026-05", resume=True, retry_failed=False)
    manifest.mark("rb:1m:2026-05", "success")
    manifest.mark("hc:1m:2026-05", "failed", "network")

    assert not manifest.should_run("rb:1m:2026-05", resume=True, retry_failed=False)
    assert manifest.should_run("rb:1m:2026-05", resume=False, retry_failed=False)
    assert not manifest.should_run("hc:1m:2026-05", resume=True, retry_failed=False)
    assert manifest.should_run("hc:1m:2026-05", resume=True, retry_failed=True)
