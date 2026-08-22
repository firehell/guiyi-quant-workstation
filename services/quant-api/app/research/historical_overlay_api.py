"""Read-only HTTP projections for offline Historical Research events."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.operational_universe import ActiveUniverseError
from app.research.composition import build_n_structure_research_service
from app.research.n_structure.n_structure_policy import NStructurePolicyError
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from app.schemas.research_overlays import (
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
