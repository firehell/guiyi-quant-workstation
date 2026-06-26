from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.models.review import ReviewAttachment, ReviewNote, ReviewTag
from app.services.review_center import (
    attachment_payload,
    backtest_trade_source_payload,
    create_or_get_backtest_trade_review,
    review_payload,
    review_stats,
    tag_payload,
)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewUpdateRequest(BaseModel):
    entry_reason: str | None = None
    exit_reason: str | None = None
    market_phase: str | None = None
    is_system_compliant: bool | None = None
    mistake_tags: list[str] | None = None
    rule_tags: list[str] | None = None
    emotion_tags: list[str] | None = None
    lesson: str | None = None
    screenshot_paths: list[str] | None = None
    review_score: int | None = Field(default=None, ge=0, le=100)
    ai_summary: str | None = None


class ReviewAttachmentRequest(BaseModel):
    file_path: str
    file_type: str | None = "image"
    title: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


@router.get("/sources/backtest-trades")
def list_backtest_trade_sources(
    symbol: str | None = None,
    period: str | None = None,
    report_id: int | None = None,
    reviewed: bool | None = None,
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(BacktestTradeModel).order_by(BacktestTradeModel.close_time.desc())
    if symbol:
        query = query.where(BacktestTradeModel.symbol == symbol)
    if report_id is not None:
        query = query.where(BacktestTradeModel.report_id == report_id)
    trades = list(session.scalars(query))
    rows = []
    for trade in trades:
        report = session.get(BacktestReportModel, trade.report_id)
        if period and report and report.period != period:
            continue
        payload = backtest_trade_source_payload(session, trade)
        if reviewed is not None and payload["reviewed"] != reviewed:
            continue
        rows.append(payload)
    return rows


@router.get("/sources/paper-trades")
def list_paper_trade_sources() -> list[dict[str, Any]]:
    return []


@router.post("/from-backtest-trade/{trade_id}")
def create_review_from_backtest_trade(trade_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        note = create_or_get_backtest_trade_review(session, trade_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    session.refresh(note)
    return review_payload(note, include_source=True, session=session)


@router.get("")
def list_reviews(
    source_type: str | None = None,
    symbol: str | None = None,
    mistake_tag: str | None = None,
    market_phase: str | None = None,
    is_system_compliant: bool | None = None,
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(ReviewNote).order_by(ReviewNote.updated_at.desc())
    if source_type:
        query = query.where(ReviewNote.source_type == source_type)
    if symbol:
        query = query.where(ReviewNote.symbol == symbol)
    if market_phase:
        query = query.where(ReviewNote.market_phase == market_phase)
    if is_system_compliant is not None:
        query = query.where(ReviewNote.is_system_compliant == is_system_compliant)
    rows = list(session.scalars(query))
    if mistake_tag:
        rows = [row for row in rows if mistake_tag in row.mistake_tags]
    return [review_payload(row) for row in rows]


@router.get("/tags")
def list_review_tags(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    tags = session.scalars(select(ReviewTag).where(ReviewTag.is_active.is_(True)).order_by(ReviewTag.tag_type, ReviewTag.sort_order))
    return [tag_payload(tag) for tag in tags]


@router.get("/stats")
def get_review_stats(session: Session = Depends(get_db)) -> dict[str, Any]:
    return review_stats(session)


@router.get("/{review_id}")
def get_review(review_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    return review_payload(note, include_source=True, session=session)


@router.put("/{review_id}")
def update_review(review_id: int, request: ReviewUpdateRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    data = request.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(note, key, value)
    session.commit()
    session.refresh(note)
    return review_payload(note, include_source=True, session=session)


@router.post("/{review_id}/attachments")
def add_review_attachment(review_id: int, request: ReviewAttachmentRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    attachment = ReviewAttachment(
        review_id=review_id,
        file_path=request.file_path,
        file_type=request.file_type,
        title=request.title,
        meta=request.meta,
    )
    session.add(attachment)
    paths = list(note.screenshot_paths or [])
    if request.file_path not in paths:
        paths.append(request.file_path)
        note.screenshot_paths = paths
    session.commit()
    session.refresh(attachment)
    return attachment_payload(attachment)
