from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel
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


def test_validation_and_legacy_reference_are_inactive_for_new_tasks() -> None:
    with pytest.raises(ValidationError, match="only primary RQData/local parquet data is active"):
        VnpyBacktestTaskCreate(vnpy_strategy_class="pkg.module:Strategy", data_role=BacktestDataRole.VALIDATION)

    with pytest.raises(ValidationError, match="only primary RQData/local parquet data is active"):
        VnpyBacktestTaskCreate(vnpy_strategy_class="pkg.module:Strategy", data_role=BacktestDataRole.LEGACY_REFERENCE)

    with pytest.raises(ValidationError, match="only primary RQData/local parquet data is active"):
        VnpyBacktestTaskCreate(
            vnpy_strategy_class="pkg.module:Strategy",
            data_role=BacktestDataRole.LEGACY_REFERENCE,
            research_only=True,
        )


def test_models_expose_vnpy_backtest_and_data_role_columns() -> None:
    engine, SessionLocal = _session_factory()
    inspector = inspect(engine)

    task_columns = {column["name"] for column in inspector.get_columns("backtest_tasks")}
    report_columns = {column["name"] for column in inspector.get_columns("backtest_reports")}
    trade_columns = {column["name"] for column in inspector.get_columns("backtest_trades")}
    market_file_columns = {column["name"] for column in inspector.get_columns("market_data_files")}

    assert {"engine_type", "vnpy_strategy_class", "vnpy_setting_json", "data_source", "data_role", "research_only"} <= task_columns
    assert {
        "engine_type",
        "strategy_code",
        "data_source",
        "data_role",
        "research_only",
        "summary",
        "warnings",
        "consistency_hash",
    } <= report_columns
    assert {"equity_curve", "drawdown_curve", "orders", "fills"} & report_columns == set()
    assert {
        "sequence",
        "exchange",
        "research_contract",
        "timeframe",
        "entry_signal_time",
        "exit_signal_time",
        "stop_loss_price",
        "entry_contract",
        "exit_contract",
        "entry_contract_month",
        "exit_contract_month",
        "contract_multiplier",
        "price_tick",
        "margin_ratio",
        "margin_required",
        "parameter_source",
        "fee_rule_source",
        "main_contract_source",
        "rollover_forced_exit",
        "delivery_risk_exit",
        "rollover_reason",
    } <= trade_columns
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
            consistency_hash="a" * 64,
            summary={
                "initial_capital": 100000.0,
                "final_equity": 101000.0,
                "total_return": 0.01,
                "annual_return": 0.1,
                "max_drawdown": 0.02,
                "max_drawdown_amount": 2000.0,
                "max_drawdown_pct": 0.02,
                "win_rate": 0.5,
                "profit_loss_ratio": 1.5,
                "trade_count": 2,
                "max_consecutive_losses": 1,
                "total_commission": 10.0,
                "total_slippage": 2.0,
                "max_margin_required": 42000.0,
                "max_margin_usage_pct": 0.42,
                "rollover_exit_count": 1,
                "delivery_risk_exit_count": 1,
            },
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
        session.flush()
        trade = BacktestTradeModel(
            report_id=report.id,
            trade_no="T-REAL-001",
            sequence=1,
            symbol="jm",
            exchange="DCE",
            research_contract="jm.MAIN",
            contract="JM2405",
            timeframe="15m",
            entry_contract="JM2405",
            exit_contract="JM2409",
            entry_contract_month="2024-05",
            exit_contract_month="2024-09",
            direction="long",
            open_time=datetime(2024, 4, 29, 9, 0, tzinfo=UTC),
            open_price=1800.0,
            close_time=datetime(2024, 5, 6, 9, 0, tzinfo=UTC),
            close_price=1820.0,
            volume=1,
            turnover=108000.0,
            contract_multiplier=60,
            price_tick=0.5,
            commission=16.2,
            slippage=30.0,
            margin_ratio=0.13,
            margin_required=14040.0,
            parameter_source="futures_trading_parameters",
            fee_rule_source={"source": "futures_trading_parameters"},
            main_contract_source={"provider": "rqdata", "data_version": "test-v1"},
            rollover_forced_exit=True,
            delivery_risk_exit=True,
            rollover_reason="delivery_month_guard",
            gross_pnl=1200.0,
            net_pnl=1153.8,
            return_pct=0.011538,
            holding_bars=10,
            entry_reason="test",
            exit_reason="delivery_risk_exit",
            raw_payload={"last_allowed_holding_date": "2024-04-30"},
        )
        session.add(trade)
        session.commit()

        assert report.engine_type == "vnpy"
        assert report.consistency_hash == "a" * 64
        assert report.trade_count == 2
        assert report.max_drawdown_amount == 2000.0
        assert report.max_drawdown_pct == 0.02
        assert report.max_margin_required == 42000.0
        assert report.rollover_exit_count == 1
        assert trade.entry_contract == "JM2405"
        assert trade.sequence == 1
        assert trade.exchange == "DCE"
        assert trade.research_contract == "jm.MAIN"
        assert trade.timeframe == "15m"
        assert trade.exit_contract == "JM2409"
        assert trade.contract_multiplier == 60
        assert trade.margin_required == 14040.0
        assert trade.rollover_forced_exit is True
        assert market_file.data_role == "primary"
