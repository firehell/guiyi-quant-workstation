from __future__ import annotations

from datetime import UTC, datetime
import importlib
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.backtest import BacktestTask
from app.schemas.backtest import BacktestDataRole, BacktestEngineType, BacktestTaskConfig
from app.vnpy_integration.errors import VnpyNotInstalledError


class FakeSuccessfulAdapter:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "prepared",
            "statistics": {"total_return": 0.01, "max_drawdown": 0.02},
            "trades": [],
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
