from datetime import datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, LiveAggregatedBar, MarketDataFile
from app.models.signal import SignalEvent, StrategySignal
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _session_factory(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        _add_rb_signal_bars(session, tmp_path)
        _add_jm_daily_bars(session, tmp_path)
        session.commit()
    return TestingSessionLocal


def test_signal_scan_writes_created_event_once_and_exposes_event_api(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        payload = _scan_payload()

        first_scan = client.post("/api/signals/scan", json=payload)
        assert first_scan.status_code == 200
        second_scan = client.post("/api/signals/scan", json=payload)
        assert second_scan.status_code == 200

        with TestingSessionLocal() as session:
            signal = session.scalar(select(StrategySignal).where(StrategySignal.symbol == "rb"))
            assert signal is not None
            events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "signal_created"
        assert event.event_key == f"signal_created:{signal.dedupe_key}"
        assert event.signal_id == signal.id
        assert event.task_no == first_scan.json()["task_no"]
        assert event.source_mode == "historical_scan"
        assert event.signal_status == signal.status
        assert event.lifecycle_status == "new"
        assert event.data_role == "primary"
        assert event.payload["signal"]["id"] == signal.id
        assert _contains_no_secret_words(event.payload)

        list_response = client.get("/api/signals/events", params={"symbol": "rb", "event_type": "signal_created"})
        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()] == [event.id]

        signal_response = client.get(f"/api/signals/{signal.id}/events")
        assert signal_response.status_code == 200
        assert [item["event_key"] for item in signal_response.json()] == [event.event_key]
    finally:
        app.dependency_overrides.clear()


def test_signal_status_changes_write_append_only_events_only_when_status_changes(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        assert client.post("/api/signals/scan", json=_scan_payload()).status_code == 200
        signal = client.get("/api/signals/latest", params={"watchlist_code": "black"}).json()[0]

        watching = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "watching"})
        assert watching.status_code == 200
        duplicate_watching = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "watching"})
        assert duplicate_watching.status_code == 200
        ignored = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "ignored"})
        assert ignored.status_code == 200

        with TestingSessionLocal() as session:
            events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))

        assert [event.event_type for event in events] == [
            "signal_created",
            "signal_status_changed",
            "signal_status_changed",
        ]
        assert events[1].source_mode == "manual_api"
        assert events[1].payload["status_change"] == {"old_status": "new", "new_status": "watching"}
        assert events[2].payload["status_change"] == {"old_status": "watching", "new_status": "ignored"}
        assert events[1].event_key != events[2].event_key
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_preview_does_not_write_signal_events(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
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

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
    finally:
        app.dependency_overrides.clear()


def _scan_payload() -> dict:
    return {
        "watchlist_code": "black",
        "symbols": ["rb"],
        "periods": ["5m"],
        "run_inline": True,
        "min_score_bucket": 0,
        "strategy_params": {
            "ema_period": 3,
            "macd_fast": 2,
            "macd_slow": 4,
            "macd_signal": 2,
            "atr_period": 3,
            "breakout_lookback": 3,
            "confirmation_bars": 2,
            "volume_ratio_intraday": 1.5,
            "zero_axis_atr_threshold": 10,
            "max_distance_from_ema_atr": 99,
            "confluence_threshold": 3,
            "volume_lookback": 3,
            "macd_cross_lookback": 5,
            "chop_cross_threshold": 99,
            "rapid_move_atr_threshold": 99,
        },
    }


def _add_rb_signal_bars(session, tmp_path: Path) -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2, 102.4]
    rows = []
    previous = closes[0]
    timestamp = datetime(2024, 1, 1, 9, 5)
    for index, close in enumerate(closes):
        bar_time = timestamp + timedelta(minutes=index * 5)
        rows.append(
            {
                "symbol": "rb",
                "contract": "rb.MAIN",
                "exchange": "SHFE",
                "datetime": bar_time,
                "trading_day": bar_time.date(),
                "open": previous,
                "close": close,
                "high": max(previous, close) + 0.2,
                "low": min(previous, close) - 0.2,
                "volume": 300 if index == 7 else 100,
                "open_interest": 1000 + index,
                "turnover": 1000,
                "period": "5m",
                "provider": "rqdata",
                "data_version": "signal_events_test",
            }
        )
        previous = close
    _write_market_file(session, tmp_path / "canonical" / "bars" / "rb_5m.parquet", rows, "rb", "rb.MAIN", "5m")


def _add_jm_daily_bars(session, tmp_path: Path) -> None:
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
    _write_market_file(session, tmp_path / "canonical" / "bars" / "jm_1d.parquet", rows, "jm", "jm.MAIN", "1d")


def _write_market_file(session, path: Path, rows: list[dict], symbol: str, contract: str, period: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period=period,
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        data_version=rows[0]["data_version"],
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
            instrument_symbol=symbol,
            contract_code=contract,
            period=period,
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


def _add_live_bars(session, period: str, *, count: int) -> None:
    start = datetime(2026, 7, 7, 9, 0)
    for index in range(count):
        timestamp = start + timedelta(minutes=(index + 1) * 15)
        close = 1000 + index
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
                trading_day=timestamp.date(),
                source_start_datetime=timestamp - timedelta(minutes=14),
                source_end_datetime=timestamp,
                source_bar_count=15,
                expected_bar_count=15,
                open=close - 1,
                high=close + 2,
                low=close - 2,
                close=close,
                volume=100 + index,
                open_interest=1000 + index,
                turnover=close * 100,
                bar_status="confirmed",
                quality_status="passed",
                confirmed_at=timestamp,
                raw_payload={},
            )
        )


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret"))
