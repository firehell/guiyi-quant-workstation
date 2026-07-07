from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.market_data_reader import MarketDataReader
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _write_bar_file(
    path,
    *,
    provider: str,
    close_values: list[float],
    period: str = "5m",
    symbol: str = "rb",
    contract: str = "rb.MAIN",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, close in enumerate(close_values):
        rows.append(
            {
                "symbol": symbol,
                "contract": contract,
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


def _market_file(
    path,
    *,
    provider: str,
    data_role: str,
    quality_status: str = "passed",
    symbol: str = "rb",
    contract: str = "rb.MAIN",
    period: str = "5m",
    data_version: str | None = None,
) -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period=period,
        start_time=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
        end_time=datetime(2021, 1, 4, 9, 15, tzinfo=UTC),
        file_path=str(path),
        row_count=3,
        data_version=data_version or f"{provider}_test",
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


def test_market_data_reader_default_reads_only_active_primary_sources(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        rqdata_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        local_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=local_parquet" / "rb_5m.parquet"
        candidate_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_candidate_5m.parquet"
        failed_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=local_parquet" / "rb_failed_5m.parquet"
        tqsdk_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=tqsdk" / "rb_5m.parquet"
        trader_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=trader_future_data" / "rb_5m.parquet"
        _write_bar_file(rqdata_path, provider="rqdata", close_values=[4010])
        _write_bar_file(local_path, provider="local_parquet", close_values=[4020])
        _write_bar_file(candidate_path, provider="rqdata", close_values=[7010])
        _write_bar_file(failed_path, provider="local_parquet", close_values=[7020])
        _write_bar_file(tqsdk_path, provider="tqsdk", close_values=[9010])
        _write_bar_file(trader_path, provider="trader_future_data", close_values=[8010])
        session.add_all(
            [
                _market_file(rqdata_path, provider="rqdata", data_role="primary"),
                _market_file(local_path, provider="local_parquet", data_role="primary", quality_status="warning"),
                _market_file(candidate_path, provider="rqdata", data_role="candidate", data_version="rqdata_candidate_test"),
                _market_file(failed_path, provider="local_parquet", data_role="primary", quality_status="failed", data_version="local_parquet_failed_test"),
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

    assert [row["provider"] for row in rows] == ["rqdata", "local_parquet"]
    assert [row["close"] for row in rows] == [4010.0, 4020.0]


def test_market_data_reader_coverage_hides_non_active_roles_and_failed_files(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        active_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_5m.parquet"
        local_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=local_parquet" / "jm_5m.parquet"
        candidate_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_candidate_5m.parquet"
        failed_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_failed_5m.parquet"
        validation_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=tqsdk" / "jm_5m.parquet"
        _write_bar_file(active_path, provider="rqdata", close_values=[1005], symbol="jm", contract="jm.MAIN")
        _write_bar_file(local_path, provider="local_parquet", close_values=[1015], symbol="jm", contract="jm.MAIN")
        _write_bar_file(candidate_path, provider="rqdata", close_values=[8005], symbol="jm", contract="jm.MAIN")
        _write_bar_file(failed_path, provider="rqdata", close_values=[9005], symbol="jm", contract="jm.MAIN")
        _write_bar_file(validation_path, provider="tqsdk", close_values=[7005], symbol="jm", contract="jm.MAIN")
        session.add_all(
            [
                _market_file(active_path, provider="rqdata", data_role="primary", symbol="jm", contract="jm.MAIN"),
                _market_file(local_path, provider="local_parquet", data_role="primary", quality_status="warning", symbol="jm", contract="jm.MAIN"),
                _market_file(candidate_path, provider="rqdata", data_role="candidate", symbol="jm", contract="jm.MAIN", data_version="rqdata_candidate_test"),
                _market_file(failed_path, provider="rqdata", data_role="primary", quality_status="failed", symbol="jm", contract="jm.MAIN", data_version="rqdata_failed_test"),
                _market_file(validation_path, provider="tqsdk", data_role="validation", quality_status="warning", symbol="jm", contract="jm.MAIN"),
            ]
        )
        session.commit()

        files = MarketDataReader(session).get_coverage(symbol="jm", contract="jm.MAIN", period="5m")

    assert [(item.provider, item.data_role, item.quality_status) for item in files] == [
        ("rqdata", "primary", "passed"),
        ("local_parquet", "primary", "warning"),
    ]


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
