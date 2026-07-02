from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_sources import DataRole, LocalParquetProvider, MarketDataQuery
from app.db.base import Base
from app.models.data_center import MarketDataFile


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_bar_file(path: Path, *, provider: str, close: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "symbol": "rb",
                "contract": "rb2405",
                "exchange": "SHFE",
                "datetime": datetime(2024, 1, 2, 9, 0),
                "trading_day": datetime(2024, 1, 2).date(),
                "open": 3500.0,
                "high": 3510.0,
                "low": 3490.0,
                "close": close,
                "volume": 1,
                "open_interest": 10,
                "turnover": 3500.0,
                "period": "1m",
                "provider": provider,
                "data_version": "test",
            }
        ]
    )
    frame.to_parquet(path, index=False)


def _market_file(path: Path, *, provider: str, quality_status: str = "passed", data_version: str = "test") -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="rb",
        contract_code="rb2405",
        period="1m",
        start_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        file_path=str(path),
        row_count=1,
        quality_status=quality_status,
        data_version=data_version,
        data_role="primary" if provider in {"rqdata", "local_parquet"} else "legacy_reference",
    )


def _query() -> MarketDataQuery:
    return MarketDataQuery(
        symbol="rb",
        contract="rb2405",
        period="1m",
        start=datetime(2024, 1, 2, 8, 59, tzinfo=UTC),
        end=datetime(2024, 1, 2, 9, 1, tzinfo=UTC),
    )


def test_local_parquet_provider_defaults_to_primary_and_excludes_legacy(tmp_path) -> None:
    SessionLocal = _session_factory()
    rqdata_path = tmp_path / "canonical" / "bars" / "rqdata.parquet"
    legacy_path = tmp_path / "canonical" / "bars" / "legacy.parquet"
    _write_bar_file(rqdata_path, provider="rqdata", close=3505.0)
    _write_bar_file(legacy_path, provider="trader_future_data", close=9999.0)

    with SessionLocal() as session:
        session.add_all(
            [
                _market_file(rqdata_path, provider="rqdata"),
                _market_file(legacy_path, provider="trader_future_data"),
            ]
        )
        session.commit()

        rows = LocalParquetProvider(session).get_bars(_query())

    assert len(rows) == 1
    assert rows[0]["provider"] == "rqdata"
    assert rows[0]["data_role"] == DataRole.PRIMARY.value
    assert rows[0]["research_only"] is False
    assert rows[0]["close"] == 3505.0


def test_failed_quality_status_is_excluded_from_default_reads(tmp_path) -> None:
    SessionLocal = _session_factory()
    passed_path = tmp_path / "canonical" / "bars" / "passed.parquet"
    failed_path = tmp_path / "canonical" / "bars" / "failed.parquet"
    _write_bar_file(passed_path, provider="rqdata", close=3505.0)
    _write_bar_file(failed_path, provider="rqdata", close=9999.0)

    with SessionLocal() as session:
        session.add_all(
            [
                _market_file(passed_path, provider="rqdata", quality_status="passed"),
                _market_file(failed_path, provider="rqdata", quality_status="failed", data_version="failed"),
            ]
        )
        session.commit()

        rows = LocalParquetProvider(session).get_bars(_query())
        contracts = LocalParquetProvider(session).get_contracts()

    assert [row["close"] for row in rows] == [3505.0]
    assert len(contracts) == 1
    assert contracts[0]["quality_status"] == "passed"


def test_inactive_legacy_reference_is_not_read_even_when_present(tmp_path) -> None:
    SessionLocal = _session_factory()
    legacy_path = tmp_path / "canonical" / "bars" / "legacy.parquet"
    _write_bar_file(legacy_path, provider="trader_future_data", close=3505.0)

    with SessionLocal() as session:
        session.add(_market_file(legacy_path, provider="trader_future_data"))
        session.commit()

        rows = LocalParquetProvider(session).get_bars(_query())

    assert rows == []
