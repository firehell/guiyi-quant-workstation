from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MainContractMap, MarketDataFile
from app.services.tqsdk_ingest.aggregate import aggregate_bars
from app.services.tqsdk_ingest.contract_plan import build_contract_download_plan, czce_to_tqsdk_symbol, tqsdk_download_symbol
from app.services.tqsdk_ingest.db import TqSdkIngestRecorder
from app.services.tqsdk_ingest.downloader import download_1m_csv, download_main_1m_csv
from app.services.tqsdk_ingest.manifest import TqSdkCsvManifest
from app.services.tqsdk_ingest.products import DEFAULT_CORE_PRODUCTS, product_spec
from app.services.tqsdk_ingest.quality import evaluate_1m_quality
from app.services.tqsdk_ingest.transformer import (
    build_month_chunks,
    canonical_path,
    raw_path,
    transform_downloader_csv,
)


def _write_downloader_csv(path: Path, source_symbol: str = "KQ.m@SHFE.rb") -> None:
    path.write_text(
        "\n".join(
            [
                f"datetime,datetime_nano,{source_symbol}.open,{source_symbol}.high,{source_symbol}.low,{source_symbol}.close,{source_symbol}.volume,{source_symbol}.open_oi,{source_symbol}.close_oi",
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


def test_core_products_aliases_and_month_chunks_are_plan_aligned() -> None:
    assert DEFAULT_CORE_PRODUCTS == ["rb", "hc", "i", "j", "jm", "TA", "MA", "pp", "v", "eg", "SA", "fu", "bu", "sc", "cu", "al", "m", "y", "p"]
    assert product_spec("rb").download_symbol == "KQ.m@SHFE.rb"
    assert product_spec("TA").download_symbol == "KQ.m@CZCE.TA"
    assert product_spec("PP").product == "pp"
    assert product_spec("L").product == "l"
    assert product_spec("V").product == "v"
    assert product_spec("EG").download_symbol == "KQ.m@DCE.eg"
    assert product_spec("FG").download_symbol == "KQ.m@CZCE.FG"
    assert product_spec("pg").download_symbol == "KQ.m@DCE.pg"

    chunks = build_month_chunks(date(2026, 5, 20), date(2026, 7, 3))

    assert [(chunk.start, chunk.end, chunk.key_suffix) for chunk in chunks] == [
        (date(2026, 5, 20), date(2026, 5, 31), "2026-05"),
        (date(2026, 6, 1), date(2026, 6, 30), "2026-06"),
        (date(2026, 7, 1), date(2026, 7, 3), "2026-07"),
    ]


def test_transformer_writes_main_and_contract_fields_and_paths(tmp_path) -> None:
    csv_path = tmp_path / "rb_2026_05.csv"
    _write_downloader_csv(csv_path)
    spec = product_spec("rb")

    raw_frame, canonical_frame = transform_downloader_csv(csv_path, spec=spec, year=2026, month=5, data_type="main_continuous")

    assert raw_frame["download_symbol"].unique().tolist() == ["KQ.m@SHFE.rb"]
    assert canonical_frame[["symbol", "contract", "exchange", "period", "provider", "data_type"]].iloc[0].to_dict() == {
        "symbol": "rb",
        "contract": "rb.MAIN",
        "exchange": "SHFE",
        "period": "1m",
        "provider": "tqsdk",
        "data_type": "main_continuous",
    }
    assert canonical_frame["source_symbol"].unique().tolist() == ["KQ.m@SHFE.rb"]
    assert canonical_frame["source_contract"].unique().tolist() == ["KQ.m@SHFE.rb"]
    assert canonical_frame["is_main_continuous"].unique().tolist() == [True]
    assert canonical_frame["data_version"].unique().tolist() == ["tq_1m_v1"]
    assert raw_path(tmp_path, spec, 2026, 5, data_type="main_continuous").as_posix().endswith(
        "raw/tqsdk/main_continuous_1m/exchange=SHFE/product=rb/year=2026/month=05/KQ.m@SHFE.rb_2026_05.parquet"
    )
    assert canonical_path(tmp_path, spec, 2026, 5, data_type="main_continuous").as_posix().endswith(
        "parquet/canonical/bars/provider=tqsdk/data_type=main_continuous/period=1m/exchange=SHFE/symbol=rb/contract=rb.MAIN/year=2026/month=05/part-000.parquet"
    )

    contract_csv = tmp_path / "SHFE.rb2410_2026_05.csv"
    _write_downloader_csv(contract_csv, source_symbol="SHFE.rb2410")
    _, contract_frame = transform_downloader_csv(
        contract_csv,
        spec=spec,
        year=2026,
        month=5,
        data_type="contract",
        source_symbol="SHFE.rb2410",
        contract_code="SHFE.rb2410",
    )
    assert contract_frame[["symbol", "contract", "data_type", "source_symbol", "is_main_continuous"]].iloc[0].to_dict() == {
        "symbol": "rb",
        "contract": "SHFE.rb2410",
        "data_type": "contract",
        "source_symbol": "SHFE.rb2410",
        "is_main_continuous": False,
    }
    assert canonical_path(tmp_path, spec, 2026, 5, data_type="contract", contract_code="SHFE.rb2410").as_posix().endswith(
        "parquet/canonical/bars/provider=tqsdk/data_type=contract/period=1m/exchange=SHFE/symbol=rb/contract=SHFE.rb2410/year=2026/month=05/part-000.parquet"
    )


def test_downloader_uses_data_downloader_for_main_and_contract_1m_csv(tmp_path) -> None:
    calls = []

    class FakeApi:
        def __init__(self) -> None:
            self.wait_count = 0

        def wait_update(self) -> None:
            self.wait_count += 1

    class FakeDownloader:
        def __init__(self, api, symbol_list, dur_sec, start_dt, end_dt, csv_file_name):
            calls.append((api, symbol_list, dur_sec, start_dt, end_dt, csv_file_name))
            self.finished = False

        def is_finished(self) -> bool:
            if not self.finished:
                self.finished = True
                return False
            return True

    api = FakeApi()
    main_path = tmp_path / "downloads/rb.csv"
    contract_path = tmp_path / "downloads/rb2410.csv"

    assert download_main_1m_csv(api=api, spec=product_spec("rb"), start=date(2026, 5, 1), end=date(2026, 5, 31), output_path=main_path, downloader_cls=FakeDownloader) == main_path
    assert download_1m_csv(api=api, source_symbol="SHFE.rb2410", start=date(2026, 5, 1), end=date(2026, 5, 31), output_path=contract_path, downloader_cls=FakeDownloader) == contract_path
    assert calls[0][1] == "KQ.m@SHFE.rb"
    assert calls[1][1] == "SHFE.rb2410"
    assert calls[0][2] == calls[1][2] == 60
    assert api.wait_count == 2


def test_tqsdk_manifest_enforces_resume_retry_force_and_checksum(tmp_path) -> None:
    data_file = tmp_path / "part.parquet"
    data_file.write_text("v1", encoding="utf-8")
    manifest = TqSdkCsvManifest(tmp_path / "manifest.csv")
    manifest.mark(
        key="rb:main_continuous:1m:2026-05",
        provider="tqsdk",
        data_type="main_continuous",
        product="rb",
        exchange="SHFE",
        source_symbol="KQ.m@SHFE.rb",
        period="1m",
        chunk_start=date(2026, 5, 1),
        chunk_end=date(2026, 5, 31),
        raw_path=data_file,
        canonical_path=data_file,
        rows=1,
        checksum=manifest.file_checksum(data_file),
        status="success",
    )

    assert not manifest.should_run("rb:main_continuous:1m:2026-05", resume=True, retry_failed=False, force=False)
    data_file.write_text("changed", encoding="utf-8")
    assert not manifest.should_run("rb:main_continuous:1m:2026-05", resume=True, retry_failed=False, force=False)
    row = manifest.load().iloc[0]
    assert row["status"] == "failed"
    assert "checksum mismatch" in row["error"]
    assert manifest.should_run("rb:main_continuous:1m:2026-05", resume=True, retry_failed=False, force=True)

    manifest.mark(
        key="hc:main_continuous:1m:2026-05",
        provider="tqsdk",
        data_type="main_continuous",
        product="hc",
        exchange="SHFE",
        source_symbol="KQ.m@SHFE.hc",
        period="1m",
        chunk_start=date(2026, 5, 1),
        chunk_end=date(2026, 5, 31),
        status="empty",
        error="no rows",
    )
    assert not manifest.should_run("hc:main_continuous:1m:2026-05", resume=True, retry_failed=True, force=False)
    assert manifest.should_run("hc:main_continuous:1m:2026-05", resume=True, retry_failed=False, force=True)


def test_contract_plan_from_main_contract_map_has_buffer_and_full_symbol() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add_all(
            [
                MainContractMap(instrument_symbol="rb", trade_date=date(2026, 5, 10), rank=1, contract_code="RB2410", rule="volume_open_interest", provider="rqdata", data_version="test"),
                MainContractMap(instrument_symbol="rb", trade_date=date(2026, 5, 12), rank=1, contract_code="RB2410", rule="volume_open_interest", provider="rqdata", data_version="test"),
                MainContractMap(instrument_symbol="rb", trade_date=date(2026, 5, 11), rank=2, contract_code="RB2411", rule="volume_open_interest", provider="rqdata", data_version="test"),
            ]
        )
        session.commit()
        plan = build_contract_download_plan(session, products=["rb"], start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), ranks=[1], buffer_days=10)

    assert plan.to_dict("records") == [
        {
            "contract_code": "SHFE.rb2410",
            "exchange": "SHFE",
            "product": "rb",
            "first_trading_day_in_mapping": "2026-05-10",
            "last_trading_day_in_mapping": "2026-05-12",
            "download_start": "2026-04-30",
            "download_end": "2026-05-22",
            "rank": 1,
            "source_mapping_rule": "volume_open_interest",
            "source_symbol": "SHFE.rb2410",
            "status": "pending",
        }
    ]


def test_czce_tqsdk_download_symbol_uses_three_digit_year() -> None:
    assert czce_to_tqsdk_symbol("CZCE.MA2105", "MA") == "CZCE.MA105"
    assert czce_to_tqsdk_symbol("CZCE.TA2512", "TA") == "CZCE.TA512"
    assert tqsdk_download_symbol("SHFE.rb2410", "SHFE", "rb") == "SHFE.rb2410"
    assert tqsdk_download_symbol("CZCE.MA2105", "CZCE", "MA") == "CZCE.MA105"


def test_contract_plan_czce_keeps_canonical_and_tqsdk_source_symbol() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add(
            MainContractMap(
                instrument_symbol="MA",
                trade_date=date(2021, 3, 1),
                rank=1,
                contract_code="MA2105",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="test",
            )
        )
        session.commit()
        plan = build_contract_download_plan(
            session,
            products=["MA"],
            start_date=date(2021, 3, 1),
            end_date=date(2021, 3, 31),
            ranks=[1],
            buffer_days=10,
        )

    row = plan.iloc[0].to_dict()
    assert row["contract_code"] == "CZCE.MA2105"
    assert row["source_symbol"] == "CZCE.MA105"


def test_aggregate_bars_does_not_cross_session_and_warns_without_sessions() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-05-06 09:01", "2026-05-06 09:02", "2026-05-06 10:31", "2026-05-06 10:32"]),
            "trading_day": [date(2026, 5, 6)] * 4,
            "session_id": ["am1", "am1", "am2", "am2"],
            "open": [1.0, 2.0, 10.0, 11.0],
            "high": [2.0, 3.0, 12.0, 13.0],
            "low": [0.5, 1.5, 9.0, 10.0],
            "close": [1.5, 2.5, 11.0, 12.0],
            "volume": [10, 20, 30, 40],
            "turnover": [100.0, 200.0, 300.0, 400.0],
            "open_interest": [100.0, 101.0, 200.0, 201.0],
        }
    )

    result, warnings = aggregate_bars(frame, "5m")

    assert warnings == []
    assert result[["session_id", "open", "close", "volume", "open_interest"]].to_dict("records") == [
        {"session_id": "am1", "open": 1.0, "close": 2.5, "volume": 30, "open_interest": 101.0},
        {"session_id": "am2", "open": 10.0, "close": 12.0, "volume": 70, "open_interest": 201.0},
    ]
    _, no_session_warnings = aggregate_bars(frame.drop(columns=["session_id"]), "5m")
    assert no_session_warnings == ["missing session_id; used trading_day-only grouping"]


