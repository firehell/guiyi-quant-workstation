from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, LiveAggregatedBar, MarketDataFile
from app.models.signal import SignalNotification, SignalScanTask, StrategySignal
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _session_factory(tmp_path: Path, *, with_daily: bool = True):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        if with_daily:
            _add_daily_bars(session, tmp_path)
        session.commit()
    return TestingSessionLocal


def test_live_signal_evaluator_preview_reads_live_bars_without_writing_signal_tables(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=50)
        _add_live_bars(session, "5m", count=50, minutes=5)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={
                "symbol": "jm",
                "contract": "JM2609",
                "entry_intervals": ["15m", "5m"],
                "provider": "rqdata",
                "source_mode": "live_1m_sequential_bucket",
                "limit": 100,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["strategy_code"] == "jm_v1b_daily_direction_fast_entry"
        assert payload["strategy_version"] == "v1b.0"
        assert payload["quality_summary"]["preview_only"] is True
        assert payload["quality_summary"]["writes_strategy_signal"] is False
        assert {item["entry_interval"] for item in payload["results"]} == {"15m", "5m"}
        assert all(item["source"]["entry_data_source"] == "live_db" for item in payload["results"])
        assert all(item["source"]["daily_data_source"] == "active_standard_parquet" for item in payload["results"])
        assert all(item["source"]["auto_order"] is False for item in payload["results"])
        assert all(item["bar_time"] for item in payload["results"])

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
            assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
            assert session.scalar(select(func.count()).select_from(SignalScanTask)) == 0
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_blocks_warning_partial_bucket_by_default(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=50, warning_index=49)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["15m"], "limit": 100},
        )

        assert response.status_code == 200
        item = response.json()["results"][0]
        assert item["status"] == "no_signal"
        assert item["direction"] == "neutral"
        assert item["no_signal_reason"] == "live_data_quality_warning_blocked"
        assert "live_quality_warning" in item["warnings"]
        assert "live_partial_bucket" in item["warnings"]
        assert "incomplete_source_bucket" in item["warnings"]
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_reports_insufficient_live_bars(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "5m", count=3, minutes=5)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["5m"], "limit": 100},
        )

        assert response.status_code == 200
        item = response.json()["results"][0]
        assert item["status"] == "no_signal"
        assert item["no_signal_reason"] == "entry_bars_insufficient"
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_reports_missing_historical_daily_data(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path, with_daily=False)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=50)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["15m"], "limit": 100},
        )

        assert response.status_code == 200
        item = response.json()["results"][0]
        assert item["status"] == "no_signal"
        assert item["no_signal_reason"] == "daily_data_missing"
        assert item["quality"]["daily"]["status"] == "missing"
    finally:
        app.dependency_overrides.clear()


def _add_daily_bars(session: Session, tmp_path: Path) -> None:
    rows = []
    start = datetime(2026, 4, 1)
    for index in range(70):
        timestamp = start + timedelta(days=index)
        close = 1000 + index * 2
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": close - 1,
                "high": close + 4,
                "low": close - 4,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000,
                "turnover": close * 100,
                "period": "1d",
                "provider": "rqdata",
                "data_version": "daily_test",
            }
        )
    path = tmp_path / "canonical" / "bars" / "jm_MAIN_1d.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="1d",
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        data_version="daily_test",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            start_time=rows[0]["datetime"],
            end_time=rows[-1]["datetime"],
            status="passed",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
        )
    )


def _add_live_bars(
    session: Session,
    period: str,
    *,
    count: int,
    minutes: int = 15,
    warning_index: int | None = None,
) -> None:
    start = datetime(2026, 7, 7, 9, 0)
    for index in range(count):
        timestamp = start + timedelta(minutes=(index + 1) * minutes)
        price = Decimal(1000 + index)
        warning = warning_index == index
        session.add(
            LiveAggregatedBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period=period,
                source_period="1m",
                source_mode="live_1m_sequential_bucket",
                bar_datetime=timestamp,
                trading_day=date(2026, 7, 7),
                source_start_datetime=timestamp - timedelta(minutes=minutes - 1),
                source_end_datetime=timestamp,
                source_bar_count=minutes - 1 if warning else minutes,
                expected_bar_count=minutes,
                open=price - Decimal("1"),
                high=price + Decimal("3"),
                low=price - Decimal("3"),
                close=price,
                volume=Decimal("100"),
                open_interest=Decimal("1000"),
                turnover=Decimal("10000"),
                bar_status="confirmed",
                quality_status="warning" if warning else "passed",
                first_seen_at=timestamp + timedelta(seconds=2),
                last_seen_at=timestamp + timedelta(seconds=3),
                confirmed_at=timestamp + timedelta(seconds=3),
                revision=0,
                raw_payload={"quality_reasons": ["incomplete_source_bucket"]} if warning else {},
            )
        )
