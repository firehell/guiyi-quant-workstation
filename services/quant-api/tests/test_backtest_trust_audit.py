from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.service import BacktestService
from app.backtest.trust_audit import (
    BacktestTrustAuditError,
    build_backtest_trust_audit,
    render_audit_markdown,
)
from app.db.base import Base
from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.schemas.backtest import BacktestTaskConfig


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
        "strategy_class_path": "tests.test_backtest_trust_audit:FakeStrategy",
        "strategy_code": "trust_fixture",
        "strategy_version": "test-v1",
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
        "bar_data_path": "/Volumes/local/jm_MAIN_15m.parquet",
        "request_payload": {"note": "fixture", "token": "should-not-leak"},
    }
    payload.update(overrides)
    return BacktestTaskConfig(**payload)


class FakeStrategy:
    pass


def _persist_report(session, *, config: BacktestTaskConfig | None = None, result: dict[str, Any] | None = None) -> BacktestReportModel:
    service = BacktestService(session)
    task = service.create_task(config or _valid_config())
    service.persist_result(task, result or _trusted_result())
    session.commit()
    report = session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)).one()
    return report


def _trusted_result() -> dict[str, Any]:
    return {
        "summary": {"capital": 100000},
        "trades": [
            {
                "tradeid": "T-PASS-1",
                "symbol": "jm.MAIN",
                "contract": "JM2405",
                "direction": "long",
                "entry_signal_time": "2024-01-02T09:00:00Z",
                "entry_datetime": "2024-01-02T09:01:00Z",
                "exit_datetime": "2024-01-02T10:00:00Z",
                "entry_price": 100,
                "exit_price": 105,
                "volume": 1,
                "contract_multiplier": 60,
                "price_tick": 0.5,
                "gross_pnl": 300,
                "commission": 12,
                "slippage": 30,
                "net_pnl": 258,
                "margin_required": 10000,
                "holding_bars": 4,
            }
        ],
        "orders": [
            {
                "orderid": "O-PASS-1",
                "symbol": "jm.MAIN",
                "contract": "JM2405",
                "direction": "long",
                "offset": "open",
                "status": "all_traded",
                "price": 100,
                "volume": 1,
                "traded": 1,
                "datetime": "2024-01-02T09:01:00Z",
            },
            {
                "orderid": "O-PASS-2",
                "symbol": "jm.MAIN",
                "contract": "JM2405",
                "direction": "short",
                "offset": "close",
                "status": "all_traded",
                "price": 105,
                "volume": 1,
                "traded": 1,
                "datetime": "2024-01-02T10:00:00Z",
            }
        ],
    }


def test_backtest_trust_audit_passed_fixture_is_readonly_and_sanitized() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(session)
        before_reports = session.scalar(select(func.count(BacktestReportModel.id)))
        before_trades = session.scalar(select(func.count(BacktestTradeModel.id)))

        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert audit["audit_status"] == "passed"
        assert audit["readonly"] is True
        assert audit["would_write_db"] is False
        assert audit["would_run_rqdata"] is False
        assert audit["would_run_backtest"] is False
        assert audit["checks"]["data_lineage"]["status"] == "passed"
        assert audit["checks"]["equity_consistency"]["status"] == "passed"
        assert audit["checks"]["sensitive_output"]["status"] == "passed"
        assert session.scalar(select(func.count(BacktestReportModel.id))) == before_reports
        assert session.scalar(select(func.count(BacktestTradeModel.id))) == before_trades

        encoded = json.dumps(audit, ensure_ascii=False, sort_keys=True, default=str)
        assert "/Volumes/" not in encoded
        assert "/Users/" not in encoded
        assert "should-not-leak" not in encoded
        assert "token" not in encoded.lower()


def test_backtest_trust_audit_warns_when_execution_and_costs_are_not_fully_confirmed() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(
            session,
            result={
                "summary": {"capital": 100000},
                "trades": [
                    {
                        "tradeid": "T-WARN-1",
                        "symbol": "jm.MAIN",
                        "direction": "long",
                        "entry_datetime": "2024-01-02T09:01:00Z",
                        "exit_datetime": "2024-01-02T10:00:00Z",
                        "entry_price": 100,
                        "exit_price": 101,
                        "volume": 1,
                        "gross_pnl": 60,
                        "commission": 0,
                        "slippage": 0,
                        "net_pnl": 60,
                    }
                ],
                "orders": [],
            },
        )
        metadata = dict(report.summary["report_metadata"])
        metadata.pop("execution_timing")
        report.summary = {**report.summary, "report_metadata": metadata}
        session.commit()

        audit = build_backtest_trust_audit(session, task_no=report.task_no)

        assert audit["audit_status"] == "warning"
        assert audit["checks"]["execution_policy"]["status"] == "warning"
        assert audit["checks"]["fee_slippage"]["status"] == "warning"
        assert audit["checks"]["trade_order_consistency"]["status"] == "warning"
        assert any("entry_signal_time" in warning for warning in audit["warnings"])
        assert any("commission" in warning for warning in audit["warnings"])


