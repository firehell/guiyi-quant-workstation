from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport
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
        session.commit()
    return TestingSessionLocal


def test_run_backtest_api_returns_report(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/backtests/run",
            json={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "5m",
                "start": "2024-01-01",
                "end": "2024-01-01",
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
        payload = response.json()
        assert {"summary", "trades", "equity_curve", "drawdown_curve", "orders", "fills"} <= set(payload)
        assert payload["summary"]["initial_capital"] == 100000.0
        assert len(payload["equity_curve"]) > 0
        assert any("research_contract=true" in warning for warning in payload["warnings"])
    finally:
        app.dependency_overrides.clear()


def test_run_backtest_api_rejects_failed_quality(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)
    with TestingSessionLocal() as session:
        report = session.scalar(select(DataQualityReport))
        assert report is not None
        report.status = "failed"
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/backtests/run",
            json={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "5m",
                "start": "2024-01-01",
                "end": "2024-01-01",
            },
        )

        assert response.status_code == 422
        assert "quality failed" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_run_batch_backtest_inline_creates_reports_and_skips_missing_symbol(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/backtests/run-batch",
            json={
                "watchlist_code": "black",
                "symbols": ["rb", "hc"],
                "period": "5m",
                "start": "2024-01-01",
                "end": "2024-01-01",
                "run_inline": True,
                "parameter_templates": [
                    {
                        "name": "default",
                        "label": "默认",
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
                ],
            },
        )

        assert response.status_code == 200
        task = response.json()
        assert task["status"] in {"completed", "partial_failed"}
        assert task["total_items"] == 2
        assert task["completed_items"] == 1
        assert task["skipped_items"] == 1

        reports_response = client.get(f"/api/backtests/tasks/{task['task_no']}/reports")
        assert reports_response.status_code == 200
        reports = reports_response.json()
        assert len(reports) == 2
        assert {report["symbol"] for report in reports} == {"rb", "hc"}
        rb_report = next(report for report in reports if report["symbol"] == "rb")
        assert rb_report["status"] == "completed"
        assert rb_report["suitability_label"] in {"适合", "观察", "不适合", "数据不足"}

        detail_response = client.get(f"/api/backtests/reports/{rb_report['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert {"summary", "trades", "orders", "fills", "equity_curve", "drawdown_curve"} <= set(detail)
    finally:
        app.dependency_overrides.clear()


def test_watchlist_api_returns_default_pools(tmp_path) -> None:
    TestingSessionLocal = _setup_imported_bars(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/watchlists")
        assert response.status_code == 200
        pools = response.json()
        assert {"black", "chemical", "energy"} <= {pool["code"] for pool in pools}

        items_response = client.get("/api/watchlists/black/items")
        assert items_response.status_code == 200
        assert any(item["symbol"] == "rb" and "5m" in item["available_periods"] for item in items_response.json())
    finally:
        app.dependency_overrides.clear()
