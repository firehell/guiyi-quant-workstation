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
