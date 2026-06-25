from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.market import MarketBarsResponse, MarketWorkbenchCoverage
from app.services.market_workbench import get_market_bars, get_workbench_coverage

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/workbench/coverage", response_model=MarketWorkbenchCoverage)
def market_workbench_coverage(session: Session = Depends(get_db)) -> MarketWorkbenchCoverage:
    return get_workbench_coverage(session)


@router.get("/bars", response_model=MarketBarsResponse)
def market_bars(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    limit: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> MarketBarsResponse:
    return get_market_bars(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        start=_parse_query_datetime(start, end_of_day=False) if start else None,
        end=_parse_query_datetime(end, end_of_day=True) if end else None,
        provider=provider,
        limit=limit,
    )


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
