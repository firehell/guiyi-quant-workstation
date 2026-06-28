from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.equity_curve_generator import generate_equity_curve
from app.db.base import Base
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_all_backtest_reports_are_consistent() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reports(session)
        report_ids = list(session.scalars(select(BacktestReportModel.id).order_by(BacktestReportModel.id)))

        assert len(report_ids) == 3
        for report_id in report_ids:
            report = session.get(BacktestReportModel, report_id)
            assert report is not None
            _assert_report_consistent(report)


def test_consistency_check_detects_incorrect_final_equity() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reports(session)
        report = session.scalars(select(BacktestReportModel).order_by(BacktestReportModel.id)).first()
        assert report is not None
        report.summary = {**report.summary, "final_equity": report.final_equity + 1.0}

        with pytest.raises(AssertionError, match="final_equity"):
            _assert_report_consistent(report)


def test_consistency_check_detects_incorrect_drawdown_summary() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reports(session)
        report = session.scalars(select(BacktestReportModel).order_by(BacktestReportModel.id)).first()
        assert report is not None
        report.summary = {**report.summary, "max_drawdown_amount": report.max_drawdown_amount + 1.0}

        with pytest.raises(AssertionError, match="max_drawdown_amount"):
            _assert_report_consistent(report)


def _seed_reports(session: Session) -> None:
    task = BacktestTask(
        task_no="BT-CONSISTENCY-001",
        engine_type="vnpy",
        status="success",
        data_source="local_parquet",
        data_role="primary",
    )
    session.add(task)
    session.flush()

    _add_report(
        session,
        task=task,
        report_no="RPT-CONSISTENCY-MULTI",
        initial_capital=100000.0,
        trades=[
            _trade_fact("T-2", sequence=2, close_offset_minutes=60, gross_pnl=-596.0, commission=2.0, slippage=2.0),
            _trade_fact("T-1", sequence=1, close_offset_minutes=45, gross_pnl=1006.0, commission=4.0, slippage=2.0),
            _trade_fact("T-4", sequence=3, close_offset_minutes=90, gross_pnl=500.0, commission=0.0, slippage=0.0),
            _trade_fact("T-3", sequence=1, close_offset_minutes=60, gross_pnl=-197.0, commission=2.0, slippage=1.0),
        ],
    )
    _add_report(
        session,
        task=task,
        report_no="RPT-CONSISTENCY-EMPTY",
        initial_capital=50000.0,
        trades=[],
    )
    _add_report(
        session,
        task=task,
        report_no="RPT-CONSISTENCY-SHUFFLED",
        initial_capital=200000.0,
        trades=[
            _trade_fact("B", sequence=2, close_offset_minutes=75, gross_pnl=2006.0, commission=4.0, slippage=2.0),
            _trade_fact("C", sequence=1, close_offset_minutes=75, gross_pnl=-1495.0, commission=3.0, slippage=2.0),
            _trade_fact("A", sequence=1, close_offset_minutes=70, gross_pnl=-496.0, commission=2.0, slippage=2.0),
        ],
    )
    session.commit()


def _add_report(
    session: Session,
    *,
    task: BacktestTask,
    report_no: str,
    initial_capital: float,
    trades: list[dict[str, Any]],
) -> BacktestReportModel:
    summary = _summary_from_trades(trades, initial_capital=initial_capital)
    report = BacktestReportModel(
        task_id=task.id,
        task_no=task.task_no,
        report_no=report_no,
        template_name="consistency_test",
        engine_type=task.engine_type,
        strategy_code="consistency_test_strategy",
        symbol="jm",
        contract="JM2405",
        period="15m",
        data_source="local_parquet",
        data_role="primary",
        status="success",
        consistency_hash="0" * 64,
        summary=summary,
        warnings=[],
    )
    session.add(report)
    session.flush()

    for index, trade in enumerate(trades, start=1):
        session.add(_trade_model(report_id=report.id, index=index, trade=trade))

    return report


