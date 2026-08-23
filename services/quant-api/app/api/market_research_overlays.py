"""Source-specific read-only Historical Research Overlay HTTP API."""

from __future__ import annotations

from datetime import date
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import ActiveUniverseError
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.composition import build_subing_historical_signal_service
from app.market_data.subing_historical_signal_service import (
    SubingHistoricalSignalRequest,
    SubingHistoricalSignalSegmentIdentityError,
    SubingHistoricalSignalSourceUnavailableError,
)
from app.schemas.research_overlays import (
    SubingHistoricalSignalEventOut,
    SubingHistoricalSignalRequestOut,
    SubingHistoricalSignalResponse,
)


router = APIRouter(prefix="/api/v1/market/research", tags=["market-research"])


@router.get("/subing/history", response_model=SubingHistoricalSignalResponse)
def subing_historical_signals(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> SubingHistoricalSignalResponse:
    try:
        request = SubingHistoricalSignalRequest(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            frequency=cast(BarFrequency, frequency),
            since=since,
            through=through,
        )
        result = build_subing_historical_signal_service(session).history(request)
    except SubingCalibrationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except ActiveUniverseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SUBING_HISTORICAL_REQUEST"},
        ) from None
    except (
        SubingHistoricalSignalSegmentIdentityError,
        SubingHistoricalSignalSourceUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    return SubingHistoricalSignalResponse(
        request=SubingHistoricalSignalRequestOut(
            series_kind=result.request.series_kind.value,
            symbol=result.request.symbol,
            frequency=result.request.frequency.value,
            since=result.request.since,
            through=result.request.through,
        ),
        events=[
            SubingHistoricalSignalEventOut(
                event_id=event.event_id,
                bar_end=event.bar_end,
                trading_day=event.trading_day,
                contract=event.contract,
                segment_start_trading_day=event.segment_start_trading_day,
                direction=event.direction.value,
                trigger_timeframe=event.trigger_timeframe.value,
                lower_tf_confirmation=event.lower_tf_confirmation,
            )
            for event in result.events
        ],
    )
