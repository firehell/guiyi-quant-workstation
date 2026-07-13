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

    assert [row["provider"] for row in rows] == ["rqdata"]
    assert [row["close"] for row in rows] == [4010.0]


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


def test_market_data_reader_tail_returns_latest_bars_when_limit_exceeded(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_1m.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for index in range(20):
            close = 1000 + index
            rows.append(
                {
                    "symbol": "jm",
                    "contract": "JM2609",
                    "exchange": "DCE",
                    "datetime": datetime(2021, 1, 4, 9, index),
                    "trading_day": datetime(2021, 1, 4).date(),
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "volume": 100 + index,
                    "open_interest": 1000 + index,
                    "turnover": close * 100,
                    "period": "1m",
                    "provider": "rqdata",
                    "data_version": "rqdata_test",
                }
            )
        pd.DataFrame(rows).to_parquet(path, index=False)
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="1m",
                start_time=datetime(2021, 1, 4, 9, 0, tzinfo=UTC),
                end_time=datetime(2021, 1, 4, 9, 19, tzinfo=UTC),
                file_path=str(path),
                row_count=20,
                data_version="rqdata_test",
                data_role="primary",
                quality_status="passed",
            )
        )
        session.commit()

        reader = MarketDataReader(session)
        head_rows = reader.load_bars(
            symbol="jm",
            contract="JM2609",
            period="1m",
            start=datetime(2021, 1, 4, 9, 0, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 19, tzinfo=UTC),
            limit=5,
            tail=False,
        )
        tail_rows = reader.load_bars(
            symbol="jm",
            contract="JM2609",
            period="1m",
            start=datetime(2021, 1, 4, 9, 0, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 19, tzinfo=UTC),
            limit=5,
            tail=True,
        )

    assert [row["close"] for row in head_rows] == [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]
    assert [row["close"] for row in tail_rows] == [1015.0, 1016.0, 1017.0, 1018.0, 1019.0]


