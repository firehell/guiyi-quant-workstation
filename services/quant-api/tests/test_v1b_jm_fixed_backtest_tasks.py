from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.runner import BacktestTaskRunner
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import (
    BacktestDrawdownCurvePointModel,
    BacktestEquityCurvePointModel,
    BacktestReportModel,
    BacktestTask,
    BacktestTradeModel,
)
from app.models.data_center import MarketDataFile
from app.models.data_center import Contract, Exchange, FuturesTradingParameter, Instrument, MainContractMap, TradingCalendar


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_jm_v1b_files(session, tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for period in ("1d", "15m", "5m"):
        path = tmp_path / f"jm_MAIN_{period}_v1b.parquet"
        path.write_text("registered test placeholder", encoding="utf-8")
        paths[period] = path
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period=period,
                start_time=datetime(2023, 1, 1, tzinfo=UTC),
                end_time=datetime(2025, 12, 31, 15, 0, tzinfo=UTC),
                file_path=str(path),
                row_count=1000,
                data_version="v1b_jm_20230101_20251231",
                data_role="primary",
                quality_status="passed",
            )
        )
    session.commit()
    return paths


def _seed_jm_contract_reference(session, *, with_params: bool = True) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code="JM2405",
            instrument_symbol="jm",
            exchange_code="DCE",
            name="焦煤2405",
            contract_month="2405",
            contract_multiplier=60,
            maturity_date=date(2024, 5, 15),
            provider="rqdata",
        )
    )
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 29), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 30), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 5, 1), is_trading_day=False, provider="rqdata"),
        ]
    )
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2024, 1, 2),
            rank=1,
            contract_code="JM2405",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="test-v1",
        )
    )
    if with_params:
        session.add(
            FuturesTradingParameter(
                contract_code="JM2405",
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=date(2024, 1, 2),
                long_margin_ratio=Decimal("0.12"),
                short_margin_ratio=Decimal("0.13"),
                open_commission=Decimal("0.0001"),
                close_commission=Decimal("0.00011"),
                close_today_commission=Decimal("0.0002"),
                commission_type="by_money",
                price_tick=Decimal("0.5"),
                contract_multiplier=60,
                provider="rqdata",
                data_version="test-v1",
            )
        )
    session.commit()


class FakeV1bSuccessfulAdapter:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "success",
            "statistics": {
                "capital": 100000,
                "end_balance": 100600,
                "total_return": 0.006,
                "max_drawdown": 120.0,
                "total_trade_count": 1,
            },
            "strategy_trades": [
                {
                    "daily_direction": "long",
                    "entry_interval": request.strategy_parameters["entry_interval"],
                    "entry_reason": "daily_long_ema21_pullback_macd_confirmed",
                    "exit_reason": "max_hold_bars_exit",
                    "hold_bars": 8,
                    "stop_loss_price": 980.0,
                    "entry_datetime": "2024-01-02T09:15:00",
                    "exit_datetime": "2024-01-02T11:15:00",
                    "entry_price": 1000.0,
                    "exit_price": 1010.0,
                    "direction": "long",
                    "volume": 1,
                }
            ],
            "orders": [{"orderid": "O-V1B-1", "symbol": request.symbol, "direction": "long", "price": 1000, "volume": 1}],
            "equity_curve": [{"date": "2024-01-02", "balance": 100000}, {"date": "2024-01-03", "balance": 100600}],
            "drawdown_curve": [{"date": "2024-01-02", "drawdown": 0, "ddpercent": 0}],
            "warnings": [],
        }


def test_create_jm_v1b_15m_and_5m_tasks_enter_backtest_queue(tmp_path: Path, monkeypatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)

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
        client = TestClient(app)
        created_15m = client.post("/api/backtests/v1b/jm/15m/tasks")
        created_5m = client.post("/api/backtests/v1b/jm/5m/tasks")

        assert created_15m.status_code == 200
        assert created_5m.status_code == 200
        assert created_15m.json()["status"] == "queued"
        assert created_5m.json()["status"] == "queued"
        assert created_15m.json()["fixed_task"]["entry_interval"] == "15m"
        assert created_5m.json()["fixed_task"]["entry_interval"] == "5m"
        assert queued_ids == [created_15m.json()["id"], created_5m.json()["id"]]

        with SessionLocal() as session:
            tasks = session.scalars(select(BacktestTask).order_by(BacktestTask.id)).all()
            assert [task.task_type for task in tasks] == ["v1b_jm_15m_entry", "v1b_jm_5m_entry"]
            assert [task.vnpy_setting_json["interval"] for task in tasks] == ["15m", "5m"]
            assert all(task.vnpy_strategy_class and "jm_v1b_daily_direction_fast_entry" in task.vnpy_strategy_class for task in tasks)
            assert all(task.vnpy_setting_json["auxiliary_bar_data_paths"].keys() == {"1d"} for task in tasks)
            assert tasks[0].vnpy_setting_json["strategy_parameters"]["entry_interval"] == "15m"
            assert tasks[1].vnpy_setting_json["strategy_parameters"]["entry_interval"] == "5m"
            assert all(task.vnpy_setting_json["strategy_parameters"]["max_hold_bars_min"] == 5 for task in tasks)
            assert all(task.vnpy_setting_json["strategy_parameters"]["max_hold_bars_max"] == 8 for task in tasks)
            assert all(task.vnpy_setting_json["strategy_parameters"]["stop_loss_atr_multiple"] > 0 for task in tasks)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("entry_interval", ["15m", "5m"])
