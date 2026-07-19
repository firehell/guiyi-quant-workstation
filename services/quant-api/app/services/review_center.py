from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.models.review import ReviewAttachment, ReviewNote, ReviewTag
from app.models.signal import SignalEvent, StrategySignal
from app.services.review_lineage import ReviewLineageError, resolve_review_source_lineage


def create_or_get_backtest_trade_review(session: Session, trade_id: int) -> ReviewNote:
    trade = session.get(BacktestTradeModel, trade_id)
    if trade is None:
        raise ValueError("backtest trade not found")
    report = session.get(BacktestReportModel, trade.report_id)
    existing = session.scalar(select(ReviewNote).where(ReviewNote.source_type == "backtest_trade", ReviewNote.source_id == trade_id))
    if existing is not None:
        existing.extra = {**_review_extra_from_trade(trade, report, session=session), **(existing.extra or {})}
        return existing
    note = ReviewNote(
        source_type="backtest_trade",
        source_id=trade.id,
        symbol=trade.symbol,
        contract=trade.contract,
        period=_entry_interval(trade, report),
        direction=trade.direction,
        strategy_name=report.strategy_code if report and report.strategy_code else "su_bing_ema21",
        strategy_version=report.strategy_version if report and report.strategy_version else report.template_name if report else "v0",
        open_time=trade.open_time,
        close_time=trade.close_time,
        open_price=trade.open_price,
        close_price=trade.close_price,
        volume=trade.volume,
        net_pnl=trade.net_pnl,
        entry_reason=trade.entry_reason,
        exit_reason=trade.exit_reason,
        is_system_compliant=None,
        market_phase=None,
        mistake_tags=_suggest_mistake_tags(trade),
        rule_tags=_suggest_rule_tags(trade),
        emotion_tags=[],
        lesson=None,
        screenshot_paths=[],
        kline_focus_time=trade.open_time,
        kline_window_start=trade.open_time - timedelta(days=3),
        kline_window_end=trade.close_time + timedelta(days=3),
        ai_status="reserved",
        extra=_review_extra_from_trade(trade, report, session=session),
    )
    session.add(note)
    session.flush()
    return note


def create_or_get_signal_review(session: Session, *, source_type: str, source_id: int) -> ReviewNote:
    if source_type not in {"strategy_signal", "signal_event"}:
        raise ReviewLineageError(
            code="REVIEW_SOURCE_TYPE_UNSUPPORTED",
            context={"source_type": source_type, "source_id": source_id},
        )
    existing = session.scalar(
        select(ReviewNote).where(ReviewNote.source_type == source_type, ReviewNote.source_id == source_id)
    )
    if existing is not None:
        return existing
    source = session.get(StrategySignal if source_type == "strategy_signal" else SignalEvent, source_id)
    if source is None:
        raise ReviewLineageError(
            code="REVIEW_SOURCE_NOT_FOUND",
            context={"source_type": source_type, "source_id": source_id},
        )
    lineage = resolve_review_source_lineage(session, source_type=source_type, source_id=source_id)
    note = ReviewNote(
        source_type=source_type,
        source_id=source_id,
        symbol=source.symbol,
        contract=source.contract,
        period=source.period,
        direction=source.direction,
        strategy_name=source.strategy_name,
        strategy_version=source.strategy_version,
        open_time=source.bar_start,
        close_time=source.bar_end,
        open_price=source.trigger_price,
        close_price=source.trigger_price,
        volume=0,
        net_pnl=None,
        entry_reason="；".join(source.reasons or []) if isinstance(source, StrategySignal) else None,
        exit_reason=None,
        is_system_compliant=None,
        market_phase=None,
        mistake_tags=[],
        rule_tags=[],
        emotion_tags=[],
        lesson=None,
        screenshot_paths=[],
        kline_focus_time=source.bar_end,
        kline_window_start=source.bar_start,
        kline_window_end=source.bar_end,
        ai_status="reserved",
        extra={
            "lineage_status": "ready",
            "formal_lineage": deepcopy(lineage),
            "signal_id": source.id if source_type == "strategy_signal" else source.signal_id,
            "event_id": source.id if source_type == "signal_event" else None,
            "source_mode": (source.features or {}).get("source_mode") if isinstance(source, StrategySignal) else source.source_mode,
        },
    )
    session.add(note)
    session.flush()
    return note