def test_market_data_reader_passed_only_excludes_warning_files(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        passed_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "bb_1d.parquet"
        warning_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "bb_1d_warning.parquet"
        _write_bar_file(passed_path, provider="rqdata", close_values=[4010], symbol="bb", contract="bb.MAIN", period="1d")
        _write_bar_file(warning_path, provider="rqdata", close_values=[4020], symbol="bb", contract="bb.MAIN", period="1d")
        session.add_all(
            [
                _market_file(passed_path, provider="rqdata", data_role="primary", symbol="bb", contract="bb.MAIN", period="1d"),
                _market_file(
                    warning_path,
                    provider="rqdata",
                    data_role="primary",
                    quality_status="warning",
                    symbol="bb",
                    contract="bb.MAIN",
                    period="1d",
                    data_version="rqdata_warning_test",
                ),
            ]
        )
        session.commit()

        reader = MarketDataReader(session)
        active_files = reader.get_coverage(symbol="bb", contract="bb.MAIN", period="1d")
        passed_files = reader.get_coverage(symbol="bb", contract="bb.MAIN", period="1d", passed_only=True)
        passed_rows = reader.load_bars(
            symbol="bb",
            contract="bb.MAIN",
            period="1d",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            passed_only=True,
        )

    assert len(active_files) == 2
    assert len(passed_files) == 1
    assert passed_files[0].quality_status == "passed"
    assert len(passed_rows) == 1
    assert passed_rows[0]["close"] == 4010.0


# ---------------------------------------------------------------------------
# Cross-file conflict detection tests (DATA-FINAL-002)
# ---------------------------------------------------------------------------


def _write_1d_bar_file(
    path,
    *,
    provider: str,
    close_values: list[float],
    symbol: str = "rr",
    contract: str = "RR2005",
    data_version: str | None = None,
    start_day: str = "2020-01-02",
) -> None:
    """Write a 1d Parquet file with one row per trading_day."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    base_date = datetime.strptime(start_day, "%Y-%m-%d")
    for index, close in enumerate(close_values):
        day = base_date.replace(day=base_date.day + index)
        rows.append({
            "symbol": symbol,
            "contract": contract,
            "exchange": "SHFE",
            "datetime": day,
            "trading_day": day.date(),
            "open": close - 10,
            "high": close + 10,
            "low": close - 20,
            "close": close,
            "volume": 100 + index,
            "open_interest": 1000 + index,
            "turnover": close * 100,
            "period": "1d",
            "provider": provider,
            "data_version": data_version or f"{provider}_test",
        })
    pd.DataFrame(rows).to_parquet(path, index=False)


def _engine_and_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return engine, SessionLocal


def _make_1d_market_file(path, *, provider="rqdata", data_role="primary", quality_status="passed",
                         symbol="rr", contract="RR2005", data_version=None):
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period="1d",
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2020, 1, 10, tzinfo=UTC),
        file_path=str(path),
        row_count=5,
        data_version=data_version or f"{provider}_test",
        data_role=data_role,
        quality_status=quality_status,
    )


def test_cross_file_conflicts_same_values_no_conflict(tmp_path) -> None:
    """R1: Two overlapping 1d files with identical OHLCV → no conflicts."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    _write_1d_bar_file(file1, provider="rqdata", close_values=[4010, 4020, 4030], data_version="rq_v1")
    _write_1d_bar_file(file2, provider="rqdata", close_values=[4010, 4020, 4030], data_version="rq_v2")

    with SessionLocal() as session:
        session.add_all([
            _make_1d_market_file(file1, data_version="rq_v1"),
            _make_1d_market_file(file2, data_version="rq_v2"),
        ])
        session.commit()

        conflicts = MarketDataReader(session).get_cross_file_conflicts(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )

    assert conflicts == [], f"Expected no conflicts for identical values, got {conflicts}"


def test_cross_file_conflicts_different_values_produces_conflict(tmp_path) -> None:
    """R2: Two overlapping 1d files with different close → conflicts detected."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    _write_1d_bar_file(file1, provider="rqdata", close_values=[4010, 4020, 4030], data_version="rq_v1")
    _write_1d_bar_file(file2, provider="rqdata", close_values=[4110, 4020, 4030], data_version="rq_v2")

    with SessionLocal() as session:
        session.add_all([
            _make_1d_market_file(file1, data_version="rq_v1"),
            _make_1d_market_file(file2, data_version="rq_v2"),
        ])
        session.commit()

        conflicts = MarketDataReader(session).get_cross_file_conflicts(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )

    assert len(conflicts) == 1, f"Expected 1 conflict, got {len(conflicts)}: {conflicts}"
    conflict = conflicts[0]
    assert conflict["occurrence_count"] == 2
    assert "close" in conflict["conflicting_fields"]
    assert conflict["value_ranges"]["close"] is not None
    assert conflict["file_count"] == 2


def test_cross_file_conflicts_single_file_no_conflict(tmp_path) -> None:
    """R3: Single file → no conflicts (short-circuit)."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    _write_1d_bar_file(file1, provider="rqdata", close_values=[4010, 4020, 4030])

    with SessionLocal() as session:
        session.add(_make_1d_market_file(file1))
        session.commit()

        conflicts = MarketDataReader(session).get_cross_file_conflicts(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )

    assert conflicts == []


def test_cross_file_conflicts_different_contracts_no_conflict(tmp_path) -> None:
    """R4: Same trading_day but different contract → no conflicts (filtered by where clause)."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    _write_1d_bar_file(file1, provider="rqdata", close_values=[4010], contract="RR2005", data_version="rq_v1")
    _write_1d_bar_file(file2, provider="rqdata", close_values=[4110], contract="RR2009", data_version="rq_v2")

    with SessionLocal() as session:
        session.add_all([
            _make_1d_market_file(file1, contract="RR2005", data_version="rq_v1"),
            _make_1d_market_file(file2, contract="RR2009", data_version="rq_v2"),
        ])
        session.commit()

        conflicts = MarketDataReader(session).get_cross_file_conflicts(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )

    assert conflicts == []


def test_cross_file_conflicts_1m_uses_datetime_partition(tmp_path) -> None:
    """R5: 1m period uses datetime partition, conflict detection works."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    # Same timestamps, different close values → should be a conflict
    _write_bar_file(file1, provider="rqdata", close_values=[4010, 4020, 4030], period="1m")
    _write_bar_file(file2, provider="rqdata", close_values=[4110, 4020, 4030], period="1m")

    with SessionLocal() as session:
        session.add_all([
            _market_file(file1, provider="rqdata", data_role="primary", period="1m"),
            _market_file(file2, provider="rqdata", data_role="primary", period="1m", data_version="rqdata_v2"),
        ])
        session.commit()

        conflicts = MarketDataReader(session).get_cross_file_conflicts(
            symbol="rb", contract="rb.MAIN", period="1m",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 15, tzinfo=UTC),
        )

    assert len(conflicts) == 1
    assert "close" in conflicts[0]["conflicting_fields"]


