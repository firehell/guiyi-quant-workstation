from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.review import ReviewAttachment, ReviewNote, ReviewTag
from app.models.signal import SignalEvent, StrategySignal
from app.review.policy import supported_review_source_clause
from app.services.review_lineage import ReviewLineageError, resolve_review_source_lineage


def create_or_get_signal_review(
    session: Session, *, source_type: str, source_id: int
) -> ReviewNote:
    if source_type not in {"strategy_signal", "signal_event"}:
        raise ReviewLineageError(
            code="REVIEW_SOURCE_TYPE_UNSUPPORTED",
            context={"source_type": source_type, "source_id": source_id},
        )
    existing = session.scalar(
        select(ReviewNote).where(
            ReviewNote.source_type == source_type,
            ReviewNote.source_id == source_id,
        )
    )
    if existing is not None:
        return existing
    source = session.get(
        StrategySignal if source_type == "strategy_signal" else SignalEvent,
        source_id,
    )
    if source is None:
        raise ReviewLineageError(
            code="REVIEW_SOURCE_NOT_FOUND",
            context={"source_type": source_type, "source_id": source_id},
        )
    lineage = resolve_review_source_lineage(
        session, source_type=source_type, source_id=source_id
    )
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
        entry_reason="；".join(source.reasons or [])
        if isinstance(source, StrategySignal)
        else None,
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
            "source_mode": (source.features or {}).get("source_mode")
            if isinstance(source, StrategySignal)
            else source.source_mode,
        },
    )
    session.add(note)
    session.flush()
    return note


def review_payload(note: ReviewNote) -> dict[str, Any]:
    extra = dict(note.extra or {})
    return {
        "id": note.id,
        "source_type": note.source_type,
        "source_id": note.source_id,
        "symbol": note.symbol,
        "contract": note.contract,
        "period": note.period,
        "direction": note.direction,
        "strategy_name": note.strategy_name,
        "strategy_version": note.strategy_version,
        "open_time": note.open_time.isoformat() if note.open_time else None,
        "close_time": note.close_time.isoformat() if note.close_time else None,
        "open_price": note.open_price,
        "close_price": note.close_price,
        "volume": note.volume,
        "net_pnl": note.net_pnl,
        "entry_reason": note.entry_reason,
        "exit_reason": note.exit_reason,
        "market_phase": note.market_phase,
        "is_system_compliant": note.is_system_compliant,
        "mistake_tags": note.mistake_tags,
        "rule_tags": note.rule_tags,
        "emotion_tags": note.emotion_tags,
        "lesson": note.lesson,
        "screenshot_paths": note.screenshot_paths,
        "kline_focus_time": note.kline_focus_time.isoformat()
        if note.kline_focus_time
        else None,
        "kline_window_start": note.kline_window_start.isoformat()
        if note.kline_window_start
        else None,
        "kline_window_end": note.kline_window_end.isoformat()
        if note.kline_window_end
        else None,
        "review_score": note.review_score,
        "ai_summary": note.ai_summary,
        "ai_status": note.ai_status,
        "ai_model": note.ai_model,
        "ai_generated_at": note.ai_generated_at.isoformat()
        if note.ai_generated_at
        else None,
        "extra": note.extra,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "signal_id": extra.get("signal_id"),
        "event_id": extra.get("event_id"),
    }


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
        "created_at": attachment.created_at.isoformat()
        if attachment.created_at
        else None,
    }


def review_stats(session: Session) -> dict[str, Any]:
    notes = list(
        session.scalars(
            select(ReviewNote).where(supported_review_source_clause(ReviewNote.source_type))
        )
    )
    mistake_counts = Counter(tag for note in notes for tag in note.mistake_tags)
    rule_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "net_pnl": 0.0, "wins": 0}
    )
    phase_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "net_pnl": 0.0, "wins": 0}
    )
    compliance_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "net_pnl": 0.0}
    )
    for note in notes:
        for tag in note.rule_tags:
            rule_stats[tag]["count"] += 1
            rule_stats[tag]["net_pnl"] += note.net_pnl or 0.0
            if (note.net_pnl or 0.0) > 0:
                rule_stats[tag]["wins"] += 1
        phase = note.market_phase or "未标注"
        phase_stats[phase]["count"] += 1
        phase_stats[phase]["net_pnl"] += note.net_pnl or 0.0
        if (note.net_pnl or 0.0) > 0:
            phase_stats[phase]["wins"] += 1
        compliance = (
            "系统内"
            if note.is_system_compliant is True
            else "系统外"
            if note.is_system_compliant is False
            else "未确认"
        )
        compliance_stats[compliance]["count"] += 1
        compliance_stats[compliance]["net_pnl"] += note.net_pnl or 0.0
    return {
        "total_reviews": len(notes),
        "mistake_tags": [
            {"name": name, "count": count}
            for name, count in mistake_counts.most_common()
        ],
        "rule_effectiveness": [
            {
                "name": name,
                "count": stat["count"],
                "net_pnl": stat["net_pnl"],
                "win_rate": stat["wins"] / stat["count"] if stat["count"] else 0.0,
            }
            for name, stat in sorted(
                rule_stats.items(), key=lambda item: item[1]["net_pnl"], reverse=True
            )
        ],
        "market_phase": [
            {
                "name": name,
                "count": stat["count"],
                "net_pnl": stat["net_pnl"],
                "win_rate": stat["wins"] / stat["count"] if stat["count"] else 0.0,
            }
            for name, stat in sorted(
                phase_stats.items(), key=lambda item: item[1]["count"], reverse=True
            )
        ],
        "system_compliance": [
            {"name": name, "count": stat["count"], "net_pnl": stat["net_pnl"]}
            for name, stat in compliance_stats.items()
        ],
    }