def backtest_trade_source_payload(session: Session, trade: BacktestTradeModel) -> dict[str, Any]:
    report = session.get(BacktestReportModel, trade.report_id)
    review = session.scalar(select(ReviewNote).where(ReviewNote.source_type == "backtest_trade", ReviewNote.source_id == trade.id))
    entry_interval = _entry_interval(trade, report)
    return {
        "id": trade.id,
        "source_type": "backtest_trade",
        "source_id": trade.id,
        "review_id": review.id if review else None,
        "reviewed": review is not None,
        "report_id": trade.report_id,
        "trade_id": trade.id,
        "trade_no": trade.trade_no,
        "symbol": trade.symbol,
        "contract": trade.contract,
        "period": entry_interval,
        "entry_interval": entry_interval,
        "direction": trade.direction,
        "entry_signal_time": trade.entry_signal_time.isoformat() if trade.entry_signal_time else None,
        "open_time": trade.open_time.isoformat(),
        "close_time": trade.close_time.isoformat(),
        "entry_time": trade.open_time.isoformat(),
        "exit_time": trade.close_time.isoformat(),
        "open_price": trade.open_price,
        "close_price": trade.close_price,
        "volume": trade.volume,
        "net_pnl": trade.net_pnl,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "holding_bars": trade.holding_bars,
        "hold_bars": _hold_bars(trade),
        "entry_reason": trade.entry_reason,
        "exit_reason": trade.exit_reason,
    }


def review_payload(note: ReviewNote, include_source: bool = False, session: Session | None = None) -> dict[str, Any]:
    extra = dict(note.extra or {})
    payload = {
        "id": note.id,
        "source_type": note.source_type,
        "source_id": note.source_id,
        "report_id": extra.get("report_id") or extra.get("source_report_id"),
        "trade_id": note.source_id if note.source_type == "backtest_trade" else extra.get("trade_id"),
        "trade_no": extra.get("trade_no"),
        "symbol": note.symbol,
        "contract": note.contract,
        "period": note.period,
        "entry_interval": extra.get("entry_interval") or note.period,
        "direction": note.direction,
        "strategy_name": note.strategy_name,
        "strategy_version": note.strategy_version,
        "open_time": note.open_time.isoformat() if note.open_time else None,
        "close_time": note.close_time.isoformat() if note.close_time else None,
        "entry_time": note.open_time.isoformat() if note.open_time else None,
        "exit_time": note.close_time.isoformat() if note.close_time else None,
        "open_price": note.open_price,
        "close_price": note.close_price,
        "volume": note.volume,
        "net_pnl": note.net_pnl,
        "hold_bars": extra.get("hold_bars") or extra.get("holding_bars"),
        "entry_reason": note.entry_reason,
        "exit_reason": note.exit_reason,
        "market_phase": note.market_phase,
        "is_system_compliant": note.is_system_compliant,
        "mistake_tags": note.mistake_tags,
        "rule_tags": note.rule_tags,
        "emotion_tags": note.emotion_tags,
        "lesson": note.lesson,
        "screenshot_paths": note.screenshot_paths,
        "kline_focus_time": note.kline_focus_time.isoformat() if note.kline_focus_time else None,
        "kline_window_start": note.kline_window_start.isoformat() if note.kline_window_start else None,
        "kline_window_end": note.kline_window_end.isoformat() if note.kline_window_end else None,
        "review_score": note.review_score,
        "ai_summary": note.ai_summary,
        "ai_status": note.ai_status,
        "ai_model": note.ai_model,
        "ai_generated_at": note.ai_generated_at.isoformat() if note.ai_generated_at else None,
        "extra": note.extra,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }
    if include_source and session and note.source_type == "backtest_trade" and note.source_id:
        trade = session.get(BacktestTradeModel, note.source_id)
        payload["source"] = backtest_trade_source_payload(session, trade) if trade else None
    return payload


def tag_payload(tag: ReviewTag) -> dict[str, Any]:
    return {
        "id": tag.id,
        "tag_type": tag.tag_type,
        "name": tag.name,
        "description": tag.description,
        "sort_order": tag.sort_order,
        "is_active": tag.is_active,
    }


def attachment_payload(attachment: ReviewAttachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "review_id": attachment.review_id,
        "file_path": attachment.file_path,
        "file_type": attachment.file_type,
        "title": attachment.title,
        "meta": attachment.meta,
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
    }