def _assert_report_consistent(report: BacktestReportModel) -> None:
    trades = list(report.trades)
    trade_mappings = [_trade_curve_mapping(trade) for trade in trades]
    equity_curve = generate_equity_curve(trade_mappings, initial_capital=report.initial_capital)
    drawdown_result = generate_drawdown_curve(equity_curve)
    drawdown_curve = drawdown_result["drawdown_curve"]

    total_net_pnl = sum(trade.net_pnl for trade in trades)
    expected_final_equity = report.initial_capital + total_net_pnl
    assert report.final_equity == pytest.approx(expected_final_equity), "final_equity must match initial_capital + sum(trades.net_pnl)"

    assert equity_curve[0]["source"] == "initial_capital"
    assert equity_curve[0]["equity"] == pytest.approx(report.initial_capital)
    assert len(equity_curve) == len(trades) + 1
    assert equity_curve[-1]["equity"] == pytest.approx(report.final_equity)

    expected_trade_order = [
        trade.trade_no for trade in sorted(trades, key=lambda item: (item.close_time, item.sequence, item.trade_no))
    ]
    assert [point.get("trade_id") for point in equity_curve[1:]] == expected_trade_order

    max_drawdown_amount = max((point["drawdown"] for point in drawdown_curve), default=0.0)
    max_drawdown_pct = max((point["drawdown_pct"] for point in drawdown_curve), default=0.0)
    assert drawdown_result["max_drawdown_amount"] == pytest.approx(max_drawdown_amount)
    assert drawdown_result["max_drawdown_pct"] == pytest.approx(max_drawdown_pct)
    assert drawdown_result["max_drawdown"] == pytest.approx(max_drawdown_pct)
    assert report.max_drawdown_amount == pytest.approx(drawdown_result["max_drawdown_amount"]), "max_drawdown_amount must be trade-derived"
    assert report.max_drawdown_pct == pytest.approx(drawdown_result["max_drawdown_pct"]), "max_drawdown_pct must be trade-derived"
    assert report.max_drawdown == pytest.approx(drawdown_result["max_drawdown"]), "max_drawdown must equal max_drawdown_pct"


def _summary_from_trades(trades: list[dict[str, Any]], *, initial_capital: float) -> dict[str, Any]:
    equity_curve = generate_equity_curve(trades, initial_capital=initial_capital)
    drawdown_result = generate_drawdown_curve(equity_curve)
    total_net_pnl = sum(float(trade["net_pnl"]) for trade in trades)
    total_commission = sum(float(trade["commission"]) for trade in trades)
    total_slippage = sum(float(trade["slippage"]) for trade in trades)
    final_equity = initial_capital + total_net_pnl
    return {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_net_pnl": total_net_pnl,
        "total_return": total_net_pnl / initial_capital if initial_capital else 0.0,
        "trade_count": len(trades),
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "max_drawdown": drawdown_result["max_drawdown"],
        "max_drawdown_amount": drawdown_result["max_drawdown_amount"],
        "max_drawdown_pct": drawdown_result["max_drawdown_pct"],
    }


def _trade_fact(
    trade_no: str,
    *,
    sequence: int,
    close_offset_minutes: int,
    gross_pnl: float,
    commission: float,
    slippage: float,
) -> dict[str, Any]:
    close_time = datetime(2024, 1, 2, 9, 0, tzinfo=UTC) + timedelta(minutes=close_offset_minutes)
    return {
        "trade_no": trade_no,
        "trade_id": trade_no,
        "sequence": sequence,
        "exit_time": close_time,
        "gross_pnl": gross_pnl,
        "commission": commission,
        "slippage": slippage,
        "net_pnl": gross_pnl - commission - slippage,
    }


def _trade_model(*, report_id: int, index: int, trade: dict[str, Any]) -> BacktestTradeModel:
    close_time = trade["exit_time"]
    open_time = close_time - timedelta(minutes=15)
    return BacktestTradeModel(
        report_id=report_id,
        trade_no=trade["trade_no"],
        sequence=trade["sequence"],
        symbol="jm",
        exchange="DCE",
        research_contract="jm.MAIN",
        contract="JM2405",
        timeframe="15m",
        entry_contract="JM2405",
        exit_contract="JM2405",
        direction="long",
        open_time=open_time,
        open_price=1800.0 + index,
        close_time=close_time,
        close_price=1810.0 + index,
        volume=1,
        turnover=(1810.0 + index) * 60,
        contract_multiplier=60,
        price_tick=0.5,
        commission=trade["commission"],
        slippage=trade["slippage"],
        margin_ratio=0.13,
        margin_required=(1810.0 + index) * 60 * 0.13,
        gross_pnl=trade["gross_pnl"],
        net_pnl=trade["net_pnl"],
        return_pct=trade["net_pnl"] / ((1800.0 + index) * 60),
        holding_bars=1,
        entry_reason="consistency_test",
        exit_reason="consistency_test_exit",
        raw_payload={"test_case": "backtest_consistency"},
    )


def _trade_curve_mapping(trade: BacktestTradeModel) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_no,
        "trade_no": trade.trade_no,
        "sequence": trade.sequence,
        "exit_time": trade.close_time,
        "gross_pnl": trade.gross_pnl,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "net_pnl": trade.net_pnl,
    }
