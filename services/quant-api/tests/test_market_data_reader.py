from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.market_data_reader import MarketDataReader
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _write_bar_file(path, *, provider: str, close_values: list[float], period: str = "5m") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, close in enumerate(close_values):
        rows.append(
            {
                "symbol": "rb",
                "contract": "rb.MAIN",
                "exchange": "SHFE",
                "datetime": datetime(2021, 1, 4, 9, 5 + index * 5),
                "trading_day": datetime(2021, 1, 4).date(),
                "open": close - 10,
                "high": close + 10,
                "low": close - 20,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": period,
                "provider": provider,
                "data_version": f"{provider}_test",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _market_file(path, *, provider: str, data_role: str, quality_status: str = "passed") -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="rb",
        contract_code="rb.MAIN",
        period="5m",
        start_time=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
        end_time=datetime(2021, 1, 4, 9, 15, tzinfo=UTC),
        file_path=str(path),
        row_count=3,
        data_version=f"{provider}_test",
        data_role=data_role,
        quality_status=quality_status,
    )


def test_market_data_reader_loads_bars_by_symbol_contract_period_and_date_range(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        _write_bar_file(path, provider="rqdata", close_values=[4010, 4020, 4030])
        session.add(_market_file(path, provider="rqdata", data_role="primary"))
        session.commit()

        reader = MarketDataReader(session)
        five_minute = reader.load_bars(
            symbol="rb",
            contract="rb.MAIN",
            period="5m",
            start=datetime(2021, 1, 4, 9, 10, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 15, tzinfo=UTC),
        )

        assert [row["datetime"].strftime("%H:%M:%S") for row in five_minute] == ["09:10:00", "09:15:00"]
        assert all(row["symbol"] == "rb" and row["contract"] == "rb.MAIN" for row in five_minute)


def test_market_data_reader_default_reads_only_primary_rqdata_or_local_parquet(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        rqdata_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        tqsdk_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=tqsdk" / "rb_5m.parquet"
        trader_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=trader_future_data" / "rb_5m.parquet"
        _write_bar_file(rqdata_path, provider="rqdata", close_values=[4010])
        _write_bar_file(tqsdk_path, provider="tqsdk", close_values=[9010])
        _write_bar_file(trader_path, provider="trader_future_data", close_values=[8010])
        session.add_all(
            [
                _market_file(rqdata_path, provider="rqdata", data_role="primary"),
                _market_file(tqsdk_path, provider="tqsdk", data_role="validation", quality_status="warning"),
                _market_file(trader_path, provider="trader_future_data", data_role="legacy_reference"),
            ]
        )
        session.commit()

        rows = MarketDataReader(session).load_bars(
            symbol="rb",
            contract="rb.MAIN",
            period="5m",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
        )

    assert [row["provider"] for row in rows] == ["rqdata"]
    assert [row["close"] for row in rows] == [4010.0]


def test_market_data_reader_quality_status_aggregates_rqdata_reports(tmp_path) -> None:
    path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
    _write_bar_file(path, provider="rqdata", close_values=[4010, 4020])

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        market_file = _market_file(path, provider="rqdata", data_role="primary", quality_status="warning")
        session.add(market_file)
        session.flush()
        session.add(
            DataQualityReport(
                file_id=market_file.id,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="rb",
                contract_code="rb.MAIN",
                period="5m",
                start_time=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
                end_time=datetime(2021, 1, 4, 9, 10, tzinfo=UTC),
                status="warning",
                missing_bars=2,
                duplicated_bars=0,
                abnormal_price_count=0,
                abnormal_volume_count=0,
                details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
            )
        )
        session.commit()

        report = session.scalar(select(DataQualityReport))
        assert report is not None
        assert report.status == "warning"

        status = MarketDataReader(session).get_quality_status(
            symbol="rb",
            contract="rb.MAIN",
            period="5m",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 20, tzinfo=UTC),
        )
        assert status["status"] == "warning"
        assert status["missing_bars"] == 2
