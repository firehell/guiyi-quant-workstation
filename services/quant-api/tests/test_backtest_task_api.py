from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import (
    BacktestDrawdownCurvePointModel,
    BacktestEquityCurvePointModel,
    BacktestOrderModel,
    BacktestReportModel,
    BacktestTask,
    BacktestTradeModel,
)


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "rb2405",
        "exchange": "SHFE",
        "interval": "1m",
        "start": "2024-01-02T09:00:00Z",
        "end": "2024-01-02T15:00:00Z",
        "strategy_class_path": "tests.test_backtest_task_api:FakeStrategy",
        "strategy_parameters": {"ema_period": 21},
        "rate": 0.0001,
        "slippage": 1,
        "size": 10,
        "pricetick": 1,
        "capital": 100000,
    }
    payload.update(overrides)
    return payload


class FakeStrategy:
    pass


def test_create_vnpy_backtest_task_returns_queued_task(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    queued_ids: list[int] = []

    def fake_enqueue(task_id: int) -> str:
        queued_ids.append(task_id)
        return f"job-{task_id}"

    monkeypatch.setattr(api_module, "enqueue_backtest_task", fake_enqueue)

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post("/api/backtests/tasks", json=_valid_payload())

        assert response.status_code == 200
        payload = response.json()
        assert payload["engine_type"] == "vnpy"
        assert payload["status"] == "queued"
        assert payload["data_role"] == "primary"
        assert payload["research_only"] is False
        assert payload["rq_job_id"] == f"job-{payload['id']}"
        assert "回测结果不等于实盘结果" in payload["disclaimer"]
        assert queued_ids == [payload["id"]]
    finally:
        app.dependency_overrides.clear()


def test_create_task_rejects_legacy_reference_without_research_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/backtests/tasks",
            json=_valid_payload(data_role="legacy_reference", research_only=False),
        )

        assert response.status_code == 422
        assert "research_only=true" in response.text
    finally:
        app.dependency_overrides.clear()


def test_create_task_rejects_live_or_auto_order_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        for forbidden in ("live", "real", "trading", "auto_order"):
            response = TestClient(app).post("/api/backtests/tasks", json=_valid_payload(task_type=forbidden))
            assert response.status_code == 422
            assert "not allowed for backtest tasks" in response.text
    finally:
        app.dependency_overrides.clear()


def test_task_list_and_missing_task_404(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created = client.post("/api/backtests/tasks", json=_valid_payload()).json()

        list_response = client.get("/api/backtests/tasks")
        assert list_response.status_code == 200
        rows = list_response.json()
        assert rows[0]["id"] == created["id"]
        assert rows[0]["disclaimer"]

        detail_response = client.get(f"/api/backtests/tasks/{created['id']}")
        assert detail_response.status_code == 200
        assert detail_response.json()["task_no"] == created["task_no"]

        missing_response = client.get("/api/backtests/tasks/999999")
        assert missing_response.status_code == 404
        assert "not found" in missing_response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_report_list_detail_and_curves_are_serializable() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        task = BacktestTask(task_no="BTV-API-001", engine_type="vnpy", status="success", data_source="local_parquet", data_role="primary")
        session.add(task)
        session.flush()
        report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no="RPT-API-001",
            template_name="vnpy",
            engine_type="vnpy",
            symbol="rb2405",
            contract="rb2405",
            period="1m",
            status="success",
            summary={"total_return": 0.01},
            warnings=["demo"],
            equity_curve=[{"datetime": "2024-01-02T09:00:00", "equity": 100000.0}],
            drawdown_curve=[{"datetime": "2024-01-02T09:00:00", "drawdown": 0.0}],
        )
        session.add(report)
        session.flush()
        session.add(
            BacktestTradeModel(
                report_id=report.id,
                trade_no="T-1",
                symbol="rb2405",
                contract="rb2405",
                direction="long",
                open_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                open_price=3500,
                close_time=datetime(2024, 1, 2, 10, 0, tzinfo=UTC),
                close_price=3520,
                volume=1,
                turnover=35000,
                commission=3,
                slippage=1,
                gross_pnl=200,
                net_pnl=196,
                return_pct=0.00196,
                holding_bars=12,
                entry_reason="test",
                exit_reason="test",
                raw_payload={"source": "detail_table"},
            )
        )
        session.add(
            BacktestOrderModel(
                report_id=report.id,
                order_no="O-1",
                symbol="rb",
                contract="rb2405",
                direction="long",
                offset="open",
                order_type="limit",
                status="filled",
                order_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                price=3500,
                volume=1,
                traded=1,
                raw_payload={"orderid": "O-1"},
            )
        )
        session.add(
            BacktestEquityCurvePointModel(
                report_id=report.id,
                point_index=0,
                point_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                equity=123456.0,
                raw_payload={"datetime": "2024-01-02T09:00:00", "equity": 123456.0},
            )
        )
        session.add(
            BacktestDrawdownCurvePointModel(
                report_id=report.id,
                point_index=0,
                point_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                drawdown=12.0,
                drawdown_pct=0.12,
                raw_payload={"datetime": "2024-01-02T09:00:00", "drawdown": 12.0, "drawdown_pct": 0.12},
            )
        )
        session.commit()
        report_id = report.id

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        reports = client.get("/api/backtests/reports")
        assert reports.status_code == 200
        assert reports.json()[0]["id"] == report_id

        detail = client.get(f"/api/backtests/reports/{report_id}")
        assert detail.status_code == 200
        assert "回测结果不等于实盘结果" in detail.json()["disclaimer"]
        assert detail.json()["orders"][0]["order_no"] == "O-1"

        trades = client.get(f"/api/backtests/reports/{report_id}/trades")
        assert trades.status_code == 200
        assert trades.json()[0]["trade_no"] == "T-1"
        assert trades.json()[0]["raw_payload"]["source"] == "detail_table"

        equity = client.get(f"/api/backtests/reports/{report_id}/equity-curve")
        assert equity.status_code == 200
        assert equity.json()[0]["equity"] == 123456.0

        drawdown = client.get(f"/api/backtests/reports/{report_id}/drawdown-curve")
        assert drawdown.status_code == 200
        assert drawdown.json()[0]["drawdown"] == 12.0

        missing = client.get("/api/backtests/reports/999999")
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
