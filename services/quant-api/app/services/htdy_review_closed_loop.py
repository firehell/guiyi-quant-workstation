from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.backtest.htdy_trusted_report import packet_hash
from app.backtest.trust_audit import build_backtest_trust_audit
from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.models.review import ReviewNote
from app.services.backtest_validation_context import build_backtest_validation_context
from app.services.review_center import (
    backtest_trade_source_payload,
    create_or_get_backtest_trade_review,
    review_payload,
)
from app.services.review_lineage import load_review_bars


TASK_ID = "HTDY-STRATEGY-REVIEW-CLOSED-LOOP-X506B"
GATE = "STRATEGY_REVIEW_CLOSED_LOOP_READY"
CANDIDATE_REPORT_ID = 15
REPORT14_ID = 14


def choose_max_net_loss_trade(trades: Sequence[Any]) -> Any:
    if not trades:
        raise ValueError("candidate report has no trade to review")
    return min(
        trades,
        key=lambda trade: (
            float(trade.net_pnl),
            trade.close_time,
            int(trade.id),
        ),
    )


def verify_closed_loop_packet(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def build_closed_loop_packet(
    *,
    source_commit: str,
    db_evidence: Mapping[str, Any],
    browser_smoke: Mapping[str, Any],
) -> dict[str, Any]:
    db_ready = (
        db_evidence.get("status") == "passed"
        and (db_evidence.get("review_note") or {}).get("saved_and_reread") is True
        and (db_evidence.get("exact_bars") or {}).get("status") == "passed"
        and (db_evidence.get("timing") or {}).get("status") == "passed"
        and (db_evidence.get("report_invariance") or {}).get("candidate") is True
        and (db_evidence.get("report_invariance") or {}).get("report14") is True
    )
    if not db_ready:
        raise ValueError("review DB evidence is incomplete")
    required_smoke = (
        "validation_context_api",
        "review_deep_link",
        "exact_bars_rendered",
        "trade_markers_rendered",
        "market_chart_round_trip",
        "backtest_round_trip",
        "review_saved_and_reread",
    )
    browser_ready = (
        browser_smoke.get("status") == "passed"
        and all(browser_smoke.get(key) is True for key in required_smoke)
        and browser_smoke.get("console_error_count") == 0
        and bool(browser_smoke.get("screenshot_sha256"))
    )
    if not browser_ready:
        raise ValueError("browser smoke evidence is incomplete")
    packet: dict[str, Any] = {
        "schema_version": "htdy_strategy_review_closed_loop_x506b_v1",
        "task_id": TASK_ID,
        "gate": GATE,
        "status": "completed",
        "source_commit": source_commit,
        "report_id": db_evidence.get("report_id"),
        "candidate_status": "oos_hard_rejected",
        "research_outcome_hint": "rejected_research_candidate",
        "validation_context_hash": db_evidence.get("validation_context_hash"),
        "review_note": deepcopy(db_evidence.get("review_note") or {}),
        "selected_trade": deepcopy(db_evidence.get("selected_trade") or {}),
        "exact_bars": deepcopy(db_evidence.get("exact_bars") or {}),
        "timing": deepcopy(db_evidence.get("timing") or {}),
        "report_invariance": deepcopy(db_evidence.get("report_invariance") or {}),
        "browser_smoke": deepcopy(dict(browser_smoke)),
        "boundaries": {
            "frontend_strategy_recomputed": False,
            "original_report_or_trade_mutated": False,
            "report14_mutated": False,
            "candidate_rejection_flipped": False,
            "canonical_write": "one ReviewNote only",
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def execute_review_note(
    session_factory: Callable[[], Session],
    *,
    repo_root: Path,
    report_id: int = CANDIDATE_REPORT_ID,
) -> dict[str, Any]:
    staged: dict[str, Any]
    with session_factory() as session:
        with session.begin():
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            report = session.get(BacktestReportModel, report_id)
            report14 = session.get(BacktestReportModel, REPORT14_ID)
            if report is None or report14 is None:
                raise ValueError("candidate report or report14 is missing")
            context = build_backtest_validation_context(
                repo_root,
                report_identity=_report_identity(report),
            )
            candidate_before = build_backtest_trust_audit(session, report_id=report_id)
            report14_before = build_backtest_trust_audit(session, report_id=REPORT14_ID)
            if candidate_before.get("audit_status") != "passed" or report14_before.get("audit_status") != "passed":
                raise ValueError("candidate/report14 trust audit failed before ReviewNote write")
            report_hash_before = _model_facts_hash(report)
            report14_hash_before = _model_facts_hash(report14)
            trades = list(
                session.scalars(
                    select(BacktestTradeModel).where(BacktestTradeModel.report_id == report_id)
                )
            )
            trade = choose_max_net_loss_trade(trades)
            trade_hash_before = _model_facts_hash(trade)
            if trade.entry_signal_time is None or trade.open_time <= trade.entry_signal_time:
                raise ValueError("selected trade does not satisfy confirmed signal < next-bar fill")
            existing = session.scalar(
                select(ReviewNote).where(
                    ReviewNote.source_type == "backtest_trade",
                    ReviewNote.source_id == trade.id,
                )
            )
            if existing is not None and (existing.extra or {}).get("stage5_task") != TASK_ID:
                raise ValueError("selected deterministic trade already has an unrelated ReviewNote")
            before_count = int(session.scalar(select(func.count(ReviewNote.id))) or 0)
            note = create_or_get_backtest_trade_review(session, trade.id)
            note.extra = {
                **dict(note.extra or {}),
                "stage5_task": TASK_ID,
                "validation_context_hash": context["context_hash"],
                "review_skip_status": context["review_skip_status"],
                "hard_reject_reason": context["hard_reject_reason"],
                "execution_note": "confirmed-close signal and next-bar-open fill verified from stored trade facts",
            }
            note.lesson = (
                "冻结 OOS hard reject 已由 rolling folds 复现；本复盘保持拒绝，"
                "不修改策略或原始报告事实。"
            )
            session.flush()
            bars_payload = load_review_bars(session, note, project_root=repo_root)
            source = backtest_trade_source_payload(session, trade)
            if source.get("entry_signal_time") != trade.entry_signal_time.isoformat():
                raise ValueError("Review source lost entry_signal_time")
            after_count = int(session.scalar(select(func.count(ReviewNote.id))) or 0)
            expected_delta = 0 if existing is not None else 1
            if after_count - before_count != expected_delta:
                raise ValueError("ReviewNote row delta is not exact")
            candidate_after = build_backtest_trust_audit(session, report_id=report_id)
            report14_after = build_backtest_trust_audit(session, report_id=REPORT14_ID)
            if candidate_after.get("audit_status") != "passed" or report14_after.get("audit_status") != "passed":
                raise ValueError("candidate/report14 trust audit failed after ReviewNote flush")
            if _model_facts_hash(report) != report_hash_before or _model_facts_hash(report14) != report14_hash_before:
                raise ValueError("report facts changed while creating ReviewNote")
            if _model_facts_hash(trade) != trade_hash_before:
                raise ValueError("selected trade facts changed while creating ReviewNote")
            staged = {
                "status": "passed",
                "report_id": report_id,
                "validation_context_hash": context["context_hash"],
                "review_note": {
                    "id": note.id,
                    "created_by_task": True,
                    "created_in_current_transaction": existing is None,
                    "resumed_existing_task_note": existing is not None,
                    "saved_and_reread": False,
                },
                "selected_trade": _trade_evidence(trade),
                "exact_bars": _bars_evidence(bars_payload),
                "timing": {
                    "status": "passed",
                    "entry_signal_time": trade.entry_signal_time.isoformat(),
                    "next_bar_fill_time": trade.open_time.isoformat(),
                    "strictly_after": trade.open_time > trade.entry_signal_time,
                },
                "row_counts": {
                    "review_notes_before": before_count,
                    "review_notes_after_flush": after_count,
                    "delta": after_count - before_count,
                },
                "trust_audits": {
                    "candidate_before": candidate_before.get("consistency_hash"),
                    "candidate_after_flush": candidate_after.get("consistency_hash"),
                    "report14_before": report14_before.get("consistency_hash"),
                    "report14_after_flush": report14_after.get("consistency_hash"),
                },
                "report_hash_before": report_hash_before,
                "report14_hash_before": report14_hash_before,
                "trade_hash_before": trade_hash_before,
            }

    with session_factory() as verification:
        report = verification.get(BacktestReportModel, report_id)
        report14 = verification.get(BacktestReportModel, REPORT14_ID)
        note = verification.get(ReviewNote, int(staged["review_note"]["id"]))
        trade = verification.get(BacktestTradeModel, int(staged["selected_trade"]["id"]))
        if report is None or report14 is None or note is None or trade is None:
            raise ValueError("ReviewNote or report facts unavailable after commit")
        reread = review_payload(note, include_source=True, session=verification)
        bars = load_review_bars(verification, note, project_root=repo_root)
        candidate_audit = build_backtest_trust_audit(verification, report_id=report_id)
        report14_audit = build_backtest_trust_audit(verification, report_id=REPORT14_ID)
        report_invariance = {
            "candidate": (
                _model_facts_hash(report) == staged["report_hash_before"]
                and candidate_audit.get("consistency_hash")
                == staged["trust_audits"]["candidate_before"]
                and candidate_audit.get("audit_status") == "passed"
            ),
            "report14": (
                _model_facts_hash(report14) == staged["report14_hash_before"]
                and report14_audit.get("consistency_hash")
                == staged["trust_audits"]["report14_before"]
                and report14_audit.get("audit_status") == "passed"
            ),
            "selected_trade": _model_facts_hash(trade) == staged["trade_hash_before"],
        }
        if not all(report_invariance.values()):
            raise ValueError("report/trade facts changed after ReviewNote commit")
        if reread.get("extra", {}).get("validation_context_hash") != staged["validation_context_hash"]:
            raise ValueError("ReviewNote validation context hash was not persisted")
        staged["review_note"]["saved_and_reread"] = True
        staged["review_note"]["source_id"] = note.source_id
        staged["review_note"]["deep_link"] = (
            f"/review?review_id={note.id}&trade_id={trade.id}&report_id={report_id}"
        )
        staged["selected_trade"]["market_deep_link"] = (
            f"/market/chart?report_id={report_id}&trade_id={trade.id}"
        )
        staged["exact_bars_after_reread"] = _bars_evidence(bars)
        staged["report_invariance"] = report_invariance
        staged["trust_audits"].update(
            {
                "candidate_after_commit": candidate_audit.get("consistency_hash"),
                "report14_after_commit": report14_audit.get("consistency_hash"),
            }
        )
        verification.rollback()
    staged.pop("report_hash_before", None)
    staged.pop("report14_hash_before", None)
    staged.pop("trade_hash_before", None)
    staged["evidence_hash"] = packet_hash(staged)
    return staged


def _report_identity(report: BacktestReportModel) -> dict[str, Any]:
    return {
        "id": report.id,
        "report_no": report.report_no,
        "task_id": report.task_id,
        "task_no": report.task_no,
        "profile_id": report.profile_id,
        "market_data_file_id": report.market_data_file_id,
    }


def _model_facts_hash(model: Any) -> str:
    payload = {
        column.name: _json_value(getattr(model, column.name))
        for column in model.__table__.columns
    }
    return packet_hash(payload)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _trade_evidence(trade: BacktestTradeModel) -> dict[str, Any]:
    return {
        "id": trade.id,
        "trade_no": trade.trade_no,
        "report_id": trade.report_id,
        "contract": trade.contract,
        "direction": trade.direction,
        "net_pnl": trade.net_pnl,
        "entry_signal_time": trade.entry_signal_time.isoformat() if trade.entry_signal_time else None,
        "open_time": trade.open_time.isoformat(),
        "close_time": trade.close_time.isoformat(),
        "commission": trade.commission,
        "slippage": trade.slippage,
        "equity_after_trade": (trade.raw_payload or {}).get("equity_after_trade"),
    }


def _bars_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    bars = list(payload.get("bars") or [])
    lineage = payload.get("lineage") or {}
    primary = lineage.get("primary") if isinstance(lineage.get("primary"), dict) else {}
    sanitized_lineage = {
        "schema_version": lineage.get("schema_version"),
        "source_type": lineage.get("source_type"),
        "source_id": lineage.get("source_id"),
        "quality_policy": lineage.get("quality_policy"),
        "primary": {
            key: primary.get(key)
            for key in (
                "profile_id",
                "market_data_file_id",
                "instrument_symbol",
                "contract_code",
                "period",
                "data_version",
                "provider",
                "data_role",
                "quality_status",
                "checksum",
            )
        },
        "bar": deepcopy(lineage.get("bar") or {}),
    }
    return {
        "status": "passed" if bars else "failed",
        "row_count": len(bars),
        "first_bar": _bar_time(bars[0]) if bars else None,
        "last_bar": _bar_time(bars[-1]) if bars else None,
        "lineage": sanitized_lineage,
        "bars_hash": packet_hash(_json_value(bars)),
    }


def _bar_time(bar: Mapping[str, Any]) -> Any:
    return _json_value(bar.get("datetime") or bar.get("time") or bar.get("trading_day"))


__all__ = [
    "GATE",
    "TASK_ID",
    "build_closed_loop_packet",
    "choose_max_net_loss_trade",
    "execute_review_note",
    "verify_closed_loop_packet",
]
