from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import duckdb
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_sources import MarketDataQuery, RQDataProvider
from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.market_data_reader import MarketDataReader
from app.services.rqdata_ingest.bar_sample import check_rqdata_credential_environment, run_rqdata_bar_sample
from app.services.trader_future_importer import CHECK_RULE_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.rqdata_sample_acceptance.run_sample import (  # noqa: E402
    aggregate_jm_standard_parquet,
    aggregate_standard_bars,
    download_dominant_product_raw,
    latest_complete_year,
    standardize_jm_raw_parquet,
)

SCRIPT = PROJECT_ROOT / "experiments" / "rqdata_sample_acceptance" / "run_sample.py"
RQDATA_ENV_KEYS = {
    "RQDATAC2_CONF",
    "RQDATAC_CONF",
    "RQDATA_LICENSE_KEY",
    "RQDATA_USERNAME",
    "RQDATA_PASSWORD",
    "RQDATA_ADDR",
}


class FakeRqDataBarsClient:
    def __init__(self, *, bad_price: bool = False) -> None:
        self.bad_price = bad_price

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        assert contract == "RB2405"
        assert start_date == date(2024, 1, 2)
        assert end_date == date(2024, 1, 2)
        assert frequency == "1m"
        high = [3510.0, 3512.0, 3515.0]
        low = [3490.0, 3501.0, 3505.0]
        if self.bad_price:
            high[1] = 3499.0
        return pd.DataFrame(
            {
                "open": [3500.0, 3505.0, 3510.0],
                "high": high,
                "low": low,
                "close": [3505.0, 3510.0, 3512.0],
                "volume": [100, 120, 130],
                "total_turnover": [3505000.0, 4212000.0, 4565600.0],
                "open_interest": [1000.0, 1005.0, 1010.0],
            },
            index=pd.DatetimeIndex(
                [
                    pd.Timestamp("2024-01-02 09:01:00"),
                    pd.Timestamp("2024-01-02 09:02:00"),
                    pd.Timestamp("2024-01-02 09:03:00"),
                ]
            ),
        )


class FakeJmDominantRawClient:
    @staticmethod
    def underlying_symbol(product: str) -> str:
        return product.upper()

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        assert product == "JM"
        assert rank == 1
        assert start_date == date(2025, 1, 1)
        assert end_date == date(2025, 12, 31)
        return pd.DataFrame(
            [
                {"date": date(2025, 1, 2), "contract": "JM2505"},
                {"date": date(2025, 1, 3), "contract": "JM2505"},
                {"date": date(2025, 1, 6), "contract": "JM2509"},
            ]
        )

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        assert frequency == "1m"
        if contract == "JM2505":
            assert start_date == date(2025, 1, 2)
            assert end_date == date(2025, 1, 3)
            return pd.DataFrame(
                {
                    "open": [1200.0, 1201.0],
                    "high": [1205.0, 1206.0],
                    "low": [1198.0, 1199.0],
                    "close": [1201.0, 1203.0],
                    "volume": [100, 120],
                    "total_turnover": [1201000.0, 1443600.0],
                    "open_interest": [2000.0, 2010.0],
                },
                index=pd.DatetimeIndex([pd.Timestamp("2025-01-02 09:01:00"), pd.Timestamp("2025-01-03 09:01:00")]),
            )
        if contract == "JM2509":
            assert start_date == date(2025, 1, 6)
            assert end_date == date(2025, 1, 6)
            return pd.DataFrame(
                {
                    "open": [1210.0],
                    "high": [1215.0],
                    "low": [1208.0],
                    "close": [1212.0],
                    "volume": [130],
                    "total_turnover": [1575600.0],
                    "open_interest": [2020.0],
                },
                index=pd.DatetimeIndex([pd.Timestamp("2025-01-06 09:01:00")]),
            )
        raise AssertionError(f"unexpected contract: {contract}")


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _query(start: datetime, end: datetime) -> MarketDataQuery:
    return MarketDataQuery(
        symbol="rb",
        contract="rb2405",
        period="1m",
        start=start.replace(tzinfo=UTC),
        end=end.replace(tzinfo=UTC),
    )