def test_cross_file_conflicts_5m_regression(tmp_path) -> None:
    """R6: 5m period multi-file → conflict detection works with datetime partition."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    _write_bar_file(file1, provider="rqdata", close_values=[4010, 4020, 4030], period="5m")
    _write_bar_file(file2, provider="rqdata", close_values=[4010, 4020, 4030], period="5m")

    with SessionLocal() as session:
        session.add_all([
            _market_file(file1, provider="rqdata", data_role="primary", period="5m"),
            _market_file(file2, provider="rqdata", data_role="primary", period="5m", data_version="rqdata_v2"),
        ])
        session.commit()

        conflicts = MarketDataReader(session).get_cross_file_conflicts(
            symbol="rb", contract="rb.MAIN", period="5m",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 15, tzinfo=UTC),
        )

    assert conflicts == [], "Same values should not produce conflicts"


def test_quality_status_includes_cross_file_conflicts(tmp_path) -> None:
    """R7: get_quality_status includes cross_file_conflicts when conflicts exist."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    _write_1d_bar_file(file1, provider="rqdata", close_values=[4010, 4020], data_version="rq_v1")
    _write_1d_bar_file(file2, provider="rqdata", close_values=[4110, 4020], data_version="rq_v2")

    with SessionLocal() as session:
        session.add_all([
            _make_1d_market_file(file1, data_version="rq_v1"),
            _make_1d_market_file(file2, data_version="rq_v2"),
        ])
        session.commit()

        status = MarketDataReader(session).get_quality_status(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )

    assert status["cross_file_conflicts"] == 1
    assert status["conflict_details"] is not None
    assert len(status["conflict_details"]) == 1
    # Status should be downgraded to warning
    assert status["status"] == "warning"
    assert any("cross_file_conflicts" in r for r in status["warning_reasons"])


def test_load_bars_returns_deduped_data_with_conflicts(tmp_path) -> None:
    """R8: load_bars still returns deduped data even when conflicts exist."""
    _, SessionLocal = _engine_and_session()

    file1 = tmp_path / "parquet" / "canonical" / "bars" / "f1.parquet"
    file2 = tmp_path / "parquet" / "canonical" / "bars" / "f2.parquet"
    _write_1d_bar_file(file1, provider="rqdata", close_values=[4010, 4020, 4030], data_version="rq_v1")
    _write_1d_bar_file(file2, provider="rqdata", close_values=[4110, 4020, 4030], data_version="rq_v2")

    with SessionLocal() as session:
        session.add_all([
            _make_1d_market_file(file1, data_version="rq_v1"),
            _make_1d_market_file(file2, data_version="rq_v2"),
        ])
        session.commit()

        reader = MarketDataReader(session)
        bars = reader.load_bars(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )
        conflicts = reader.get_cross_file_conflicts(
            symbol="rr", contract="RR2005", period="1d",
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2020, 1, 10, tzinfo=UTC),
        )

    # load_bars should return exactly 3 bars (deduped by row_number)
    assert len(bars) == 3
    # But conflicts should be detected
    assert len(conflicts) == 1
    assert "close" in conflicts[0]["conflicting_fields"]
