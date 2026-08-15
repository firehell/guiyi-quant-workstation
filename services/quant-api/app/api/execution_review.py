"""HTTP boundary for the Execution Review application domain."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.execution_review.contracts import load_product_trade_multipliers
from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)
from app.execution_review.pnl import PositionState
from app.execution_review.service import (
    DecisionUpdateCommand,
    DispositionCorrectionCommand,
    DispositionCorrectionResult,
    ExecutedCommand,
    ExecutedResult,
    ExecutionCommand,
    ExecutionResult,
    ExecutionReviewDomainError,
    ExecutionReviewService,
    ExecutionUpdateCommand,
    NotExecutedCommand,
    ReviewCommand,
    TimelineExecutionCommand,
    TimelineResult,
)
from app.schemas.execution_review import (
    DecisionOut,
    DecisionUpdateRequest,
    DispositionCorrectionRequest,
    DispositionCorrectionResponse,
    EpisodeDetailResponse,
    EpisodeOut,
    EpisodeStateStatsOut,
    EventStateOut,
    EventStatesResponse,
    ExecutedRequest,
    ExecutedResponse,
    ExecutionCreateRequest,
    ExecutionOut,
    ExecutionResponse,
    ExecutionReviewStatsResponse,
    ExecutionUpdateRequest,
    NotExecutedRequest,
    OpportunityStatsOut,
    PositionOut,
    ReviewItemOut,
    ReviewItemsResponse,
    ReviewOut,
    ReviewRequest,
    TimelineReplaceRequest,
    TimelineResponse,
)


router = APIRouter(prefix="/api/execution-review", tags=["execution-review"])
_T = TypeVar("_T")
_MULTIPLIER_PATH = (
    Path(__file__).resolve().parents[4]
    / "data/reference/product_trade_multipliers.csv"
)


@router.get("/items", response_model=ReviewItemsResponse)
def list_items(
    state: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ReviewItemsResponse:
    items = _domain_call(lambda: _service(session).list_items(state=state))
    return ReviewItemsResponse(
        items=[
            ReviewItemOut(
                item_kind=item.item_kind,
                state=item.state,
                event_id=item.event_id,
                decision_id=item.decision_id,
                episode_id=item.episode_id,
                symbol=item.symbol,
                contract=item.contract,
                direction=item.direction,
                trading_day=item.trading_day,
            )
            for item in items
        ]
    )


@router.get("/event-states", response_model=EventStatesResponse)
def event_states(session: Session = Depends(get_db)) -> EventStatesResponse:
    states = _domain_call(lambda: _service(session).event_states())
    return EventStatesResponse(
        items=[
            EventStateOut(
                event_id=item.event_id,
                state=item.state,
                decision_id=item.decision_id,
                episode_id=item.episode_id,
            )
            for item in states
        ]
    )


@router.get("/episodes/{episode_id}", response_model=EpisodeDetailResponse)
def episode_detail(
    episode_id: int,
    session: Session = Depends(get_db),
) -> EpisodeDetailResponse:
    detail = _domain_call(lambda: _service(session).episode_detail(episode_id))
    return EpisodeDetailResponse(
        episode=_episode_out(detail.episode),
        executions=[_execution_out(item) for item in detail.executions],
        review=_review_out(detail.review) if detail.review is not None else None,
        position=_position_out(detail.position),
    )


@router.get("/stats", response_model=ExecutionReviewStatsResponse)
def stats(
    trading_day_from: date | None = Query(default=None),
    trading_day_to: date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ExecutionReviewStatsResponse:
    result = _domain_call(
        lambda: _service(session).stats(
            trading_day_from=trading_day_from,
            trading_day_to=trading_day_to,
        )
    )
    return ExecutionReviewStatsResponse(
        opportunities=OpportunityStatsOut(
            eligible_events=result.opportunities.eligible_events,
            processed_events=result.opportunities.processed_events,
            pending_events=result.opportunities.pending_events,
            executed_decisions=result.opportunities.executed_decisions,
            not_executed_decisions=result.opportunities.not_executed_decisions,
            decision_completion_rate=(
                result.opportunities.decision_completion_rate
            ),
            execution_rate=result.opportunities.execution_rate,
            primary_reason_counts=result.opportunities.primary_reason_counts,
        ),
        episode_states=EpisodeStateStatsOut(
            open_episodes=result.episode_states.open_episodes,
            pending_review_episodes=result.episode_states.pending_review_episodes,
            done_episodes=result.episode_states.done_episodes,
        ),
    )


@router.post(
    "/events/{event_id}/not-executed",
    response_model=DecisionOut,
)
def record_not_executed(
    event_id: int,
    request: NotExecutedRequest,
    session: Session = Depends(get_db),
) -> DecisionOut:
    decision = _domain_call(
        lambda: _service(session).record_not_executed(
            event_id,
            NotExecutedCommand(
                primary_reason=request.primary_reason,
                secondary_reasons=tuple(request.secondary_reasons),
                first_viewed_at=request.first_viewed_at,
                decided_at=request.decided_at,
                note=request.note,
            ),
        )
    )
    return _decision_out(decision)


@router.post("/events/{event_id}/executed", response_model=ExecutedResponse)
def record_executed(
    event_id: int,
    request: ExecutedRequest,
    session: Session = Depends(get_db),
) -> ExecutedResponse:
    result = _domain_call(
        lambda: _service(session).record_executed(
            event_id,
            ExecutedCommand(
                executed_at=request.executed_at,
                price=request.price,
                quantity=request.quantity,
                execution_reason_tags=tuple(request.execution_reason_tags),
                first_viewed_at=request.first_viewed_at,
                decided_at=request.decided_at,
                planned_stop_price=request.planned_stop_price,
                stop_basis=request.stop_basis,
                note=request.note,
            ),
        )
    )
    return _executed_response(result)


@router.post(
    "/episodes/{episode_id}/executions",
    response_model=ExecutionResponse,
)
def append_execution(
    episode_id: int,
    request: ExecutionCreateRequest,
    session: Session = Depends(get_db),
) -> ExecutionResponse:
    result = _domain_call(
        lambda: _service(session).append_execution(
            episode_id,
            ExecutionCommand(
                execution_type=request.execution_type,
                executed_at=request.executed_at,
                price=request.price,
                quantity=request.quantity,
                note=request.note,
            ),
        )
    )
    return _execution_response(result)


@router.post("/episodes/{episode_id}/review", response_model=ReviewOut)
def submit_review(
    episode_id: int,
    request: ReviewRequest,
    session: Session = Depends(get_db),
) -> ReviewOut:
    review = _domain_call(
        lambda: _service(session).submit_review(
            episode_id,
            _review_command(request),
        )
    )
    return _review_out(review)


@router.put("/decisions/{decision_id}", response_model=DecisionOut)
def update_decision(
    decision_id: int,
    request: DecisionUpdateRequest,
    session: Session = Depends(get_db),
) -> DecisionOut:
    decision = _domain_call(
        lambda: _service(session).update_decision(
            decision_id,
            DecisionUpdateCommand(
                first_viewed_at=request.first_viewed_at,
                decided_at=request.decided_at,
                primary_not_execute_reason=request.primary_not_execute_reason,
                secondary_not_execute_reasons=tuple(
                    request.secondary_not_execute_reasons
                ),
                note=request.note,
                execution_reason_tags=tuple(request.execution_reason_tags),
                planned_stop_price=request.planned_stop_price,
                stop_basis=request.stop_basis,
            ),
        )
    )
    return _decision_out(decision)


@router.put("/executions/{execution_id}", response_model=ExecutionResponse)
def update_execution(
    execution_id: int,
    request: ExecutionUpdateRequest,
    session: Session = Depends(get_db),
) -> ExecutionResponse:
    result = _domain_call(
        lambda: _service(session).update_execution(
            execution_id,
            ExecutionUpdateCommand(
                executed_at=request.executed_at,
                price=request.price,
                note=request.note,
            ),
        )
    )
    return _execution_response(result)


@router.put(
    "/episodes/{episode_id}/execution-timeline",
    response_model=TimelineResponse,
)
def replace_execution_timeline(
    episode_id: int,
    request: TimelineReplaceRequest,
    session: Session = Depends(get_db),
) -> TimelineResponse:
    result = _domain_call(
        lambda: _service(session).replace_execution_timeline(
            episode_id,
            tuple(
                TimelineExecutionCommand(
                    execution_id=item.execution_id,
                    execution_type=item.execution_type,
                    executed_at=item.executed_at,
                    price=item.price,
                    quantity=item.quantity,
                    note=item.note,
                )
                for item in request.items
            ),
        )
    )
    return _timeline_response(result)


@router.put("/reviews/{review_id}", response_model=ReviewOut)
def update_review(
    review_id: int,
    request: ReviewRequest,
    session: Session = Depends(get_db),
) -> ReviewOut:
    review = _domain_call(
        lambda: _service(session).update_review(
            review_id,
            _review_command(request),
        )
    )
    return _review_out(review)


@router.post(
    "/decisions/{decision_id}/correct-disposition",
    response_model=DispositionCorrectionResponse,
)
def correct_disposition(
    decision_id: int,
    request: DispositionCorrectionRequest,
    session: Session = Depends(get_db),
) -> DispositionCorrectionResponse:
    result = _domain_call(
        lambda: _service(session).correct_disposition(
            decision_id,
            DispositionCorrectionCommand(
                target_disposition=request.target_disposition,
                primary_reason=request.primary_reason,
                secondary_reasons=tuple(request.secondary_reasons),
                execution_reason_tags=tuple(request.execution_reason_tags),
                executed_at=request.executed_at,
                price=request.price,
                quantity=request.quantity,
                first_viewed_at=request.first_viewed_at,
                decided_at=request.decided_at,
                planned_stop_price=request.planned_stop_price,
                stop_basis=request.stop_basis,
                note=request.note,
            ),
        )
    )
    return _correction_response(result)


def _service(session: Session) -> ExecutionReviewService:
    return ExecutionReviewService(
        session,
        multipliers=load_product_trade_multipliers(_MULTIPLIER_PATH),
        clock=lambda: datetime.now(UTC),
    )


def _domain_call(call: Callable[[], _T]) -> _T:
    try:
        return call()
    except ExecutionReviewDomainError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
        ) from exc


def _decision_out(row: TradeDecision) -> DecisionOut:
    return DecisionOut(
        id=row.id,
        alert_event_id=row.alert_event_id,
        disposition=row.disposition,
        first_viewed_at=row.first_viewed_at,
        decided_at=row.decided_at,
        primary_not_execute_reason=row.primary_not_execute_reason,
        secondary_not_execute_reasons=list(row.secondary_not_execute_reasons),
        note=row.decision_note,
        execution_reason_tags=list(row.execution_reason_tags),
        planned_stop_price=row.planned_stop_price,
        stop_basis=row.stop_basis,
    )


def _episode_out(row: TradeEpisode) -> EpisodeOut:
    return EpisodeOut(
        id=row.id,
        origin_decision_id=row.origin_decision_id,
        symbol=row.symbol,
        contract=row.contract,
        direction=row.direction,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        roll_reference_exit_price=row.roll_reference_exit_price,
        roll_reference_bar_end=row.roll_reference_bar_end,
        contract_multiplier_snapshot=row.contract_multiplier_snapshot,
        multiplier_policy_id=row.multiplier_policy_id,
    )


def _execution_out(row: TradeExecution) -> ExecutionOut:
    return ExecutionOut(
        id=row.id,
        episode_id=row.episode_id,
        trigger_decision_id=row.trigger_decision_id,
        sequence_no=row.sequence_no,
        execution_type=row.execution_type,
        executed_at=row.executed_at,
        price=row.price,
        quantity=row.quantity,
        note=row.note,
    )


def _review_out(row: TradeReview) -> ReviewOut:
    return ReviewOut(
        id=row.id,
        episode_id=row.episode_id,
        signal_execution_adherence=row.signal_execution_adherence,
        entry_tags=list(row.entry_tags),
        holding_tags=list(row.holding_tags),
        exit_tags=list(row.exit_tags),
        market_context_tags=list(row.market_context_tags),
        psychology_tags=list(row.psychology_tags),
        summary=row.summary,
        submitted_at=row.submitted_at,
        updated_at=row.updated_at,
    )


def _position_out(position: PositionState) -> PositionOut:
    return PositionOut(
        remaining_quantity=position.remaining_quantity,
        average_cost=position.average_cost,
        realized_points=position.realized_points,
        estimated_gross_pnl=position.realized_gross_pnl,
    )


def _executed_response(result: ExecutedResult) -> ExecutedResponse:
    return ExecutedResponse(
        decision=_decision_out(result.decision),
        episode=_episode_out(result.episode),
        execution=_execution_out(result.execution),
        position=_position_out(result.position),
    )


def _execution_response(result: ExecutionResult) -> ExecutionResponse:
    return ExecutionResponse(
        episode=_episode_out(result.episode),
        execution=_execution_out(result.execution),
        position=_position_out(result.position),
    )


def _timeline_response(result: TimelineResult) -> TimelineResponse:
    return TimelineResponse(
        episode=_episode_out(result.episode),
        executions=[_execution_out(row) for row in result.executions],
        position=_position_out(result.position),
    )


def _correction_response(
    result: DispositionCorrectionResult,
) -> DispositionCorrectionResponse:
    return DispositionCorrectionResponse(
        decision=_decision_out(result.decision),
        episode=_episode_out(result.episode) if result.episode is not None else None,
        execution=(
            _execution_out(result.execution)
            if result.execution is not None
            else None
        ),
        position=(
            _position_out(result.position) if result.position is not None else None
        ),
    )


def _review_command(request: ReviewRequest) -> ReviewCommand:
    return ReviewCommand(
        signal_execution_adherence=request.signal_execution_adherence,
        entry_tags=tuple(request.entry_tags),
        holding_tags=tuple(request.holding_tags),
        exit_tags=tuple(request.exit_tags),
        market_context_tags=tuple(request.market_context_tags),
        psychology_tags=tuple(request.psychology_tags),
        summary=request.summary,
    )
