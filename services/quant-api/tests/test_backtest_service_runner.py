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
    BacktestDrawdownCurvePointModel,
    BacktestEquityCurvePointModel,
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
        assert task.traceback in {None, ""}


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
        assert persisted.result_payload["persistence_status"] == "report_detail_tables"
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
            "task_no": persisted.task_no,
        }
        assert len(report.trades) == 1
        assert len(report.order_rows) == 1
        assert len(report.equity_points) == 2
        assert len(report.drawdown_points) == 1
        assert report.trades[0].raw_payload["tradeid"] == "T-1"


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

        trades = session.query(BacktestTradeModel).filter_by(report_id=report.id).all()
        orders = session.query(BacktestOrderModel).filter_by(report_id=report.id).all()
        equity = session.query(BacktestEquityCurvePointModel).filter_by(report_id=report.id).all()
        drawdown = session.query(BacktestDrawdownCurvePointModel).filter_by(report_id=report.id).all()

        assert len(trades) == len(result["result"]["trades"])
        assert len(trades) >= 1
        assert len(orders) == len(result["result"]["orders"])
        assert orders[0].raw_payload["orderid"]
        assert len(equity) == len(result["result"]["equity_curve"])
        assert len(drawdown) == len(result["result"]["drawdown_curve"])
