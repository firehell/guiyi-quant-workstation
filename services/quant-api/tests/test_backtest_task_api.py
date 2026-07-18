from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import (
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
        "instrument_symbol": "rb",
        "contract_code": "rb2405",
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


def _legacy_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
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
        "research_only": True,
    }
    payload.update(overrides)
    return payload


def _install_fake_formal_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.backtest.service import BacktestService

    def fake_create_formal_task(self, request):
        task = BacktestTask(
            task_no=f"BT-API-{len(self.session.new) + 1}",
            task_type=request.task_type,
            engine_type="vnpy",
            data_source="rqdata",
            data_role="primary",
            data_version="test-v1",
            profile_id="intraday_research_v1",
            market_data_file_id=101,
            binding_snapshot={"schema_version": "backtest_binding_snapshot_v1"},
            research_only=False,
            status="pending",
            request_payload=request.model_dump(mode="json"),
            result_payload={},
        )
        self.session.add(task)
        self.session.flush()
        return task

    monkeypatch.setattr(BacktestService, "create_formal_task", fake_create_formal_task)


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
    _install_fake_formal_persistence(monkeypatch)

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
    _install_fake_formal_persistence(monkeypatch)

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
        assert "extra_forbidden" in response.text
    finally:
        app.dependency_overrides.clear()


def test_create_task_rejects_client_supplied_bar_paths_before_persistence() -> None:
    response = TestClient(app).post(
        "/api/backtests/tasks",
        json=_valid_payload(
            bar_data_path="/tmp/client-primary.parquet",
            auxiliary_bar_data_paths={"1d": "/tmp/client-daily.parquet"},
        ),
    )

    assert response.status_code == 422
    assert response.text.count("extra_forbidden") == 2


