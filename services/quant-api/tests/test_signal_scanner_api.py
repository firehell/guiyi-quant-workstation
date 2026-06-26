from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import MarketDataFile
from app.models.signal import SignalNotification, StrategySignal
from app.services.trader_future_importer import TraderFutureCsvImporter


def _setup_imported_bars(tmp_path):
    raw_dir = tmp_path / "trader_Future_data" / "5分钟主力连续"
    raw_dir.mkdir(parents=True)
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2, 102.4]
    rows = ["Date,Time,Open,Close,High,Low,Volume,Amount"]
    previous = closes[0]
    timestamp = datetime(2024, 1, 1, 9, 5)
    for index, close in enumerate(closes):
        bar_time = timestamp + timedelta(minutes=index * 5)
        rows.append(
            f"{bar_time.date().isoformat()},{bar_time.time().isoformat()},{previous},{close},{max(previous, close) + 0.2},{min(previous, close) - 0.2},{300 if index == 7 else 100},1000"
        )
        previous = close
    (raw_dir / "螺纹-主连-5分钟.csv").write_text("\n".join(rows), encoding="utf-8")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        importer = TraderFutureCsvImporter(session=session, raw_root=tmp_path / "trader_Future_data", parquet_root=tmp_path / "parquet")
        importer.import_files(instrument_names=["螺纹"], periods=["5m"])
        for market_file in session.scalars(select(MarketDataFile)):
            market_file.data_role = "primary"
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
