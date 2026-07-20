from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.service import BacktestService
from app.backtest.trust_audit import build_backtest_trust_audit
from app.db.base import Base
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTradeModel
from app.schemas.backtest import BacktestTaskConfig


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "stage13g_repair_report14_lineage.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("stage13g_repair_report14_lineage", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
assert SCRIPT_SPEC.loader is not None
stage13g = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(stage13g)


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
        "symbol": "jm.MAIN",
        "exchange": "DCE",
        "interval": "15m",
        "start": datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        "end": datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
        "strategy_class_path": "tests.test_stage13g_report_lineage_repair:FakeStrategy",
        "strategy_code": "jm_v1b_daily_direction_fast_entry",
        "strategy_version": "v1b.0",
        "strategy_parameters": {},
        "rate": 0.0001,
        "slippage": 1,
        "size": 60,
        "pricetick": 0.5,
        "capital": 100000,
        "data_source": "local_parquet",
        "data_version": "fixture-v1",
        "quality_status": "passed",
        "research_only": True,
    }
    payload.update(overrides)
    return BacktestTaskConfig(**payload)


class FakeStrategy:
    pass


def _persist_partial_lineage_report(session) -> BacktestReportModel:
    service = BacktestService(session)
    task = service.create_task(_valid_config())
    service.persist_result(
        task,
        {
            "summary": {"capital": 100000},
            "trades": [
                {
                    "tradeid": "T-PLANNED-EXIT",
                    "symbol": "jm.MAIN",
                    "contract": "JM2405",
                    "entry_contract": "JM2405",
                    "exit_contract": "JM2405",
                    "direction": "long",
                    "signal_datetime": "2024-01-02T09:00:00Z",
                    "entry_signal_time": "2024-01-02T09:00:00Z",
                    "fill_datetime": "2024-01-02T09:15:00Z",
                    "entry_datetime": "2024-01-02T09:15:00Z",
                    "exit_datetime": "2024-01-02T10:00:00Z",
                    "entry_price": 100,
                    "exit_price": 105,
                    "volume": 1,
                    "contract_multiplier": 60,
                    "price_tick": 0.5,
                    "gross_pnl": 300,
                    "commission": 12,
                    "slippage": 30,
                    "fee_rule_source": {"source": "fixture"},
                    "main_contract_source": {"source": "fixture"},
                    "net_pnl": 258,
                    "holding_bars": 4,
                    "exit_reason": "max_hold_bars_exit",
                },
                {
                    "tradeid": "T-DIRECT-EXIT",
                    "symbol": "jm.MAIN",
                    "contract": "JM2405",
                    "entry_contract": "JM2405",
                    "exit_contract": "JM2405",
                    "direction": "short",
                    "signal_datetime": "2024-01-02T10:15:00Z",
                    "entry_signal_time": "2024-01-02T10:15:00Z",
                    "fill_datetime": "2024-01-02T10:30:00Z",
                    "entry_datetime": "2024-01-02T10:30:00Z",
                    "exit_datetime": "2024-01-02T10:45:00Z",
                    "entry_price": 104,
                    "exit_price": 103,
                    "volume": 1,
                    "contract_multiplier": 60,
                    "price_tick": 0.5,
                    "gross_pnl": 60,
                    "commission": 12,
                    "slippage": 30,
                    "fee_rule_source": {"source": "fixture"},
                    "main_contract_source": {"source": "fixture"},
                    "net_pnl": 18,
                    "holding_bars": 1,
                    "exit_reason": "stop_loss_atr_or_structure",
                },
            ],
            "orders": [
                {
                    "orderid": "O-ENTRY-1",
                    "symbol": "jm.MAIN",
                    "contract": "JM2405",
                    "direction": "多",
                    "offset": "开",
                    "datetime": "2024-01-02T09:00:00Z",
                    "price": 100,
                    "volume": 1,
                    "traded": 1,
                },
                {
                    "orderid": "O-EXIT-1",
                    "symbol": "jm.MAIN",
                    "contract": "JM2405",
                    "direction": "空",
                    "offset": "平",
                    "datetime": "2024-01-02T09:45:00Z",
                    "price": 105,
                    "volume": 1,
                    "traded": 1,
                },
                {
                    "orderid": "O-ENTRY-2",
                    "symbol": "jm.MAIN",
                    "contract": "JM2405",
                    "direction": "空",
                    "offset": "开",
                    "datetime": "2024-01-02T10:15:00Z",
                    "price": 104,
                    "volume": 1,
                    "traded": 1,
                },
            ],
        },
    )
    session.commit()
    report = session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)).one()
    _downgrade_to_stage13f_partial_lineage(session, report.id)
    session.commit()
    return report


