from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.backtest import BacktestReportModel, BacktestTask
from app.models.data_center import MarketDataFile
from app.schemas.backtest import BacktestDataRole, BacktestEngineType, VnpyBacktestTaskCreate


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_vnpy_task_schema_defaults_to_primary_research_false() -> None:
    request = VnpyBacktestTaskCreate(vnpy_strategy_class="pkg.module:Strategy")

    assert request.engine_type is BacktestEngineType.VNPY
    assert request.data_source == "local_parquet"
    assert request.data_role is BacktestDataRole.PRIMARY
    assert request.research_only is False
    assert request.vnpy_setting_json == {}
    assert request.request_payload == {}


def test_validation_and_legacy_reference_require_research_only() -> None:
    with pytest.raises(ValidationError, match="research_only=true"):
        VnpyBacktestTaskCreate(vnpy_strategy_class="pkg.module:Strategy", data_role=BacktestDataRole.VALIDATION)

    with pytest.raises(ValidationError, match="research_only=true"):
        VnpyBacktestTaskCreate(vnpy_strategy_class="pkg.module:Strategy", data_role=BacktestDataRole.LEGACY_REFERENCE)

    request = VnpyBacktestTaskCreate(
        vnpy_strategy_class="pkg.module:Strategy",
        data_role=BacktestDataRole.LEGACY_REFERENCE,
        research_only=True,
    )

    assert request.research_only is True


def test_models_expose_vnpy_backtest_and_data_role_columns() -> None:
    engine, SessionLocal = _session_factory()
    inspector = inspect(engine)

    task_columns = {column["name"] for column in inspector.get_columns("backtest_tasks")}
    report_columns = {column["name"] for column in inspector.get_columns("backtest_reports")}
    market_file_columns = {column["name"] for column in inspector.get_columns("market_data_files")}

    assert {"engine_type", "vnpy_strategy_class", "vnpy_setting_json", "data_source", "data_role", "research_only"} <= task_columns
    assert {
        "engine_type",
        "strategy_code",
        "data_source",
        "data_role",
        "research_only",
        "initial_capital",
        "final_equity",
        "total_return",
        "annual_return",
        "max_drawdown",
        "win_rate",
        "profit_loss_ratio",
        "trade_count",
        "max_consecutive_losses",
        "total_commission",
        "total_slippage",
    } <= report_columns
    assert "data_role" in market_file_columns

    with SessionLocal() as session:
        task = BacktestTask(task_no="BT-VNPY-001", engine_type="vnpy", data_source="local_parquet", data_role="primary")
        session.add(task)
        session.flush()
        report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no="RPT-VNPY-001",
            template_name="default",
            engine_type="vnpy",
            strategy_code="su_bing_ema21",
            symbol="rb",
            contract="rb2405",
            period="1m",
            data_source="local_parquet",
            data_role="primary",
            initial_capital=100000.0,
            final_equity=101000.0,
            total_return=0.01,
            annual_return=0.1,
            max_drawdown=0.02,
            win_rate=0.5,
            profit_loss_ratio=1.5,
            trade_count=2,
            max_consecutive_losses=1,
            total_commission=10.0,
            total_slippage=2.0,
        )
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="rb",
            contract_code="rb2405",
            period="1m",
            start_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            end_time=datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
            file_path="parquet/canonical/bars/provider=rqdata/test.parquet",
            data_role="primary",
            quality_status="passed",
        )
        session.add_all([report, market_file])
        session.commit()

        assert report.engine_type == "vnpy"
        assert report.trade_count == 2
        assert market_file.data_role == "primary"
