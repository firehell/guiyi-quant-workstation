from datetime import date, datetime, time
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.market import (
    DominantContractListResponse,
    LiveMarketBarsResponse,
    LiveTargetContractsResponse,
    MarketBarsResponse,
    MarketCoverageSummary,
    MarketWorkbenchCoverage,
)
from app.services.live_market_reader import LiveMarketReader, SUPPORTED_LIVE_PERIODS
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.market_dominant_reader import DominantContractReader, QuoteContractError
from app.services.market_workbench import get_market_bars, get_workbench_coverage

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/workbench/coverage", response_model=Union[MarketWorkbenchCoverage, MarketCoverageSummary])
def market_workbench_coverage(
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    include_paths: bool = False,
    summary: bool = False,
    session: Session = Depends(get_db),
) -> MarketWorkbenchCoverage | MarketCoverageSummary:
    return get_workbench_coverage(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        include_paths=include_paths,
        summary=summary,
    )


@router.get("/dominants", response_model=DominantContractListResponse)
def market_dominants(
    exchange: str | None = None,
    quote_ready: bool | None = None,
    search: str | None = None,
    symbol: str | None = None,
    session: Session = Depends(get_db),
) -> DominantContractListResponse:
    return DominantContractReader(session).list_dominants(
        exchange=exchange,
        quote_ready=quote_ready,
        search=search,
        symbol=symbol,
    )


@router.get("/live/targets", response_model=LiveTargetContractsResponse)
def live_market_targets(trade_date: date | None = None, session: Session = Depends(get_db)) -> dict:
    return LiveTargetContractResolver(session).list_targets(trade_date=trade_date)


@router.get("/live/coverage", response_model=Union[MarketWorkbenchCoverage, MarketCoverageSummary])
def live_market_coverage(
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    include_paths: bool = False,
    summary: bool = False,
    session: Session = Depends(get_db),
) -> MarketWorkbenchCoverage | MarketCoverageSummary:
    return LiveMarketReader(session).get_coverage(
        symbol=symbol,
        contract=contract,
        period=period,
        include_paths=include_paths,
        summary=summary,
    )


@router.get("/live/bars", response_model=LiveMarketBarsResponse)
def live_market_bars(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    source_mode: str | None = None,
    limit: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> LiveMarketBarsResponse:
    if period not in SUPPORTED_LIVE_PERIODS:
        raise HTTPException(status_code=422, detail=f"unsupported live market period: {period}")
    return LiveMarketReader(session).get_bars(
        symbol=symbol,
        contract=contract,
        period=period,
        start=_parse_query_datetime(start, end_of_day=False) if start else None,
        end=_parse_query_datetime(end, end_of_day=True) if end else None,
        provider=provider,
        source_mode=source_mode,
        limit=limit,
    )


@router.get("/bars", response_model=MarketBarsResponse)
def market_bars(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    data_role: str | None = None,
    quote_mode: bool = Query(default=False),
    allow_continuous: bool = Query(default=False),
    tail: bool = Query(default=True),
    limit: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> MarketBarsResponse:
    try:
        return get_market_bars(
            session,
            symbol=symbol,
            contract=contract,
            period=period,
            start=_parse_query_datetime(start, end_of_day=False) if start else None,
            end=_parse_query_datetime(end, end_of_day=True) if end else None,
            provider=provider,
            data_role=data_role,
            limit=limit,
            quote_mode=quote_mode,
            allow_continuous=allow_continuous,
            tail=tail,
        )
    except QuoteContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_query_datetime(value: str, end_of_day: bool) -> datetime:
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid datetime: {value}") from exc
    return parsed.replace(tzinfo=None)