def test_check_credentials_reports_clear_error_without_real_account(monkeypatch) -> None:
    for key in RQDATA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    try:
        check_rqdata_credential_environment()
    except RuntimeError as exc:
        assert "RQData credentials not configured" in str(exc)
        assert "RQDATA_PASSWORD" in str(exc)
    else:
        raise AssertionError("expected missing RQData credentials error")


def test_cli_check_credentials_without_env_writes_clear_error(tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if key not in RQDATA_ENV_KEYS}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-credentials", "--output-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "RQData credentials not configured" in result.stderr
    assert "password/addr" not in result.stderr
    payload = json.loads((tmp_path / "rqdata_credentials_check.json").read_text(encoding="utf-8"))
    assert payload["rqdata_account_required"] is True
    assert payload["live_trading_used"] is False
    assert payload["error"]["type"] == "MissingRqDataCredentials"


def test_cli_jm_one_year_raw_without_env_writes_clear_error(tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if key not in RQDATA_ENV_KEYS}
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--jm-one-year-raw",
            "--exchange",
            "DCE",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "RQData credentials not configured" in result.stderr
    payload = json.loads((tmp_path / "rqdata_jm_raw_result.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "jm-one-year-raw"
    assert payload["rqdata_account_required"] is True
    assert payload["live_trading_used"] is False
    assert payload["error"]["type"] == "MissingRqDataCredentials"


def test_latest_complete_year_uses_previous_calendar_year() -> None:
    assert latest_complete_year(date(2026, 6, 27)) == 2025


def test_fake_jm_dominant_raw_download_writes_parquet_summary(tmp_path: Path) -> None:
    result = download_dominant_product_raw(
        client=FakeJmDominantRawClient(),
        output_root=tmp_path,
        product="JM",
        exchange="DCE",
        frequency="1m",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )

    raw_path = Path(result["raw_path"])
    assert raw_path.exists()
    assert "/raw/rqdata/dominant_contract_bars/product=jm/frequency=1m/year=2025/" in raw_path.as_posix()
    assert result["row_count"] == 3
    assert result["start_datetime"] == "2025-01-02T09:01:00"
    assert result["end_datetime"] == "2025-01-06T09:01:00"
    assert {"datetime", "rqdata_product", "rqdata_order_book_id", "project_contract", "exchange", "frequency"} <= set(result["fields"])
    assert result["symbol_mapping"]["rqdata_product"] == "JM"
    assert result["symbol_mapping"]["rqdata_order_book_ids"] == ["JM2505", "JM2509"]
    assert result["symbol_mapping"]["project_contracts"] == ["jm2505", "jm2509"]
    assert result["symbol_mapping"]["project_vt_symbols"] == ["jm2505.DCE", "jm2509.DCE"]

    frame = pd.read_parquet(raw_path)
    assert len(frame) == 3
    assert sorted(frame["rqdata_order_book_id"].unique().tolist()) == ["JM2505", "JM2509"]


def test_fake_jm_raw_standardize_writes_quality_and_reader_access(tmp_path: Path) -> None:
    raw_result = download_dominant_product_raw(
        client=FakeJmDominantRawClient(),
        output_root=tmp_path,
        product="JM",
        exchange="DCE",
        frequency="1m",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = standardize_jm_raw_parquet(
            session=session,
            output_root=tmp_path,
            raw_path=Path(raw_result["raw_path"]),
            symbol="jm",
            exchange="DCE",
            interval="1m",
        )
        session.commit()

        standard_path = Path(result["standard"]["path"])
        assert standard_path.exists()
        frame = pd.read_parquet(standard_path)
        assert len(frame) == 3
        assert {
            "symbol",
            "exchange",
            "vt_symbol",
            "datetime",
            "trading_day",
            "interval",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
            "source",
            "source_symbol",
            "data_role",
            "quality_status",
        } <= set(frame.columns)
        assert frame["source"].unique().tolist() == ["rqdata"]
        assert frame["data_role"].unique().tolist() == ["primary"]
        assert frame["quality_status"].unique().tolist() == ["passed"]
        assert sorted(frame["source_symbol"].unique().tolist()) == ["jm2505", "jm2509"]
        assert result["quality"]["status"] == "passed"
        assert result["duckdb"]["row_count"] == 3
        assert result["reader"]["rows"] == 3
        assert result["local_parquet_provider"]["rows"] == 3
        assert result["formal_backtest_allowed"] is True


def _jm_standard_frame() -> pd.DataFrame:
    rows = []
    values = [
        ("2025-01-02 21:01:00", date(2025, 1, 3), 1000.0, 1003.0, 999.0, 1001.0, 10, 10010.0, 2000.0),
        ("2025-01-02 21:02:00", date(2025, 1, 3), 1001.0, 1005.0, 1000.0, 1004.0, 11, 11044.0, 2001.0),
        ("2025-01-03 09:01:00", date(2025, 1, 3), 1004.0, 1006.0, 1002.0, 1005.0, 12, 12060.0, 2002.0),
        ("2025-01-03 09:02:00", date(2025, 1, 3), 1005.0, 1007.0, 1003.0, 1006.0, 13, 13078.0, 2003.0),
        ("2025-01-03 09:03:00", date(2025, 1, 3), 1006.0, 1009.0, 1004.0, 1008.0, 14, 14112.0, 2004.0),
        ("2025-01-03 09:04:00", date(2025, 1, 3), 1008.0, 1011.0, 1007.0, 1010.0, 15, 15150.0, 2005.0),
        ("2025-01-03 09:05:00", date(2025, 1, 3), 1010.0, 1012.0, 1009.0, 1011.0, 16, 16176.0, 2006.0),
    ]
    for timestamp, trading_day, open_, high, low, close, volume, turnover, open_interest in values:
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "vt_symbol": "jm.MAIN.DCE",
                "datetime": pd.Timestamp(timestamp),
                "trading_day": trading_day,
                "interval": "1m",
                "period": "1m",
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
                "open_interest": open_interest,
                "source": "rqdata",
                "provider": "rqdata",
                "source_symbol": "jm2505",
                "data_role": "primary",
                "quality_status": "passed",
                "data_version": "test_jm_1m",
                "created_at": datetime(2026, 1, 1),
            }
        )
    return pd.DataFrame(rows)


def test_jm_standard_aggregation_uses_trading_day_and_ohlcv_rules() -> None:
    frame = _jm_standard_frame()

    bars_5m = aggregate_standard_bars(frame, "5m")
    day_bar = aggregate_standard_bars(frame, "1d").iloc[0]

    assert len(bars_5m) == 2
    night_bar = bars_5m.iloc[0]
    day_session_bar = bars_5m.iloc[1]
    assert night_bar["datetime"] == pd.Timestamp("2025-01-02 21:02:00")
    assert night_bar["trading_day"] == date(2025, 1, 3)
    assert night_bar["source_bar_count"] == 2

    assert day_session_bar["datetime"] == pd.Timestamp("2025-01-03 09:05:00")
    assert day_session_bar["open"] == 1004.0
    assert day_session_bar["high"] == 1012.0
    assert day_session_bar["low"] == 1002.0
    assert day_session_bar["close"] == 1011.0
    assert day_session_bar["volume"] == 70
    assert day_session_bar["turnover"] == 70576.0
    assert day_session_bar["open_interest"] == 2006.0
    assert day_session_bar["source_bar_count"] == 5

    assert len(aggregate_standard_bars(frame, "15m")) == 2
    assert day_bar["datetime"] == pd.Timestamp("2025-01-03 09:05:00")
    assert day_bar["trading_day"] == date(2025, 1, 3)
    assert day_bar["open"] == 1000.0
    assert day_bar["high"] == 1012.0
    assert day_bar["low"] == 999.0
    assert day_bar["close"] == 1011.0
    assert day_bar["volume"] == 91
    assert day_bar["open_interest"] == 2006.0


def test_fake_jm_standard_aggregation_writes_three_periods_and_reader_access(tmp_path: Path) -> None:
    standard_dir = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "period=1m"
    standard_dir.mkdir(parents=True)
    standard_path = standard_dir / "jm_MAIN_1m_test.parquet"
    _jm_standard_frame().to_parquet(standard_path, index=False)

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = aggregate_jm_standard_parquet(
            session=session,
            output_root=tmp_path,
            standard_path=standard_path,
            target_intervals=("5m", "15m", "1d"),
        )
        session.commit()

        assert set(result["aggregates"]) == {"5m", "15m", "1d"}
        for period, expected_rows in {"5m": 2, "15m": 2, "1d": 1}.items():
            summary = result["aggregates"][period]
            path = Path(summary["path"])
            assert path.exists()
            assert summary["row_count"] == expected_rows
            assert summary["duckdb"]["row_count"] == expected_rows
            assert summary["reader"]["rows"] == expected_rows
            assert summary["local_parquet_provider"]["rows"] == expected_rows
            assert duckdb.sql(f"select count(*) from read_parquet('{path}')").fetchone()[0] == expected_rows


def test_fake_rqdata_sample_writes_raw_standard_quality_and_is_readable(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = run_rqdata_bar_sample(
            session=session,
            client=FakeRqDataBarsClient(),
            output_root=tmp_path,
            symbol="rb",
            contract="RB2405",
            exchange="SHFE",
            frequency="1m",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
        session.commit()

        assert result.raw_path.exists()
        assert result.canonical_path.exists()
        assert "/canonical/bars/" in result.canonical_path.as_posix()
        assert result.quality.status == "passed"
        assert result.duckdb_summary["row_count"] == 3
        assert duckdb.sql(f"select count(*) from read_parquet('{result.canonical_path}')").fetchone()[0] == 3

        frame = pd.read_parquet(result.canonical_path)
        assert {
            "symbol",
            "contract",
            "exchange",
            "vt_symbol",
            "datetime",
            "trading_day",
            "interval",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
            "source",
            "provider",
            "data_role",
            "quality_status",
            "data_version",
        } <= set(frame.columns)
        assert frame["source"].unique().tolist() == ["rqdata"]
        assert frame["provider"].unique().tolist() == ["rqdata"]
        assert frame["data_role"].unique().tolist() == ["primary"]
        assert frame["quality_status"].unique().tolist() == ["passed"]
        assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
        assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()

        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 2
        quality = session.scalar(select(DataQualityReport))
        assert quality is not None
        assert quality.status == "passed"
        assert quality.details["check_rule_version"] == CHECK_RULE_VERSION
        assert quality.details["abnormal_open_interest_count"] == 0

        start = frame["datetime"].min().to_pydatetime()
        end = frame["datetime"].max().to_pydatetime()
        reader_rows = MarketDataReader(session=session, project_root=PROJECT_ROOT).load_bars(
            symbol="rb",
            contract="rb2405",
            period="1m",
            start=start.replace(tzinfo=UTC),
            end=end.replace(tzinfo=UTC),
            provider="rqdata",
        )
        provider_rows = RQDataProvider(session=session, project_root=PROJECT_ROOT).get_bars(_query(start, end))

    assert len(reader_rows) == 3
    assert len(provider_rows) == 3
    assert provider_rows[0]["data_role"] == "primary"
    assert provider_rows[0]["research_only"] is False


def test_failed_quality_sample_is_not_returned_by_default_reader(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = run_rqdata_bar_sample(
            session=session,
            client=FakeRqDataBarsClient(bad_price=True),
            output_root=tmp_path,
            symbol="rb",
            contract="RB2405",
            exchange="SHFE",
            frequency="1m",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
        session.commit()
        frame = pd.read_parquet(result.canonical_path)
        start = frame["datetime"].min().to_pydatetime()
        end = frame["datetime"].max().to_pydatetime()

        rows = RQDataProvider(session=session, project_root=PROJECT_ROOT).get_bars(_query(start, end))

    assert result.quality.status == "failed"
    assert rows == []