def test_quality_detects_duplicates_gaps_and_abnormal_rows() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-05-06 09:01:00", "2026-05-06 09:01:00", "2026-05-06 09:04:00"]),
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
    raw_frame, canonical_frame = transform_downloader_csv(csv_path, spec=spec, year=2026, month=5, data_type="main_continuous")
    raw_file = raw_path(tmp_path / "data", spec, 2026, 5, data_type="main_continuous")
    canonical_file = canonical_path(tmp_path / "data", spec, 2026, 5, data_type="main_continuous")

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        recorder = TqSdkIngestRecorder(session=session, project_root=tmp_path)
        task = recorder.start_task(spec=spec, chunk_start=date(2026, 5, 1), chunk_end=date(2026, 5, 31), data_type="main_continuous")
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
            data_type="main_continuous",
        )
        recorder.finish_task(task, status="success", row_count=len(canonical_frame))
        session.commit()

        task = recorder.start_task(spec=spec, chunk_start=date(2026, 5, 1), chunk_end=date(2026, 5, 31), data_type="main_continuous")
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
            data_type="main_continuous",
        )
        recorder.finish_task(task, status="success", row_count=len(canonical_frame))
        session.commit()

        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 2
        assert session.scalar(select(func.count()).select_from(DataQualityReport)) == 1
        canonical = session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "main_continuous"))
        assert canonical is not None
        assert canonical.provider == "tqsdk"
        assert canonical.period == "1m"
        assert canonical.contract_code == "rb.MAIN"
        assert canonical.quality_status == "passed"
        assert duckdb.sql(f"select count(*) from read_parquet('{canonical.file_path}')").fetchone()[0] == 2