def test_create_task_rejects_inactive_validation_and_legacy_roles_even_for_research(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        for inactive_role in ("validation", "legacy_reference", "candidate"):
            response = client.post(
                "/api/backtests/tasks",
                json=_valid_payload(data_role=inactive_role, research_only=True),
            )

            assert response.status_code == 422
            assert "extra_forbidden" in response.text
    finally:
        app.dependency_overrides.clear()


def test_create_task_rejects_live_or_auto_order_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")
    _install_fake_formal_persistence(monkeypatch)

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
    _install_fake_formal_persistence(monkeypatch)

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
            summary={
                "initial_capital": 100000.0,
                "final_equity": 100092.0,
                "total_return": 0.01,
                "annual_return": 0.02,
                "max_drawdown": 104.0 / 100196.0,
                "max_drawdown_amount": 104.0,
                "max_drawdown_pct": 104.0 / 100196.0,
                "max_margin_required": 27500.0,
                "max_margin_usage_pct": 0.275,
                "rollover_exit_count": 1,
                "delivery_risk_exit_count": 1,
                "trade_count": 2,
                "total_commission": 6.0,
                "total_slippage": 2.0,
                "report_metadata": {
                    "vt_symbol": "rb2405.SHFE",
                    "bar_data_path": "/Volumes/local/secret.parquet",
                    "token": "should-not-leak",
                },
            },
            warnings=["demo"],
        )
        session.add(report)
        session.flush()
        session.add(
            BacktestTradeModel(
                report_id=report.id,
                trade_no="T-1",
                sequence=1,
                symbol="rb2405",
                exchange="SHFE",
                research_contract="rb2405",
                contract="rb2405",
                timeframe="1m",
                entry_contract="JM2405",
                exit_contract="JM2409",
                entry_contract_month="2024-05",
                exit_contract_month="2024-09",
                direction="long",
                open_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                open_price=3500,
                close_time=datetime(2024, 1, 2, 10, 0, tzinfo=UTC),
                close_price=3520,
                volume=1,
                turnover=35000,
                contract_multiplier=60,
                price_tick=0.5,
                commission=3,
                slippage=1,
                margin_ratio=0.13,
                margin_required=27300.0,
                parameter_source="futures_trading_parameters",
                fee_rule_source={"source": "futures_trading_parameters"},
                main_contract_source={"provider": "rqdata", "data_version": "test-v1"},
                rollover_forced_exit=True,
                delivery_risk_exit=True,
                rollover_reason="delivery_month_guard",
                gross_pnl=200,
                net_pnl=196,
                return_pct=0.00196,
                holding_bars=12,
                entry_reason="test",
                exit_reason="test",
                raw_payload={
                    "source": "detail_table",
                    "order_id": "O-RAW-1",
                    "trading_day": "2024-01-02",
                    "holding_minutes": 60,
                    "equity_after_trade": 100196,
                    "note": "first trade note",
                    "traceback": "hidden traceback",
                    "file_path": "/Users/local/secret.parquet",
                    "token": "hidden-token",
                    "message": "safe",
                },
            )
        )
        session.add(
            BacktestTradeModel(
                report_id=report.id,
                trade_no="T-2",
                sequence=2,
                symbol="rb2405",
                exchange="SHFE",
                research_contract="rb2405",
                contract="rb2405",
                timeframe="1m",
                entry_contract="JM2409",
                exit_contract="JM2409",
                direction="short",
                open_time=datetime(2024, 1, 2, 10, 30, tzinfo=UTC),
                open_price=3530,
                close_time=datetime(2024, 1, 2, 11, 0, tzinfo=UTC),
                close_price=3540,
                volume=1,
                turnover=35400,
                contract_multiplier=60,
                price_tick=0.5,
                commission=3,
                slippage=1,
                margin_ratio=0.13,
                margin_required=27500.0,
                parameter_source="futures_trading_parameters",
                fee_rule_source={"source": "futures_trading_parameters"},
                main_contract_source={"provider": "rqdata", "data_version": "test-v1"},
                rollover_forced_exit=False,
                delivery_risk_exit=False,
                rollover_reason=None,
                gross_pnl=-100,
                net_pnl=-104,
                return_pct=-0.00104,
                holding_bars=6,
                entry_reason="short signal",
                exit_reason="stop",
                raw_payload={"source": "detail_table", "message": "second safe"},
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
                raw_payload={"orderid": "O-1", "license": "hidden-license", "path": "/private/tmp/secret"},
            )
        )
        empty_report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no="RPT-API-EMPTY",
            template_name="vnpy",
            engine_type="vnpy",
            symbol="rb2405",
            contract="rb2405",
            period="5m",
            status="success",
            summary={"initial_capital": 100000.0, "final_equity": 100000.0, "total_return": 0.0, "trade_count": 0},
            warnings=[],
        )
        session.add(empty_report)
        session.flush()
        failed_report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no="RPT-API-FAILED",
            template_name="vnpy",
            engine_type="vnpy",
            symbol="rb2405",
            contract="rb2405",
            period="5m",
            status="failed",
            summary={"total_return": 0.0},
            warnings=[],
            error_message="demo failure",
        )
        session.add(failed_report)
        session.flush()
        session.commit()
        report_id = report.id
        empty_report_id = empty_report.id
        failed_report_id = failed_report.id

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        reports = client.get("/api/backtests/reports")
        assert reports.status_code == 200
        assert any(row["id"] == report_id for row in reports.json())
        assert all(row["status"] in {"success", "completed"} for row in reports.json())

        all_reports = client.get("/api/backtests/reports", params={"status": "all"})
        assert all_reports.status_code == 200
        assert any(row["id"] == failed_report_id for row in all_reports.json())

        detail = client.get(f"/api/backtests/reports/{report_id}")
        assert detail.status_code == 200
        detail_payload = detail.json()
        assert "回测结果不等于实盘结果" in detail_payload["disclaimer"]
        assert detail_payload["orders"][0]["order_no"] == "O-1"
        assert detail_payload["max_drawdown_amount"] == 104.0
        assert detail_payload["max_drawdown_pct"] == pytest.approx(104.0 / 100196.0)
        assert detail_payload["max_margin_required"] == 27500.0
        assert detail_payload["max_margin_usage_pct"] == 0.275
        assert detail_payload["rollover_exit_count"] == 1
        assert detail_payload["delivery_risk_exit_count"] == 1
        assert detail_payload["average_hold_bars"] == 9.0
        assert detail_payload["metric_units"]["max_drawdown_amount"] == "CNY"
        assert detail_payload["metric_units"]["max_drawdown_pct"] == "ratio"
        assert "bar_data_path" not in detail_payload["summary"]["report_metadata"]
        assert "token" not in detail.text
        assert "traceback" not in detail.text
        assert "license" not in detail.text
        assert "/Volumes/" not in detail.text
        assert "/Users/" not in detail.text
        assert "/private/" not in detail.text

        trades = client.get(f"/api/backtests/reports/{report_id}/trades")
        assert trades.status_code == 200
        trades_payload = trades.json()
        assert trades_payload["report_id"] == report_id
        assert trades_payload["total"] == 2
        assert trades_payload["limit"] == 100
        assert trades_payload["offset"] == 0
        assert trades_payload["items"][0]["trade_no"] == "T-1"
        assert trades_payload["items"][0]["sequence"] == 1
        assert trades_payload["items"][0]["exchange"] == "SHFE"
        assert trades_payload["items"][0]["research_contract"] == "rb2405"
        assert trades_payload["items"][0]["timeframe"] == "1m"
        assert trades_payload["items"][0]["entry_contract"] == "JM2405"
        assert trades_payload["items"][0]["exit_contract"] == "JM2409"
        assert trades_payload["items"][0]["contract_multiplier"] == 60
        assert trades_payload["items"][0]["price_tick"] == 0.5
        assert trades_payload["items"][0]["margin_ratio"] == 0.13
        assert trades_payload["items"][0]["margin_required"] == 27300.0
        assert trades_payload["items"][0]["parameter_source"] == "futures_trading_parameters"
        assert trades_payload["items"][0]["main_contract_source"]["provider"] == "rqdata"
        assert trades_payload["items"][0]["rollover_forced_exit"] is True
        assert trades_payload["items"][0]["delivery_risk_exit"] is True
        assert trades_payload["items"][0]["rollover_reason"] == "delivery_month_guard"
        assert trades_payload["items"][0]["raw_payload"]["source"] == "detail_table"
        assert trades_payload["items"][0]["raw_payload"]["message"] == "safe"
        assert "traceback" not in trades.text
        assert "/Users/" not in trades.text

        filtered = client.get(f"/api/backtests/reports/{report_id}/trades", params={"direction": "short", "limit": 1})
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["trade_no"] == "T-2"

        sorted_trades = client.get(
            f"/api/backtests/reports/{report_id}/trades",
            params={"sort_by": "net_pnl", "sort_order": "desc", "limit": 1, "offset": 0},
        )
        assert sorted_trades.status_code == 200
        assert sorted_trades.json()["items"][0]["trade_no"] == "T-1"

        csv_export = client.get(f"/api/backtests/reports/{report_id}/trades/export", params={"format": "csv"})
        assert csv_export.status_code == 200
        assert csv_export.text.startswith("\ufeffreport_id,trade_id,order_id")
        assert "O-RAW-1" in csv_export.text
        assert "first trade note" in csv_export.text
        assert "token" not in csv_export.text
        assert "/Users/" not in csv_export.text

        json_export = client.get(
            f"/api/backtests/reports/{report_id}/trades/export",
            params={"format": "json", "direction": "short"},
        )
        assert json_export.status_code == 200
        export_payload = json_export.json()
        assert export_payload["report_summary"]["report_id"] == report_id
        assert export_payload["report_summary"]["strategy_code"] is None
        assert export_payload["trade_count"] == 1
        assert export_payload["trades"][0]["trade_no"] == "T-2"
        assert export_payload["trades"][0]["strategy_code"] is None
        assert "回测结果不等于实盘结果" in export_payload["disclaimer"]

        orders = client.get(f"/api/backtests/reports/{report_id}/orders")
        assert orders.status_code == 200
        assert orders.json()[0]["order_no"] == "O-1"
        assert orders.json()[0]["raw_payload"]["orderid"] == "O-1"
        assert "license" not in orders.text
        assert "/private/" not in orders.text

        equity = client.get(f"/api/backtests/reports/{report_id}/equity-curve")
        assert equity.status_code == 200
        assert equity.json()[0]["equity"] == 100000.0
        assert equity.json()[1]["equity"] == 100196.0

        drawdown = client.get(f"/api/backtests/reports/{report_id}/drawdown-curve")
        assert drawdown.status_code == 200
        assert drawdown.json()[2]["drawdown"] == 104.0
        assert "account" not in drawdown.text

        empty_trades = client.get(f"/api/backtests/reports/{empty_report_id}/trades")
        assert empty_trades.status_code == 200
        assert empty_trades.json()["items"] == []
        assert empty_trades.json()["total"] == 0
        empty_detail = client.get(f"/api/backtests/reports/{empty_report_id}")
        empty_equity = client.get(f"/api/backtests/reports/{empty_report_id}/equity-curve")
        empty_drawdown = client.get(f"/api/backtests/reports/{empty_report_id}/drawdown-curve")
        assert empty_detail.status_code == 200
        assert empty_detail.json()["trades"] == []
        assert empty_detail.json()["max_drawdown_amount"] == 0.0
        assert empty_detail.json()["max_drawdown_pct"] == 0.0
        assert empty_detail.json()["rollover_exit_count"] == 0
        assert empty_detail.json()["delivery_risk_exit_count"] == 0
        assert empty_detail.json()["average_hold_bars"] is None
        assert empty_detail.json()["metric_units"]["total_commission"] == "CNY"
        assert empty_equity.status_code == 200
        assert empty_equity.json()[0]["equity"] == 100000.0
        assert empty_drawdown.status_code == 200
        assert empty_drawdown.json()[0]["drawdown"] == 0.0

        missing = client.get("/api/backtests/reports/999999")
        assert missing.status_code == 404
        missing_orders = client.get("/api/backtests/reports/999999/orders")
        assert missing_orders.status_code == 404
        missing_export = client.get("/api/backtests/reports/999999/trades/export")
        assert missing_export.status_code == 404
        failed_trades = client.get(f"/api/backtests/reports/{failed_report_id}/trades")
        assert failed_trades.status_code == 409
        assert "status is failed" in failed_trades.json()["detail"]
        bad_sort = client.get(f"/api/backtests/reports/{report_id}/trades", params={"sort_by": "unknown"})
        assert bad_sort.status_code == 422
        bad_export_format = client.get(f"/api/backtests/reports/{report_id}/trades/export", params={"format": "xlsx"})
        assert bad_export_format.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_persisted_report_and_api_recompute_max_consecutive_losses_from_trades() -> None:
    from app.backtest.service import BacktestService

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        service = BacktestService(session)
        task = service.create_task(_legacy_payload(interval="5m"))
        task.started_at = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        service.persist_result(
            task,
            {
                "summary": {
                    "capital": 100000,
                    "end_balance": 99900,
                    "max_consecutive_losses": 0,
                },
                "trades": [
                    {
                        "tradeid": "T-3",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:20:00Z",
                        "exit_datetime": "2024-01-02T09:25:00Z",
                        "entry_price": 100,
                        "exit_price": 101,
                        "net_pnl": 10,
                    },
                    {
                        "tradeid": "T-1",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:00:00Z",
                        "exit_datetime": "2024-01-02T09:05:00Z",
                        "entry_price": 100,
                        "exit_price": 99,
                        "net_pnl": -10,
                    },
                    {
                        "tradeid": "T-2",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:10:00Z",
                        "exit_datetime": "2024-01-02T09:15:00Z",
                        "entry_price": 100,
                        "exit_price": 99,
                        "net_pnl": -10,
                    },
                    {
                        "tradeid": "T-4",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:30:00Z",
                        "exit_datetime": "2024-01-02T09:35:00Z",
                        "entry_price": 100,
                        "exit_price": 99,
                        "net_pnl": -10,
                    },
                    {
                        "tradeid": "T-5",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:40:00Z",
                        "exit_datetime": "2024-01-02T09:45:00Z",
                        "entry_price": 100,
                        "exit_price": 99,
                        "net_pnl": -10,
                    },
                    {
                        "tradeid": "T-6",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:50:00Z",
                        "exit_datetime": "2024-01-02T09:55:00Z",
                        "entry_price": 100,
                        "exit_price": 99,
                        "net_pnl": -10,
                    },
                ],
                "equity_curve": [{"datetime": "2024-01-02T09:00:00Z", "equity": 100000}],
                "drawdown_curve": [{"datetime": "2024-01-02T09:00:00Z", "drawdown": 100}],
            },
        )
        session.commit()
        report = session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)).one()
        assert report.max_consecutive_losses == 3
        assert report.summary["max_consecutive_losses"] == 3
        report_id = report.id

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        detail = TestClient(app).get(f"/api/backtests/reports/{report_id}")

        assert detail.status_code == 200
        payload = detail.json()
        assert payload["max_consecutive_losses"] == 3
        assert payload["summary"]["max_consecutive_losses"] == 3
    finally:
        app.dependency_overrides.clear()


