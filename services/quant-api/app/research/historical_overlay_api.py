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
    build_jdj_strategy_replay_service,
    build_n_structure_research_service,
)
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyProfileUnavailableError,
    JdjStrategyReplayRequest,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
)
from app.research.n_structure.n_structure_policy import (
    NStructurePolicyError,
    load_n_structure_policy,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureProductScopeError,
    NStructureResearchRequest,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from app.schemas.research_overlays import (
    JdjStrategyHistoricalActionOut,
    JdjStrategyHistoricalRequestOut,
    JdjStrategyHistoricalResponse,
    NStructureBandOut,
    NStructureBandPolicyOut,
    NStructureBandRequestOut,
    NStructureBandResponse,
)


router = APIRouter(prefix="/api/v1/market/research", tags=["market-research"])


@router.get(
    "/n-structure/bands",
    response_model=NStructureBandResponse,
)
def n_structure_historical_bands(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> NStructureBandResponse:
    if series_kind != "actual_dominant" or frequency != "5m":
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_N_STRUCTURE_BAND_REQUEST"},
        )
    try:
        request = NStructureResearchRequest(
            since=since,
            through=through,
            symbol=symbol,
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_N_STRUCTURE_BAND_REQUEST"},
        ) from None
    try:
        policy = load_n_structure_policy()
        bands = build_n_structure_research_service(
            session,
            policy=policy,
        ).range_bands(request)
    except (ActiveUniverseError, NStructurePolicyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except (
        NStructureSegmentIdentityError,
        NStructureProductScopeError,
        NStructureSourceUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    normalized_symbol = request.symbol
    if normalized_symbol is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_N_STRUCTURE_BAND_REQUEST"},
        )
    return NStructureBandResponse(
        request=NStructureBandRequestOut(
            series_kind="actual_dominant",
            symbol=normalized_symbol,
            frequency="5m",
            since=request.since,
            through=request.through,
        ),
        policy=NStructureBandPolicyOut(
            policy_id=policy.policy_id,
            formula_version=policy.formula_version,
            source_timeframe=policy.source_timeframe.value,
            research_only=policy.research_only,
        ),
        bands=[
            NStructureBandOut(
                band_id=band.band_id,
                contract=band.contract,
                segment_start_trading_day=band.segment_start_trading_day,
                completion_trading_day=band.completion_trading_day,
                direction=band.direction.value,
                role=band.role.value,
                n1_at=band.n1_at,
                completed_at=band.completed_at,
                completion_level=band.completion_level,
                lower=band.lower,
                upper=band.upper,
                first_reentered_at=band.first_reentered_at,
                invalidated_at=band.invalidated_at,
                expanded_until=band.expanded_until,
            )
            for band in bands
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
        result = build_jdj_strategy_replay_service(session).history(request)
    except JdjStrategyProfileUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code},
        ) from None
    except ActiveUniverseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
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
