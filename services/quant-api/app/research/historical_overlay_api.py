"""Read-only HTTP projections for offline Historical Research events."""

from __future__ import annotations

from datetime import date
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import ActiveUniverseError
from app.research.composition import (
    build_jdj_research_service,
    build_jdj_strategy_replay_service,
    build_n_structure_research_service,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_policy import JdjPolicyError
from app.research.jdj.jdj_research import (
    JdjResearchRequest,
    JdjSourceUnavailableError,
)
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyProfileUnavailableError,
    JdjStrategyReplayRequest,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
)
from app.research.n_structure.n_structure_policy import NStructurePolicyError
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from app.schemas.research_overlays import (
    JdjHistoricalEventOut,
    JdjHistoricalRequestOut,
    JdjHistoricalResponse,
    JdjStrategyHistoricalActionOut,
    JdjStrategyHistoricalRequestOut,
    JdjStrategyHistoricalResponse,
    NStructureHistoricalEventOut,
    NStructureHistoricalRequestOut,
    NStructureHistoricalResponse,
)


router = APIRouter(prefix="/api/v1/market/research", tags=["market-research"])


@router.get(
    "/n-structure/history",
    response_model=NStructureHistoricalResponse,
)
def n_structure_historical_events(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> NStructureHistoricalResponse:
    if series_kind != "actual_dominant" or frequency != "5m":
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_N_STRUCTURE_HISTORICAL_REQUEST"},
        )
    try:
        request = NStructureResearchRequest(
            since=since,
            through=through,
            symbol=symbol,
        )
        events = build_n_structure_research_service(session).completion_events(
            request
        )
    except (ActiveUniverseError, NStructurePolicyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except (
        NStructureSegmentIdentityError,
        NStructureSourceUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_N_STRUCTURE_HISTORICAL_REQUEST"},
        ) from None
    normalized_symbol = request.symbol
    if normalized_symbol is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_N_STRUCTURE_HISTORICAL_REQUEST"},
        )
    return NStructureHistoricalResponse(
        request=NStructureHistoricalRequestOut(
            series_kind="actual_dominant",
            symbol=normalized_symbol,
            frequency="5m",
            since=request.since,
            through=request.through,
        ),
        events=[
            NStructureHistoricalEventOut(
                event_id=event.event_id,
                observed_at=event.observed_at,
                trading_day=event.trading_day,
                contract=event.contract,
                segment_start_trading_day=event.segment_start_trading_day,
                direction=event.direction.value,
            )
            for event in events
        ],
    )


@router.get(
    "/jdj/history",
    response_model=JdjHistoricalResponse,
)
def jdj_historical_events(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> JdjHistoricalResponse:
    if series_kind != "actual_dominant" or frequency != "1m":
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JDJ_HISTORICAL_REQUEST"},
        )
    try:
        request = JdjResearchRequest(
            since=since,
            through=through,
            symbol=symbol,
            candidate_id="jdj_trend_follow_1m_candidate_v1",
        )
        normalized_symbol = request.symbol
        if normalized_symbol is None:
            raise JdjContextError()
        result = build_jdj_research_service(session).run_batch(
            symbol=normalized_symbol,
            since=since,
            through=through,
        )
    except (
        ActiveUniverseError,
        JdjPolicyError,
        NStructurePolicyError,
        JdjSourceUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except (JdjContextError, ValueError):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JDJ_HISTORICAL_REQUEST"},
        ) from None
    return JdjHistoricalResponse(
        request=JdjHistoricalRequestOut(
            series_kind="actual_dominant",
            symbol=result.symbol,
            frequency="1m",
            since=since,
            through=through,
        ),
        events=[
            JdjHistoricalEventOut(
                event_id=event.event_id,
                candidate_id=event.candidate_id,
                source_event_kind=event.source_event_kind,
                observed_at=event.observed_at,
                trading_day=event.trading_day,
                contract=event.contract,
                segment_start_trading_day=(
                    event.segment_start_trading_day
                ),
                direction=event.direction.value,
                trigger_level=event.trigger_level,
            )
            for candidate in result.candidates
            for event in candidate.result.events
        ],
    )


@router.get(
    "/jdj-strategy/history",
    response_model=JdjStrategyHistoricalResponse,
)
def jdj_strategy_historical_actions(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> JdjStrategyHistoricalResponse:
    try:
        request = JdjStrategyReplayRequest(
            series_kind=series_kind,
            symbol=symbol,
            frequency=frequency,
            since=since,
            through=through,
        )
    except JdjStrategyProfileUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code},
        ) from None
    try:
        result = build_jdj_strategy_replay_service(session).history(request)
    except (
        JdjStrategyContextInvalidError,
        JdjStrategySegmentIdentityError,
        JdjStrategySessionIdentityError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    return JdjStrategyHistoricalResponse(
        request=JdjStrategyHistoricalRequestOut(
            series_kind=cast(SeriesKind, result.request.series_kind).value,
            symbol=result.request.symbol,
            frequency=cast(BarFrequency, result.request.frequency).value,
            since=result.request.since,
            through=result.request.through,
        ),
        reference_execution=result.reference_execution,
        actions=[
            JdjStrategyHistoricalActionOut(
                event_id=action.event_id,
                episode_id=action.episode_id,
                kind=action.kind.value,
                source_event_ids=list(action.source_event_ids),
                primary_setup=action.primary_setup,
                supporting_setups=list(action.supporting_setups),
                direction=(
                    action.direction.value
                    if action.direction is not None
                    else None
                ),
                contract=action.contract,
                trading_day=action.trading_day,
                segment_start_trading_day=(
                    action.segment_start_trading_day
                ),
                decision_at=action.decision_at,
                effective_bar_end=action.effective_bar_end,
                reference_price=action.reference_price,
                quantity=action.quantity,
                position_quantity_after=action.position_quantity_after,
                stop_price=action.stop_price,
                target_price=action.target_price,
                reward_risk=action.reward_risk,
                reason=action.reason,
                fill_basis=action.fill_basis,
            )
            for action in result.actions
        ],
    )
