from __future__ import annotations

from datetime import UTC, datetime
import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.backtest import (
    BacktestOrderModel,
    BacktestReportModel,
    BacktestTask,
    BacktestTradeModel,
)
from app.schemas.backtest import BacktestDataRole, BacktestEngineType, BacktestTaskConfig
from app.vnpy_integration.errors import VnpyNotInstalledError


REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = REPO_ROOT / "experiments" / "vnpy_rqdata_demo" / "generate_standard_fixture.py"

GENERATOR_SPEC = importlib.util.spec_from_file_location("generate_standard_fixture", GENERATOR_PATH)
assert GENERATOR_SPEC is not None
assert GENERATOR_SPEC.loader is not None
fixture_generator = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(fixture_generator)


class FakeSuccessfulAdapter:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "success",
            "statistics": {"capital": 100000, "end_balance": 101000, "total_return": 1.0, "max_drawdown": 0.02},
            "trades": [
                {
                    "tradeid": "T-1",
                    "symbol": request.symbol,
                    "direction": "多",
                    "price": 3500,
                    "volume": 1,
                    "datetime": "2024-01-02T10:00:00",
                }
            ],
            "orders": [
                {
                    "orderid": "O-1",
                    "symbol": request.symbol,
                    "direction": "多",
                    "status": "全部成交",
                    "price": 3500,
                    "volume": 1,
                    "traded": 1,
                    "datetime": "2024-01-02T09:00:00",
                }
            ],
            "equity_curve": [{"date": "2024-01-02", "balance": 100000}, {"date": "2024-01-03", "balance": 101000}],
            "drawdown_curve": [{"date": "2024-01-02", "drawdown": 0, "ddpercent": 0}],
            "warnings": ["fake adapter result"],
        }


class FakeMissingVnpyAdapter:
    def run(self, request: Any) -> dict[str, Any]:
        raise VnpyNotInstalledError()


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _valid_config(**overrides: Any) -> BacktestTaskConfig:
    payload: dict[str, Any] = {
        "symbol": "rb2405",
        "exchange": "SHFE",
        "interval": "1m",
        "start": datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        "end": datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
        "strategy_class_path": "tests.test_backtest_service_runner:FakeStrategy",
        "strategy_code": "fake_strategy",
        "strategy_version": "test-v1",
        "strategy_parameters": {"ema_period": 21},
        "rate": 0.0001,
        "slippage": 1,
        "size": 10,
        "pricetick": 1,
        "capital": 100000,
        "quality_status": "passed",
    }
    payload.update(overrides)
    return BacktestTaskConfig(**payload)


class FakeStrategy:
    pass


def test_backtest_task_config_creates_legal_vnpy_config_with_primary_default() -> None:
    config = _valid_config()

    assert config.engine_type is BacktestEngineType.VNPY
    assert config.data_role is BacktestDataRole.PRIMARY
    assert config.research_only is False
    assert config.strategy_class_path.endswith("FakeStrategy")


def test_backtest_task_config_rejects_legacy_reference_without_research_only() -> None:
    with pytest.raises(ValidationError, match="research_only=true"):
        _valid_config(data_role=BacktestDataRole.LEGACY_REFERENCE)


def test_backtest_task_config_rejects_failed_quality_status() -> None:
    with pytest.raises(ValidationError, match="failed quality_status"):
        _valid_config(quality_status="failed")


def test_backtest_service_creates_task_and_generates_vnpy_setting() -> None:
    from app.backtest.service import BacktestService

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        service = BacktestService(session)
        task = service.create_task(_valid_config())
        session.commit()

        assert task.id is not None
        assert task.engine_type == "vnpy"
        assert task.status == "pending"
        assert task.data_role == "primary"
        assert task.research_only is False
        assert task.vnpy_strategy_class == "tests.test_backtest_service_runner:FakeStrategy"
    assert task.vnpy_setting_json["vt_symbol"] == "rb2405.SHFE"
    assert task.vnpy_setting_json["execution_timing"] == "next_bar_open"
    assert task.vnpy_setting_json["strategy_code"] == "fake_strategy"


def test_backtest_task_runner_marks_missing_vnpy_as_clear_failed_message() -> None:
    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        task = BacktestService(session).create_task(_valid_config())
        session.commit()

        result = BacktestTaskRunner(session, adapter=FakeMissingVnpyAdapter()).run(task.id)
        session.refresh(task)

        assert result["status"] == "failed"
        assert task.status == "failed"
        assert task.error_type == "VnpyNotInstalledError"
        assert "vn.py is not installed or cannot be imported" in task.error_message
        assert task.traceback
        assert "VnpyNotInstalledError" in task.traceback


