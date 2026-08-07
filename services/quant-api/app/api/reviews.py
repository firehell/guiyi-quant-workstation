from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.review import ReviewAttachment, ReviewNote, ReviewTag
from app.review.policy import is_supported_review_source_type, supported_review_source_clause
from app.review.payloads import apply_review_fields, default_mistake_tag_payloads, review_response, tag_response
from app.schemas.review import (
    ReviewAttachmentRequest,
    ReviewExactBarsResponse,
    ReviewSourceUpdateRequest,
    ReviewLineageResponse,
    ReviewUpdateRequest,
)
from app.services.review_center import (
    attachment_payload,
    create_or_get_signal_review,
    review_stats,
)
from app.services.review_lineage import (
    ReviewLineageError,
    load_review_bars,
    resolve_review_source_lineage,
)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/sources/paper-trades")
def list_paper_trade_sources() -> list[dict[str, Any]]:
    return []


@router.get("/lineage/{source_type}/{source_id}", response_model=ReviewLineageResponse)
def get_source_lineage(
    source_type: str,
    source_id: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_supported_source_type(source_type)
    try:
        return resolve_review_source_lineage(session, source_type=source_type, source_id=source_id)
    except ReviewLineageError as exc:
        raise _lineage_http_error(exc) from exc


@router.post("/from-strategy-signal/{signal_id}")
def create_review_from_strategy_signal(
    signal_id: int,
    request: ReviewSourceUpdateRequest | None = Body(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return _create_signal_review(
        session,
        source_type="strategy_signal",
        source_id=signal_id,
        request=request,
    )


@router.post("/from-signal-event/{event_id}")
def create_review_from_signal_event(
    event_id: int,
    request: ReviewSourceUpdateRequest | None = Body(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return _create_signal_review(
        session,
        source_type="signal_event",
        source_id=event_id,
        request=request,
    )


@router.get("")
def list_reviews(
    source_type: str | None = None,
    source_id: int | None = None,
    symbol: str | None = None,
    mistake_tag: str | None = None,
    market_phase: str | None = None,
    is_system_compliant: bool | None = None,
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]] | dict[str, Any]:
    query = select(ReviewNote).where(supported_review_source_clause(ReviewNote.source_type))
    if source_type is not None:
        _require_supported_source_type(source_type)
        query = query.where(ReviewNote.source_type == source_type)
    if source_id is not None:
        query = query.where(ReviewNote.source_id == source_id)
    if symbol:
        query = query.where(ReviewNote.symbol == symbol)
    if market_phase:
        query = query.where(ReviewNote.market_phase == market_phase)
    if is_system_compliant is not None:
        query = query.where(ReviewNote.is_system_compliant == is_system_compliant)
    if mistake_tag:
        query = query.where(ReviewNote.mistake_tags.contains(mistake_tag))
    total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0) if paged else 0
    if paged:
        query = query.limit(limit).offset(offset)
    rows = list(session.scalars(query.order_by(ReviewNote.updated_at.desc())))
    if mistake_tag:
        rows = [row for row in rows if mistake_tag in row.mistake_tags]
    items = [review_response(row) for row in rows]
    if not paged:
        return items
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/tags")
def list_review_tags(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    tags = session.scalars(select(ReviewTag).where(ReviewTag.is_active.is_(True)).order_by(ReviewTag.tag_type, ReviewTag.sort_order))
    payloads = [tag_response(tag) for tag in tags]
    existing_mistakes = {item["name"] for item in payloads if item["tag_type"] == "mistake"}
    return [*payloads, *default_mistake_tag_payloads(existing_mistakes)]


@router.get("/stats")
def get_review_stats(session: Session = Depends(get_db)) -> dict[str, Any]:
    return review_stats(session)


@router.get("/{review_id}/bars", response_model=ReviewExactBarsResponse)
def get_review_exact_bars(review_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = _get_supported_review_or_404(session, review_id)
    try:
        return load_review_bars(session, note)
    except ReviewLineageError as exc:
        raise _lineage_http_error(exc) from exc


@router.get("/{review_id}")
def get_review(review_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = _get_supported_review_or_404(session, review_id)
    return review_response(note, include_source=True)


@router.put("/{review_id}")
def update_review(review_id: int, request: ReviewUpdateRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = _get_supported_review_or_404(session, review_id)
    data = request.model_dump(exclude_unset=True)
    apply_review_fields(note, data)
    session.commit()
    session.refresh(note)
    return review_response(note, include_source=True)


@router.post("/{review_id}/attachments")
def add_review_attachment(review_id: int, request: ReviewAttachmentRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = _get_supported_review_or_404(session, review_id)
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


def _create_signal_review(
    session: Session,
    *,
    source_type: str,
    source_id: int,
    request: ReviewSourceUpdateRequest | None,
) -> dict[str, Any]:
    try:
        note = create_or_get_signal_review(session, source_type=source_type, source_id=source_id)
    except ReviewLineageError as exc:
        raise _lineage_http_error(exc) from exc
    if request is not None:
        apply_review_fields(note, request.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(note)
    return review_response(note, include_source=True)


def _get_supported_review_or_404(session: Session, review_id: int) -> ReviewNote:
    note = session.get(ReviewNote, review_id)
    if note is None or not is_supported_review_source_type(note.source_type):
        raise HTTPException(status_code=404, detail="review not found")
    return note


def _require_supported_source_type(source_type: str) -> None:
    if not is_supported_review_source_type(source_type):
        raise HTTPException(status_code=404, detail="review source not found")


def _lineage_http_error(exc: ReviewLineageError) -> HTTPException:
    status_code = 404 if exc.code == "REVIEW_SOURCE_NOT_FOUND" else 422
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "context": exc.context,
        },
    )