def review_stats(session: Session) -> dict[str, Any]:
    notes = list(session.scalars(select(ReviewNote)))
    mistake_counts = Counter(tag for note in notes for tag in note.mistake_tags)
    rule_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "net_pnl": 0.0, "wins": 0})
    for note in notes:
        for tag in note.rule_tags:
            rule_stats[tag]["count"] += 1
            rule_stats[tag]["net_pnl"] += note.net_pnl or 0.0
            if (note.net_pnl or 0.0) > 0:
                rule_stats[tag]["wins"] += 1

    phase_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "net_pnl": 0.0, "wins": 0})
    for note in notes:
        phase = note.market_phase or "未标注"
        phase_stats[phase]["count"] += 1
        phase_stats[phase]["net_pnl"] += note.net_pnl or 0.0
        if (note.net_pnl or 0.0) > 0:
            phase_stats[phase]["wins"] += 1

    compliance_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "net_pnl": 0.0})
    for note in notes:
        key = "系统内" if note.is_system_compliant is True else "系统外" if note.is_system_compliant is False else "未确认"
        compliance_stats[key]["count"] += 1
        compliance_stats[key]["net_pnl"] += note.net_pnl or 0.0

    return {
        "total_reviews": len(notes),
        "mistake_tags": [{"name": name, "count": count} for name, count in mistake_counts.most_common()],
        "rule_effectiveness": [
            {
                "name": name,
                "count": stat["count"],
                "net_pnl": stat["net_pnl"],
                "win_rate": stat["wins"] / stat["count"] if stat["count"] else 0.0,
            }
            for name, stat in sorted(rule_stats.items(), key=lambda item: item[1]["net_pnl"], reverse=True)
        ],
        "market_phase": [
            {
                "name": name,
                "count": stat["count"],
                "net_pnl": stat["net_pnl"],
                "win_rate": stat["wins"] / stat["count"] if stat["count"] else 0.0,
            }
            for name, stat in sorted(phase_stats.items(), key=lambda item: item[1]["count"], reverse=True)
        ],
        "system_compliance": [{"name": name, "count": stat["count"], "net_pnl": stat["net_pnl"]} for name, stat in compliance_stats.items()],
    }


def _suggest_mistake_tags(trade: BacktestTradeModel) -> list[str]:
    tags: list[str] = []
    if trade.net_pnl < 0:
        if "震荡" in trade.entry_reason or "假突破" in trade.exit_reason:
            tags.append("震荡区交易")
        if "价格远离EMA21" in trade.entry_reason:
            tags.append("追价")
        if "止损" in trade.exit_reason:
            tags.append("止损执行")
    return tags


def _suggest_rule_tags(trade: BacktestTradeModel) -> list[str]:
    text = f"{trade.entry_reason};{trade.exit_reason}"
    tags: list[str] = []
    if "EMA21" in text:
        tags.append("EMA21方向过滤")
    if "MACD" in text:
        tags.append("MACD零轴附近交叉")
    if "成交量" in text or "带量" in text:
        tags.append("成交量放大")
    if "共振" in text:
        tags.append("多周期共振")
    if "突破" in text:
        tags.append("带量突破试单")
    if "止损" in text:
        tags.append("止损")
    if "止盈" in text:
        tags.append("止盈")
    return tags


def _review_extra_from_trade(
    trade: BacktestTradeModel,
    report: BacktestReportModel | None,
    *,
    session: Session | None = None,
) -> dict[str, Any]:
    raw_payload = trade.raw_payload or {}
    data_quality_status = _report_quality_status(report)
    extra = {
        "report_id": trade.report_id,
        "source_report_id": trade.report_id,
        "trade_id": trade.id,
        "trade_no": trade.trade_no,
        "entry_interval": _entry_interval(trade, report),
        "entry_time": trade.open_time.isoformat(),
        "exit_time": trade.close_time.isoformat(),
        "hold_bars": _hold_bars(trade),
        "holding_bars": trade.holding_bars,
        "daily_direction": raw_payload.get("daily_direction"),
        "stop_loss_price": raw_payload.get("stop_loss_price"),
        "entry_reason": trade.entry_reason,
        "exit_reason": trade.exit_reason,
        "research_contract": trade.contract.endswith(".MAIN"),
        "data_quality_status": data_quality_status,
    }
    if data_quality_status == "warning":
        extra["data_quality_caveat"] = "来源回测数据为 quality warning，不得作为可信信号证据"
    if session is None:
        return extra
    try:
        extra["formal_lineage"] = resolve_review_source_lineage(
            session,
            source_type="backtest_trade",
            source_id=trade.id,
        )
        extra["lineage_status"] = "ready"
    except ReviewLineageError as exc:
        extra["lineage_status"] = "unavailable"
        extra["lineage_blocked_reason"] = exc.code
    return extra


def _report_quality_status(report: BacktestReportModel | None) -> str | None:
    if report is None:
        return None
    quality = report.quality_status
    if isinstance(quality, dict):
        status = quality.get("status")
        return str(status) if status else None
    return None


def _entry_interval(trade: BacktestTradeModel, report: BacktestReportModel | None) -> str | None:
    raw_payload = trade.raw_payload or {}
    value = raw_payload.get("entry_interval") or (report.period if report else None)
    return str(value) if value else None


def _hold_bars(trade: BacktestTradeModel) -> int:
    raw_payload = trade.raw_payload or {}
    value = raw_payload.get("hold_bars") or raw_payload.get("holding_bars") or trade.holding_bars
    try:
        return int(value)
    except (TypeError, ValueError):
        return trade.holding_bars