def test_persist_result_stores_real_contract_cost_and_risk_fields() -> None:
    from app.backtest.service import BacktestService

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        service = BacktestService(session)
        task = service.create_task(_legacy_payload(symbol="jm.MAIN", exchange="DCE", interval="15m"))
        task.started_at = datetime(2024, 4, 29, 9, 0, tzinfo=UTC)
        service.persist_result(
            task,
            {
                "summary": {
                    "capital": 100000,
                    "end_balance": 101000,
                    "max_drawdown_amount": 1800.0,
                    "max_drawdown_pct": 0.018,
                    "total_commission": 18.0,
                    "total_slippage": 30.0,
                    "max_margin_required": 15300.0,
                    "max_margin_usage_pct": 0.153,
                    "rollover_exit_count": 1,
                    "delivery_risk_exit_count": 1,
                },
                "trades": [
                    {
                        "tradeid": "JM-T-1",
                        "symbol": "jm",
                        "direction": "long",
                        "entry_datetime": "2024-04-29T09:00:00Z",
                        "exit_datetime": "2024-04-30T14:45:00Z",
                        "entry_price": 1800,
                        "exit_price": 1810,
                        "volume": 1,
                        "contract_multiplier": 60,
                        "price_tick": 0.5,
                        "commission": 18.0,
                        "slippage": 30.0,
                        "gross_pnl": 600.0,
                        "net_pnl": 552.0,
                        "entry_contract": "JM2405",
                        "exit_contract": "JM2405",
                        "entry_contract_month": "2024-05",
                        "exit_contract_month": "2024-05",
                        "margin_ratio": 0.13,
                        "margin_required": 14040.0,
                        "parameter_source": "futures_trading_parameters",
                        "fee_rule_source": {"source": "futures_trading_parameters"},
                        "main_contract_source": {"provider": "rqdata", "data_version": "test-v1"},
                        "rollover_forced_exit": True,
                        "delivery_risk_exit": True,
                        "rollover_reason": "last_allowed_holding_date",
                    }
                ],
                "drawdown_curve": [{"datetime": "2024-04-30T14:45:00Z", "drawdown": 1800.0, "drawdown_pct": 0.018}],
            },
        )
        session.commit()

        report = session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)).one()
        trade = session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id)).one()

        assert report.max_drawdown_amount == 0.0
        assert report.max_drawdown_pct == 0.0
        assert report.max_margin_required == 14040.0
        assert report.max_margin_usage_pct == 0.1404
        assert report.rollover_exit_count == 1
        assert report.delivery_risk_exit_count == 1
        assert trade.entry_contract == "JM2405"
        assert trade.exit_contract == "JM2405"
        assert trade.contract_multiplier == 60
        assert trade.price_tick == 0.5
        assert trade.margin_ratio == 0.13
        assert trade.margin_required == 14040.0
        assert trade.parameter_source == "futures_trading_parameters"
        assert trade.fee_rule_source == {"source": "futures_trading_parameters"}
        assert trade.main_contract_source == {"provider": "rqdata", "data_version": "test-v1"}
        assert trade.rollover_forced_exit is True
        assert trade.delivery_risk_exit is True
        assert trade.rollover_reason == "last_allowed_holding_date"
        report_id = report.id

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        detail = TestClient(app).get(f"/api/backtests/reports/{report_id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["max_drawdown_amount"] == 0.0
        assert payload["max_drawdown_pct"] == 0.0
        assert payload["trades"][0]["entry_contract"] == "JM2405"
        assert payload["trades"][0]["margin_required"] == 14040.0
        assert payload["trades"][0]["rollover_forced_exit"] is True
    finally:
        app.dependency_overrides.clear()