def _downgrade_to_stage13f_partial_lineage(session, report_id: int) -> None:
    report = session.get(BacktestReportModel, report_id)
    assert report is not None
    trades = list(session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report_id)))
    orders = list(session.scalars(select(BacktestOrderModel).where(BacktestOrderModel.report_id == report_id)))
    for trade in trades:
        trade.entry_order_no = None
        trade.exit_order_no = None
        trade.exit_signal_source = None
        trade.lineage_status = "partial"
        raw = dict(trade.raw_payload or {})
        raw.pop("entry_order_no", None)
        raw.pop("exit_order_no", None)
        raw.pop("exit_signal_source", None)
        raw["lineage_status"] = "partial"
        trade.raw_payload = raw
    for order in orders:
        order.trade_no = None
        order.leg = None
        order.lineage_source = "unmapped_vnpy_order"
        order.mapping_status = "missing"
        raw = dict(order.raw_payload or {})
        raw.pop("trade_no", None)
        raw.pop("leg", None)
        raw["lineage_source"] = "unmapped_vnpy_order"
        raw["mapping_status"] = "missing"
        order.raw_payload = raw
    summary = dict(report.summary or {})
    summary["lineage_summary"] = {
        "trade_count": len(trades),
        "order_count": len(orders),
        "mapped_trades": 0,
        "partial_trades": len(trades),
        "missing_trades": 0,
        "ambiguous_trades": 0,
        "mapped_orders": 0,
        "unmapped_orders": len(orders),
        "ambiguous_orders": 0,
        "lineage_sources": ["trade_field"],
    }
    report.summary = summary


def test_stage13g_repair_dry_run_maps_without_writing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_partial_lineage_report(session)

        result = stage13g.repair_report_lineage(session, report_id=report.id, apply=False)
        session.expire_all()
        stored_report = session.get(BacktestReportModel, report.id)

        assert result["mode"] == "dry-run"
        assert result["before"]["partial_trades"] == 2
        assert result["before"]["unmapped_orders"] == 3
        assert result["after"]["mapped_trades"] == 2
        assert result["after"]["mapped_orders"] == 3
        assert result["after"]["partial_trades"] == 0
        assert result["after"]["unmapped_orders"] == 0
        assert stored_report.summary["lineage_summary"]["partial_trades"] == 2


def test_stage13g_repair_apply_requires_confirm() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_partial_lineage_report(session)

        with pytest.raises(ValueError, match="confirmation flag"):
            stage13g.repair_report_lineage(session, report_id=report.id, apply=True, confirm=False)


def test_stage13g_repair_apply_updates_lineage_and_audit_passes() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_partial_lineage_report(session)

        result = stage13g.repair_report_lineage(session, report_id=report.id, apply=True, confirm=True)
        session.commit()
        session.expire_all()
        trades = list(session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id)))
        orders = list(session.scalars(select(BacktestOrderModel).where(BacktestOrderModel.report_id == report.id)))
        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert result["mode"] == "apply"
        assert result["updated_trades"] == 2
        assert result["updated_orders"] == 3
        assert {trade.lineage_status for trade in trades} == {"mapped"}
        assert {order.mapping_status for order in orders} == {"mapped"}
        assert any(trade.exit_signal_source == "strategy_trade_direct_exit" for trade in trades)
        assert audit["audit_status"] == "passed"
        assert audit["checks"]["lineage_mapping"]["status"] == "passed"