def test_backtest_task_runner_marks_success_without_live_trading_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService

    original_import = importlib.import_module
    forbidden_imports: list[str] = []

    def guarded_import(name: str, package: str | None = None):
        lowered = name.lower()
        if any(token in lowered for token in ("ctp", "tqsdk", "trade_gateway", "live_trading")):
            forbidden_imports.append(name)
            raise AssertionError(f"live trading import is forbidden in backtest runner: {name}")
        return original_import(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded_import)

    SessionLocal = _session_factory()
    adapter = FakeSuccessfulAdapter()
    with SessionLocal() as session:
        task = BacktestService(session).create_task(_valid_config())
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "success"
        assert task.status == "success"
        assert task.error_message is None
        assert adapter.requests[0].strategy_class_path == "tests.test_backtest_service_runner:FakeStrategy"
        assert forbidden_imports == []
        persisted = session.get(BacktestTask, task.id)
        assert persisted is not None
        assert persisted.result_payload["normalized_result"]["engine"] == "vnpy_cta_backtesting"
        assert persisted.result_payload["persistence_status"] == "backtest_result_v1_summary_trades"
        assert persisted.result_payload["derived_curve_source"] == "trades"
        assert "equity_curve" not in persisted.result_payload["normalized_result"]
        assert "drawdown_curve" not in persisted.result_payload["normalized_result"]
        report = session.get(BacktestReportModel, persisted.result_payload["report_id"])
        assert report is not None
        assert report.engine_type == "vnpy"
        assert report.strategy_code == "fake_strategy"
        assert report.strategy_version == "test-v1"
        assert report.summary["report_metadata"] == {
            "engine_type": "vnpy",
            "data_source": "local_parquet",
            "data_role": "primary",
            "quality_status": "passed",
            "strategy_code": "fake_strategy",
            "strategy_version": "test-v1",
            "symbol": "rb",
            "contract": "rb2405",
            "vt_symbol": "rb2405.SHFE",
            "exchange": "SHFE",
            "interval": "1m",
            "start": "2024-01-02T09:00:00+00:00",
            "end": "2024-01-02T15:00:00+00:00",
            "initial_capital": 100000.0,
            "rate": 0.0001,
            "slippage": 1.0,
            "size": 10,
            "pricetick": 1.0,
            "execution_timing": "next_bar_open",
            "auxiliary_intervals": [],
            "task_no": persisted.task_no,
        }
        assert report.consistency_hash
        assert report.summary["consistency_hash"] == report.consistency_hash
        assert len(report.trades) == 1
        assert len(report.order_rows) == 1
        assert report.trades[0].sequence == 1
        assert report.trades[0].exchange == "SHFE"
        assert report.trades[0].research_contract == "rb2405"
        assert report.trades[0].timeframe == "1m"
        assert report.trades[0].raw_payload["tradeid"] == "T-1"


def test_backtest_task_runner_passes_and_redacts_auxiliary_bar_paths() -> None:
    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService

    SessionLocal = _session_factory()
    adapter = FakeSuccessfulAdapter()
    with SessionLocal() as session:
        task = BacktestService(session).create_task(_valid_config(auxiliary_bar_data_paths={"1d": "/Volumes/local/jm_MAIN_1d.parquet"}))
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "success"
        assert adapter.requests[0].auxiliary_bar_data_paths == {"1d": "/Volumes/local/jm_MAIN_1d.parquet"}
        assert task.request_payload["auxiliary_bar_data_paths"] == {"1d": "<local_standard_parquet_redacted>"}
        assert task.vnpy_setting_json["auxiliary_bar_data_paths"] == {"1d": "<local_standard_parquet_redacted>"}
        report = session.get(BacktestReportModel, task.result_payload["report_id"])
        assert report is not None
        assert report.summary["report_metadata"]["auxiliary_intervals"] == ["1d"]


def test_backtest_task_runner_persists_real_vnpy_fixture_result_to_report_tables() -> None:
    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService

    fixture_path = fixture_generator.write_fixture(fixture_generator.DEFAULT_FIXTURE_PATH)
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        task = BacktestService(session).create_task(
            _valid_config(
                interval="60m",
                start=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                end=datetime(2024, 1, 6, 8, 0, tzinfo=UTC),
                strategy_class_path="tests.test_vnpy_integration:FixtureRoundTripStrategy",
                strategy_code="fixture_round_trip",
                strategy_version="test-vnpy",
                strategy_parameters={},
                bar_data_path=str(fixture_path),
            )
        )
        session.commit()

        result = BacktestTaskRunner(session).run(task.id)
        session.refresh(task)

        assert result["status"] == "success"
        assert task.status == "success"
        report = session.get(BacktestReportModel, task.result_payload["report_id"])
        assert report is not None
        assert report.status == "success"
        assert report.engine_type == "vnpy"
        assert report.data_source == "local_parquet"
        assert report.data_role == "primary"
        assert report.strategy_code == "fixture_round_trip"
        assert task.request_payload["bar_data_path"] == "<local_standard_parquet_redacted>"
        assert task.vnpy_setting_json["bar_data_path"] == "<local_standard_parquet_redacted>"
        assert report.summary["report_metadata"]["vt_symbol"] == "rb2405.SHFE"
        assert report.summary["report_metadata"]["start"] == "2024-01-02T09:00:00+00:00"
        assert report.summary["report_metadata"]["end"] == "2024-01-06T08:00:00+00:00"
        assert report.summary["report_metadata"]["initial_capital"] == 100000.0
        assert report.summary["report_metadata"]["rate"] == 0.0001
        assert report.summary["report_metadata"]["slippage"] == 1.0
        assert report.summary["report_metadata"]["size"] == 10
        assert report.summary["report_metadata"]["pricetick"] == 1.0
        assert report.summary["report_metadata"]["auxiliary_intervals"] == []

        trades = session.query(BacktestTradeModel).filter_by(report_id=report.id).all()
        orders = session.query(BacktestOrderModel).filter_by(report_id=report.id).all()

        assert len(trades) == len(result["result"]["trades"])
        assert len(trades) >= 1
        assert len(orders) == len(result["result"]["orders"])
        assert orders[0].raw_payload["orderid"]
        assert task.result_payload["derived_curve_source"] == "trades"
        assert "equity_curve" not in task.result_payload["normalized_result"]
        assert "drawdown_curve" not in task.result_payload["normalized_result"]