def test_backtest_trust_audit_accepts_strategy_event_lineage_without_order_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(
            session,
            result={
                "summary": {"capital": 100000},
                "trades": [
                    {
                        "tradeid": "T-EVENT-1",
                        "symbol": "jm.MAIN",
                        "contract": "JM2405",
                        "direction": "long",
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
                        "net_pnl": 258,
                        "holding_bars": 3,
                    }
                ],
                "strategy_execution_events": [
                    {
                        "action": "open_long",
                        "signal_datetime": "2024-01-02T09:00:00Z",
                        "fill_datetime": "2024-01-02T09:15:00Z",
                    }
                ],
                "orders": [],
            },
        )

        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert audit["audit_status"] == "passed"
        assert audit["checks"]["lineage_mapping"]["status"] == "passed"
        assert audit["checks"]["trade_order_consistency"]["status"] == "passed"
        assert audit["checks"]["lineage_mapping"]["details"]["lineage_summary"]["mapped_trades"] == 1


def test_backtest_trust_audit_warns_for_unmapped_order_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(
            session,
            result={
                "summary": {"capital": 100000},
                "trades": [
                    {
                        "tradeid": "T-ORDER-WARN-1",
                        "symbol": "jm.MAIN",
                        "contract": "JM2405",
                        "direction": "long",
                        "entry_signal_time": "2024-01-02T09:00:00Z",
                        "entry_datetime": "2024-01-02T09:15:00Z",
                        "exit_datetime": "2024-01-02T10:00:00Z",
                        "entry_price": 100,
                        "exit_price": 101,
                        "volume": 1,
                        "contract_multiplier": 60,
                        "price_tick": 0.5,
                        "gross_pnl": 60,
                        "commission": 12,
                        "slippage": 30,
                        "net_pnl": 18,
                    }
                ],
                "orders": [
                    {
                        "orderid": "O-UNMAPPED-1",
                        "symbol": "jm.MAIN",
                        "direction": "long",
                        "offset": "open",
                        "datetime": "2024-01-02T09:30:00Z",
                        "price": 100,
                        "volume": 1,
                        "traded": 1,
                    }
                ],
            },
        )

        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert audit["audit_status"] == "warning"
        assert audit["checks"]["lineage_mapping"]["status"] == "warning"
        assert any("mapping_status" in warning for warning in audit["warnings"])


def test_backtest_trust_audit_fails_when_fill_is_not_after_entry_signal() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(
            session,
            result={
                "summary": {"capital": 100000},
                "trades": [
                    {
                        "tradeid": "T-BAD-TIMING-1",
                        "symbol": "jm.MAIN",
                        "contract": "JM2405",
                        "direction": "long",
                        "entry_signal_time": "2024-01-02T09:15:00Z",
                        "entry_datetime": "2024-01-02T09:15:00Z",
                        "exit_datetime": "2024-01-02T10:00:00Z",
                        "entry_price": 100,
                        "exit_price": 101,
                        "volume": 1,
                        "contract_multiplier": 60,
                        "price_tick": 0.5,
                        "gross_pnl": 60,
                        "commission": 12,
                        "slippage": 30,
                        "net_pnl": 18,
                    }
                ],
                "orders": [],
            },
        )

        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert audit["audit_status"] == "failed"
        assert audit["checks"]["execution_policy"]["status"] == "failed"
        assert any("open_time must be after entry_signal_time" in reason for reason in audit["blocked_reasons"])


def test_backtest_trust_audit_fails_for_inactive_or_failed_data_lineage() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(session)
        report.data_source = "legacy_reference"
        report.data_role = "validation"
        report.quality_status = {"status": "failed"}
        session.commit()

        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert audit["audit_status"] == "failed"
        assert audit["checks"]["data_lineage"]["status"] == "failed"
        assert any("data_source" in reason for reason in audit["blocked_reasons"])
        assert any("data_role" in reason for reason in audit["blocked_reasons"])
        assert any("quality_status" in reason for reason in audit["blocked_reasons"])


def test_backtest_trust_audit_reports_missing_report_as_clear_error() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        with pytest.raises(BacktestTrustAuditError, match="backtest report not found"):
            build_backtest_trust_audit(session, report_id=999)


def test_backtest_trust_audit_markdown_renderer_includes_check_statuses() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = _persist_report(session)
        audit = build_backtest_trust_audit(session, report_id=report.id)

    markdown = render_audit_markdown(audit)

    assert "Backtest Trust Audit" in markdown
    assert "audit_status: passed" in markdown
    assert "data_lineage: passed" in markdown