def test_jm_v1b_fixed_task_runner_persists_real_contract_costs_and_totals(tmp_path: Path, entry_interval: str) -> None:
    from app.backtest.service import BacktestService
    from app.backtest.v1b_jm_tasks import build_jm_v1b_task_config

    SessionLocal = _session_factory()
    adapter = FakeV1bSuccessfulAdapter()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_contract_reference(session)
        spec = build_jm_v1b_task_config(session, entry_interval)  # type: ignore[arg-type]
        task = BacktestService(session).create_task(spec.config)
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "success"
        assert adapter.requests[0].strategy_class_path.endswith("JmV1bDailyDirectionFastEntryStrategy")
        assert adapter.requests[0].strategy_parameters["entry_interval"] == entry_interval
        assert adapter.requests[0].auxiliary_bar_data_paths.keys() == {"1d"}
        assert task.status == "success"
        assert task.error_message is None
        assert task.traceback is None

        report = session.get(BacktestReportModel, task.result_payload["report_id"])
        assert report is not None
        assert report.strategy_code == "jm_v1b_daily_direction_fast_entry"
        assert report.period == entry_interval
        assert report.trade_count == 1
        assert report.total_commission == pytest.approx(18.12)
        assert report.total_slippage == pytest.approx(60.0)
        assert report.max_margin_required == pytest.approx(7800.0)
        assert report.max_margin_usage_pct == pytest.approx(0.078)
        assert report.summary["total_commission"] == pytest.approx(report.total_commission)
        assert report.summary["total_slippage"] == pytest.approx(report.total_slippage)

        trades = session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id)).all()
        equity = session.scalars(select(BacktestEquityCurvePointModel).where(BacktestEquityCurvePointModel.report_id == report.id)).all()
        drawdown = session.scalars(select(BacktestDrawdownCurvePointModel).where(BacktestDrawdownCurvePointModel.report_id == report.id)).all()

        assert len(trades) == 1
        assert trades[0].entry_reason == "daily_long_ema21_pullback_macd_confirmed"
        assert trades[0].exit_reason == "max_hold_bars_exit"
        assert trades[0].holding_bars == 8
        assert trades[0].contract == "JM2405"
        assert trades[0].entry_contract == "JM2405"
        assert trades[0].exit_contract == "JM2405"
        assert trades[0].contract_multiplier == 60
        assert trades[0].price_tick == 0.5
        assert trades[0].commission == pytest.approx(18.12)
        assert trades[0].slippage == pytest.approx(60.0)
        assert trades[0].margin_ratio == 0.13
        assert trades[0].margin_required == pytest.approx(7800.0)
        assert trades[0].parameter_source == "futures_trading_parameters"
        assert report.total_commission == pytest.approx(sum(trade.commission for trade in trades))
        assert report.total_slippage == pytest.approx(sum(trade.slippage for trade in trades))
        assert report.max_margin_required == pytest.approx(max(trade.margin_required or 0 for trade in trades))
        assert trades[0].raw_payload["daily_direction"] == "long"
        assert trades[0].raw_payload["entry_interval"] == entry_interval
        assert trades[0].raw_payload["stop_loss_price"] == 980.0
        assert trades[0].raw_payload["research_symbol"] == "jm.MAIN"
        assert len(equity) == 2
        assert len(drawdown) == 1


def test_jm_v1b_runner_fails_clearly_when_trading_parameters_are_missing(tmp_path: Path) -> None:
    from app.backtest.service import BacktestService
    from app.backtest.v1b_jm_tasks import build_jm_v1b_task_config

    SessionLocal = _session_factory()
    adapter = FakeV1bSuccessfulAdapter()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_contract_reference(session, with_params=False)
        spec = build_jm_v1b_task_config(session, "15m")
        task = BacktestService(session).create_task(spec.config)
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "failed"
        assert task.status == "failed"
        assert task.error_type == "TradingParameterMissingError"
        assert task.error_message is not None
        assert "trading parameters missing for contract=JM2405" in task.error_message
        assert task.traceback


def test_jm_v1b_fixed_task_rejects_missing_formal_data(tmp_path: Path, monkeypatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        missing = session.scalar(select(MarketDataFile).where(MarketDataFile.period == "15m"))
        assert missing is not None
        Path(missing.file_path).unlink()
        session.commit()

    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post("/api/backtests/v1b/jm/15m/tasks")

        assert response.status_code == 422
        assert "registered but missing on disk" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
