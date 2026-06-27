from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_sources import DataRole, LocalParquetProvider, MarketDataQuery
from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.services.market_data_reader import MarketDataReader


REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = REPO_ROOT / "experiments" / "vnpy_rqdata_demo" / "generate_standard_fixture.py"

GENERATOR_SPEC = importlib.util.spec_from_file_location("generate_standard_fixture", GENERATOR_PATH)
assert GENERATOR_SPEC is not None
assert GENERATOR_SPEC.loader is not None
fixture_generator = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(fixture_generator)

FIXTURE_PATH: Path = fixture_generator.DEFAULT_FIXTURE_PATH
DATA_VERSION: str = fixture_generator.DATA_VERSION

REQUIRED_FIELDS = {
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
}


def _ensure_fixture() -> Path:
    return fixture_generator.write_fixture(FIXTURE_PATH)


def _read_fixture() -> Any:
    path = _ensure_fixture()
    return duckdb.sql(f"select * from read_parquet('{path}') order by datetime").df()


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _market_file(path: Path) -> MarketDataFile:
    frame = duckdb.sql(f"select min(datetime) as start_time, max(datetime) as end_time, count(*) as rows from read_parquet('{path}')").df()
    return MarketDataFile(
        provider="local_parquet",
        data_type="bars",
        instrument_symbol="rb",
        contract_code="rb2405",
        period="60m",
        start_time=frame["start_time"].iloc[0].to_pydatetime().replace(tzinfo=UTC),
        end_time=frame["end_time"].iloc[0].to_pydatetime().replace(tzinfo=UTC),
        file_path=str(path),
        row_count=int(frame["rows"].iloc[0]),
        quality_status="passed",
        data_version=DATA_VERSION,
        data_role=DataRole.PRIMARY.value,
    )


def _query() -> MarketDataQuery:
    return MarketDataQuery(
        symbol="rb",
        contract="rb2405",
        period="60m",
        start=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        end=datetime(2024, 1, 6, 8, 0, tzinfo=UTC),
    )


def test_standard_parquet_fixture_is_duckdb_readable_and_schema_complete() -> None:
    frame = _read_fixture()

    assert len(frame) == 96
    assert REQUIRED_FIELDS <= set(frame.columns)
    assert frame["datetime"].is_monotonic_increasing
    assert frame["datetime"].is_unique
    assert frame["symbol"].unique().tolist() == ["rb"]
    assert frame["contract"].unique().tolist() == ["rb2405"]
    assert frame["exchange"].unique().tolist() == ["SHFE"]
    assert frame["vt_symbol"].unique().tolist() == ["rb2405.SHFE"]
    assert frame["interval"].unique().tolist() == ["60m"]
    assert frame["period"].unique().tolist() == ["60m"]
    assert frame["source"].unique().tolist() == ["sample"]
    assert frame["provider"].unique().tolist() == ["local_parquet"]
    assert frame["data_role"].unique().tolist() == [DataRole.PRIMARY.value]
    assert frame["quality_status"].unique().tolist() == ["passed"]
    assert frame["data_version"].unique().tolist() == [DATA_VERSION]


def test_standard_parquet_fixture_ohlc_and_volume_are_valid() -> None:
    frame = _read_fixture()

    assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
    assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
    assert (frame["high"] >= frame["low"]).all()
    assert (frame["volume"] >= 0).all()
    assert (frame["turnover"] >= 0).all()
    assert (frame["open_interest"] >= 0).all()


def test_standard_parquet_fixture_is_readable_by_market_data_reader_and_primary_provider() -> None:
    path = _ensure_fixture()
    SessionLocal = _session_factory()

    with SessionLocal() as session:
        session.add(_market_file(path))
        session.commit()

        reader_rows = MarketDataReader(session=session, project_root=REPO_ROOT).load_bars(
            symbol="rb",
            contract="rb2405",
            period="60m",
            start=_query().start,
            end=_query().end,
            provider="local_parquet",
        )
        provider_rows = LocalParquetProvider(session=session, project_root=REPO_ROOT).get_bars(_query())

    assert len(reader_rows) == 96
    assert len(provider_rows) == 96
    assert provider_rows[0]["data_role"] == DataRole.PRIMARY.value
    assert provider_rows[0]["research_only"] is False
    assert provider_rows[0]["provider"] == "local_parquet"
    assert provider_rows[0]["data_version"] == DATA_VERSION
