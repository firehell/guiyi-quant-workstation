from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.models.review import ReviewAttachment, ReviewNote, ReviewTag
from app.models.live_review_loop import SignalDecision
from app.review.backtest_trade import apply_review_fields, default_mistake_tag_payloads, review_response, tag_response
from app.schemas.review import (
    ReviewAttachmentRequest,
    ReviewExactBarsResponse,
    ReviewFromBacktestTradeRequest,
    ReviewLineageResponse,
    ReviewUpdateRequest,
)
from app.services.review_center import (
    attachment_payload,
    backtest_trade_source_payload,
    create_or_get_backtest_trade_review,
    create_or_get_signal_review,
    review_stats,
)
from app.services.review_lineage import (
    ReviewLineageError,
    load_review_bars,
    resolve_review_source_lineage,
)
from app.live_review_loop.research import (
    ResearchSampleError,
    create_or_get_decision_review,
    extract_research_sample,
)
from app.live_review_loop.gates import (
    LiveReviewExecutionGate,
    LiveReviewFeatureDisabledError,
)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/sources/backtest-trades")
def list_backtest_trade_sources(
    symbol: str | None = None,
    period: str | None = None,
    report_id: int | None = None,
    reviewed: bool | None = None,
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]] | dict[str, Any]:
    if paged:
        paged_query = (
            select(BacktestTradeModel)
            .join(BacktestReportModel, BacktestReportModel.id == BacktestTradeModel.report_id)
            .outerjoin(
                ReviewNote,
                and_(
                    ReviewNote.source_type == "backtest_trade",
                    ReviewNote.source_id == BacktestTradeModel.id,
                ),
            )
        )
        if symbol:
            paged_query = paged_query.where(BacktestTradeModel.symbol == symbol)
        if period:
            paged_query = paged_query.where(BacktestReportModel.period == period)
        if report_id is not None:
            paged_query = paged_query.where(BacktestTradeModel.report_id == report_id)
        if reviewed is True:
            paged_query = paged_query.where(ReviewNote.id.is_not(None))
        if reviewed is False:
            paged_query = paged_query.where(ReviewNote.id.is_(None))
        total = int(session.scalar(select(func.count()).select_from(paged_query.subquery())) or 0)
        trades = session.scalars(
            paged_query.order_by(BacktestTradeModel.close_time.desc()).limit(limit).offset(offset)
        )
        return {
            "items": [backtest_trade_source_payload(session, trade) for trade in trades],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
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


@router.get("/sources/signal-decisions")
def list_signal_decision_sources(
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    decisions = list(session.scalars(select(SignalDecision).order_by(SignalDecision.bar_end.desc())))
    reviewed_ids = set(
        session.scalars(
            select(ReviewNote.source_id).where(
                ReviewNote.source_type == "signal_decision",
                ReviewNote.source_id.is_not(None),
            )
        )
    )
    return [
        {
            "id": decision.id,
            "decision_key": decision.decision_key,
            "reviewed": decision.id in reviewed_ids,
            "symbol": "jm",
            "contract": decision.actual_contract,
            "period": "15m",
            "trading_day": decision.trading_day.isoformat(),
            "bar_end": decision.bar_end.isoformat(),
            "strategy_name": decision.strategy_code,
            "strategy_version": decision.strategy_version,
            "result_kind": decision.result_kind,
            "direction": decision.direction,
            "input_digest": decision.input_digest,
            "fingerprint": decision.fingerprint,
        }
        for decision in decisions
    ]


@router.get("/lineage/{source_type}/{source_id}", response_model=ReviewLineageResponse)
def get_source_lineage(
    source_type: str,
    source_id: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return resolve_review_source_lineage(session, source_type=source_type, source_id=source_id)
    except ReviewLineageError as exc:
        raise _lineage_http_error(exc) from exc


@router.post("/from-strategy-signal/{signal_id}")
def create_review_from_strategy_signal(
    signal_id: int,
    request: ReviewFromBacktestTradeRequest | None = Body(default=None),
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
    request: ReviewFromBacktestTradeRequest | None = Body(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return _create_signal_review(
        session,
        source_type="signal_event",
        source_id=event_id,
        request=request,
    )


@router.post("/from-signal-decision/{decision_id}")
def create_review_from_signal_decision(
    decision_id: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_live_review_enabled()
    try:
        note = create_or_get_decision_review(session, decision_id)
    except ResearchSampleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    session.refresh(note)
    return review_response(note, include_source=False, session=session)


@router.post("/from-backtest-trade/{trade_id}")
def create_review_from_backtest_trade(
    trade_id: int,
    request: ReviewFromBacktestTradeRequest | None = Body(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        note = create_or_get_backtest_trade_review(session, trade_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if request is not None:
        apply_review_fields(note, request.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(note)
    return review_response(note, include_source=True, session=session)


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
    query = select(ReviewNote)
    if source_type:
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
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    try:
        return load_review_bars(session, note)
    except ReviewLineageError as exc:
        raise _lineage_http_error(exc) from exc


@router.get("/{review_id}")
def get_review(review_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    return review_response(note, include_source=True, session=session)


@router.put("/{review_id}")
def update_review(review_id: int, request: ReviewUpdateRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    if note.source_type == "signal_decision":
        _require_live_review_enabled()
    data = request.model_dump(exclude_unset=True)
    apply_review_fields(note, data)
    session.commit()
    session.refresh(note)
    return review_response(note, include_source=True, session=session)


@router.post("/{review_id}/research-sample")
def create_research_sample(
    review_id: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_live_review_enabled()
    try:
        sample = extract_research_sample(session, review_id)
    except ResearchSampleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    session.refresh(sample)
    return {
        "id": sample.id,
        "sample_key": sample.sample_key,
        "schema_version": sample.schema_version,
        "decision_key": sample.decision_key,
        "review_id": sample.review_id,
        "reconciliation_digest": sample.reconciliation_digest,
        "features": sample.features,
        "outcome": sample.outcome,
        "labels": sample.labels,
        "lineage": sample.lineage,
        "created_at": sample.created_at.isoformat(),
    }


def _require_live_review_enabled() -> None:
    try:
        LiveReviewExecutionGate(os.environ).require_review()
    except LiveReviewFeatureDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{review_id}/attachments")
def add_review_attachment(review_id: int, request: ReviewAttachmentRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    note = session.get(ReviewNote, review_id)
    if note is None:
        raise HTTPException(status_code=404, detail="review not found")
    if note.source_type == "signal_decision":
        _require_live_review_enabled()
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
    request: ReviewFromBacktestTradeRequest | None,
) -> dict[str, Any]:
    try:
        note = create_or_get_signal_review(session, source_type=source_type, source_id=source_id)
    except ReviewLineageError as exc:
        raise _lineage_http_error(exc) from exc
    if request is not None:
        apply_review_fields(note, request.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(note)
    return review_response(note, include_source=True, session=session)


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