def test_persist_result_recomputes_report_metrics_from_trades_and_equity_curve() -> None:
    from app.backtest.service import BacktestService

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        service = BacktestService(session)
        task = service.create_task(
            _valid_config(
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 12, 31, tzinfo=UTC),
            )
        )
        service.persist_result(
            task,
            {
                "summary": {
                    "capital": 100000,
                    "end_balance": 1,
                    "annual_return": 0.0,
                    "max_drawdown": 999.0,
                    "max_drawdown_amount": 999.0,
                    "max_drawdown_pct": 9.99,
                    "total_commission": 999.0,
                    "total_slippage": 999.0,
                    "max_margin_required": 999.0,
                    "max_margin_usage_pct": 9.99,
                },
                "trades": [
                    {
                        "tradeid": "T-WIN",
                        "direction": "long",
                        "entry_datetime": "2024-02-01T09:00:00Z",
                        "exit_datetime": "2024-02-01T10:00:00Z",
                        "entry_price": 100,
                        "exit_price": 120,
                        "net_pnl": 20000,
                        "commission": 12,
                        "slippage": 5,
                        "margin_required": 20000,
                        "holding_bars": 4,
                        "rollover_forced_exit": True,
                    },
                    {
                        "tradeid": "T-LOSS",
                        "direction": "long",
                        "entry_datetime": "2024-03-01T09:00:00Z",
                        "exit_datetime": "2024-03-01T10:00:00Z",
                        "entry_price": 100,
                        "exit_price": 95,
                        "net_pnl": -5000,
                        "commission": 8,
                        "slippage": 7,
                        "margin_required": 30000,
                        "holding_bars": 8,
                        "delivery_risk_exit": True,
                    },
                ],
                "equity_curve": [
                    {"datetime": "2024-01-01T09:00:00Z", "equity": 100000},
                    {"datetime": "2024-02-01T10:00:00Z", "equity": 120000},
                    {"datetime": "2024-03-01T10:00:00Z", "equity": 108000},
                    {"datetime": "2024-12-31T09:00:00Z", "equity": 115000},
                ],
                "drawdown_curve": [{"datetime": "2024-03-01T10:00:00Z", "drawdown": 12, "drawdown_pct": 0.0001}],
            },
        )
        session.commit()

        report = session.query(BacktestReportModel).filter_by(task_id=task.id).one()
        trades = session.query(BacktestTradeModel).filter_by(report_id=report.id).all()

        assert report.final_equity == pytest.approx(115000.0)
        assert report.total_return == pytest.approx(0.15)
        assert report.annual_return == pytest.approx(0.15)
        assert report.max_drawdown_amount == pytest.approx(5000.0)
        assert report.max_drawdown_pct == pytest.approx(5000.0 / 120000.0)
        assert report.max_drawdown == pytest.approx(report.max_drawdown_pct)
        assert report.total_commission == pytest.approx(20.0)
        assert report.total_slippage == pytest.approx(12.0)
        assert report.max_margin_required == pytest.approx(30000.0)
        assert report.max_margin_usage_pct == pytest.approx(0.3)
        assert report.win_rate == pytest.approx(0.5)
        assert report.profit_loss_ratio == pytest.approx(4.0)
        assert report.max_consecutive_losses == 1
        assert report.rollover_exit_count == 1
        assert report.delivery_risk_exit_count == 1
        assert report.summary["average_hold_bars"] == pytest.approx(6.0)
        assert report.summary["metric_units"]["max_drawdown_pct"] == "ratio"
        assert report.total_commission == pytest.approx(sum(trade.commission for trade in trades))
        assert report.total_slippage == pytest.approx(sum(trade.slippage for trade in trades))
        assert report.max_margin_required == pytest.approx(max(trade.margin_required or 0 for trade in trades))
        assert report.consistency_hash
        assert "equity_curve" not in task.result_payload["normalized_result"]
