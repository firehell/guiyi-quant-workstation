from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, LiveAggregatedBar, MarketDataFile
from app.models.signal import SignalNotification, StrategySignal
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _setup_imported_bars(tmp_path):
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2, 102.4]
    rows = []
    previous = closes[0]
    timestamp = datetime(2024, 1, 1, 9, 5)
    for index, close in enumerate(closes):
        bar_time = timestamp + timedelta(minutes=index * 5)
        rows.append({
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
            "data_version": "signal_test",
        })
        previous = close

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(path, index=False)
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="5m",
            start_time=rows[0]["datetime"],
            end_time=rows[-1]["datetime"],
            file_path=str(path),
            row_count=len(rows),
            file_size_bytes=path.stat().st_size,
            data_version="signal_test",
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
                instrument_symbol="rb",
                contract_code="rb.MAIN",
                period="5m",
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
        session.commit()
    return TestingSessionLocal


def _setup_jm_v1b_bars(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        for period, minutes, count in [("1d", 1440, 50), ("15m", 15, 80), ("5m", 5, 120)]:
            start = datetime(2024, 1, 1, 9, 0)
            rows = []
            for index in range(count):
                timestamp = start + timedelta(days=index if period == "1d" else 0, minutes=0 if period == "1d" else index * minutes)
                close = 1000 + index * 0.1
                rows.append(
                    {
                        "symbol": "jm",
                        "contract": "jm.MAIN",
                        "exchange": "DCE",
                        "datetime": timestamp,
                        "trading_day": timestamp.date(),
                        "open": close - 0.2,
                        "high": close + 0.5,
                        "low": close - 0.5,
                        "close": close,
                        "volume": 100,
                        "open_interest": 1000,
                        "turnover": close * 100,
                        "period": period,
                        "provider": "rqdata",
                        "data_version": "v1b_test",
                    }
                )
            path = tmp_path / "canonical" / "bars" / f"jm_MAIN_{period}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_parquet(path, index=False)
            market_file = MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period=period,
                start_time=rows[0]["datetime"],
                end_time=rows[-1]["datetime"],
                file_path=str(path),
                row_count=len(rows),
                file_size_bytes=path.stat().st_size,
                data_version="v1b_test",
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
        session.commit()
    return TestingSessionLocal


def test_signal_scan_inline_creates_latest_signals_and_skips_missing(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/scan",
            json={
                "watchlist_code": "black",
                "symbols": ["rb", "hc"],
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
            },
        )

        assert response.status_code == 200
        task = response.json()
        assert task["status"] in {"completed", "partial_failed"}
        assert task["total_items"] == 2
        assert task["completed_items"] == 1
        assert task["skipped_items"] == 1

        latest_response = client.get("/api/signals/latest", params={"watchlist_code": "black"})
        assert latest_response.status_code == 200
        signals = latest_response.json()
        assert len(signals) == 1
        signal = signals[0]
        assert signal["symbol"] == "rb"
        assert signal["strategy_id"] == "su_bing_ema21"
        assert signal["strategy_version_id"] == "v0"
        assert signal["interval"] == "5m"
        assert signal["period"] == "5m"
        assert signal["price"] == signal["current_price"]
        assert isinstance(signal["reason"], str)
        assert signal["status"] == "new"
        assert signal["data_role"] == "primary"
        assert signal["score_bucket"] in {0, 51, 60, 70, 80}
        assert signal["strength_score"] == signal["score_bucket"]
        assert signal["signal_type"] in {"entry_setup", "exit_setup", "watch", "trend_signal", "neutral"}
        assert signal["research_contract"] is True
        assert {"target_price", "stop_loss_price", "open_volume", "margin_required", "risk_amount"} <= set(signal)

        task_signals_response = client.get(f"/api/signals/tasks/{task['task_no']}/signals")
        assert task_signals_response.status_code == 200
        assert len(task_signals_response.json()) == 1

        ack_response = client.post(f"/api/signals/{signal['id']}/ack")
        assert ack_response.status_code == 200
        assert ack_response.json()["status"] == "viewed"
        assert ack_response.json()["alert_status"] == "acknowledged"
    finally:
        app.dependency_overrides.clear()


def test_jm_v1b_signal_scan_records_15m_5m_or_no_signal_reason(tmp_path) -> None:
    TestingSessionLocal = _setup_jm_v1b_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post("/api/signals/v1b/jm/scan", params={"run_inline": True})

        assert response.status_code == 200
        task = response.json()
        assert task["status"] == "completed"
        assert task["watchlist_code"] == "jm_v1b"
        assert task["periods"] == ["15m", "5m"]
        assert task["completed_items"] == 2

        task_signals = client.get(f"/api/signals/tasks/{task['task_no']}/signals")
        assert task_signals.status_code == 200
        signals = task_signals.json()
        assert {signal["entry_interval"] for signal in signals} == {"15m", "5m"}
        assert all(signal["symbol"] == "jm" for signal in signals)
        assert all(signal["strategy_code"] == "jm_v1b_daily_direction_fast_entry" for signal in signals)
        assert all(signal["strategy_id"] == "jm_v1b_daily_direction_fast_entry" for signal in signals)
        assert all(signal["signal_price"] == signal["price"] for signal in signals)
        assert all(signal["max_hold_bars"] == 8 for signal in signals)
        assert all(signal["open_volume"] == 0 for signal in signals)
        for signal in signals:
            assert signal["daily_direction"] in {"long", "short", "neutral", "unavailable"}
            assert signal["strategy_status"] in {"entry_signal", "no_signal"}
            if signal["strategy_status"] == "no_signal":
                assert signal["no_signal_reason"]
                assert any("no_signal" in reason for reason in signal["reasons"])

        latest = client.get("/api/signals/latest", params={"watchlist_code": "jm_v1b"})
        assert latest.status_code == 200
        assert {signal["entry_interval"] for signal in latest.json()} == {"15m", "5m"}

        with TestingSessionLocal() as session:
            rows = list(session.scalars(select(StrategySignal).where(StrategySignal.watchlist_code == "jm_v1b")))
            assert len(rows) == 2
            assert {row.period for row in rows} == {"15m", "5m"}
    finally:
        app.dependency_overrides.clear()


def test_repeated_signal_scan_does_not_duplicate_signal_or_notification(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        payload = {
            "watchlist_code": "black",
            "symbols": ["rb"],
            "periods": ["5m"],
            "run_inline": True,
            "min_score_bucket": 0,
            "strategy_params": {"ema_period": 3, "macd_fast": 2, "macd_slow": 4, "macd_signal": 2, "atr_period": 3},
        }
        assert client.post("/api/signals/scan", json=payload).status_code == 200
        assert client.post("/api/signals/scan", json=payload).status_code == 200

        with TestingSessionLocal() as session:
            assert len(list(session.scalars(select(StrategySignal)))) == 1
            assert len(list(session.scalars(select(SignalNotification)))) <= 1
    finally:
        app.dependency_overrides.clear()


def test_signal_scan_defaults_to_primary_data_role_and_rejects_auto_order(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/scan",
            json={"watchlist_code": "black", "symbols": ["rb"], "periods": ["5m"], "run_inline": True, "min_score_bucket": 0},
        )

        assert response.status_code == 200
        task = response.json()
        assert task["data_role"] == "primary"
        assert task["research_only"] is False

        blocked_response = client.post(
            "/api/signals/scan",
            json={
                "watchlist_code": "black",
                "symbols": ["rb"],
                "periods": ["5m"],
                "run_inline": True,
                "auto_order": True,
            },
        )
        assert blocked_response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_default_signal_scan_does_not_read_live_rows(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)
    with TestingSessionLocal() as session:
        session.add(
            LiveAggregatedBar(
                provider="rqdata",
                instrument_symbol="hc",
                contract_code="hc.MAIN",
                exchange_code="SHFE",
                period="5m",
                source_period="1m",
                source_mode="live_1m_sequential_bucket",
                bar_datetime=datetime(2024, 1, 1, 10, 0),
                trading_day=datetime(2024, 1, 1).date(),
                source_start_datetime=datetime(2024, 1, 1, 9, 56),
                source_end_datetime=datetime(2024, 1, 1, 10, 0),
                source_bar_count=5,
                expected_bar_count=5,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=100,
                open_interest=1000,
                turnover=10000,
                bar_status="confirmed",
                quality_status="passed",
                confirmed_at=datetime(2024, 1, 1, 10, 0),
                raw_payload={},
            )
        )
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/scan",
            json={"watchlist_code": "black", "symbols": ["rb", "hc"], "periods": ["5m"], "run_inline": True, "min_score_bucket": 0},
        )

        assert response.status_code == 200
        task = response.json()
        assert task["completed_items"] == 1
        assert task["skipped_items"] == 1
        latest = client.get("/api/signals/latest", params={"watchlist_code": "black"})
        assert latest.status_code == 200
        assert [signal["symbol"] for signal in latest.json()] == ["rb"]
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_rejects_unsupported_period_and_extra_fields(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        unsupported_period = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["30m"]},
        )
        assert unsupported_period.status_code == 422

        extra_field = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["15m"], "auto_order": True},
        )
        assert extra_field.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_signal_status_can_move_to_watching_and_ignored(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/scan",
            json={"watchlist_code": "black", "symbols": ["rb"], "periods": ["5m"], "run_inline": True, "min_score_bucket": 0},
        )
        assert response.status_code == 200
        signal = client.get("/api/signals/latest", params={"watchlist_code": "black"}).json()[0]

        watching = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "watching"})
        assert watching.status_code == 200
        assert watching.json()["status"] == "watching"

        ignored = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "ignored"})
        assert ignored.status_code == 200
        assert ignored.json()["status"] == "ignored"

        filtered = client.get("/api/signals/latest", params={"watchlist_code": "black", "status": "ignored"})
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()] == [signal["id"]]
    finally:
        app.dependency_overrides.clear()
