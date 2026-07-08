from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.futures_research import FuturesResearchPanelCatalogResponse, FuturesResearchPanelResponse
from app.services.futures_research_reader import FuturesResearchReader

router = APIRouter(prefix="/api/v1/market/research", tags=["market-research"])


@router.get("/panels", response_model=FuturesResearchPanelCatalogResponse)
def list_research_panels(
    symbol: str = Query(...),
    contract: str | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelCatalogResponse:
    return FuturesResearchReader(session).list_panels(symbol=symbol, contract=contract)


@router.get("/dominant", response_model=FuturesResearchPanelResponse)
def research_dominant(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel("dominant", symbol=symbol, contract=contract, start=start, end=end)


@router.get("/ex-factor", response_model=FuturesResearchPanelResponse)
def research_ex_factor(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel("ex-factor", symbol=symbol, contract=contract, start=start, end=end)


@router.get("/trading-parameters", response_model=FuturesResearchPanelResponse)
def research_trading_parameters(
    symbol: str = Query(...),
    contract: str = Query(...),
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel(
        "trading-parameters",
        symbol=symbol,
        contract=contract,
        start=start,
        end=end,
    )


@router.get("/warehouse-stocks", response_model=FuturesResearchPanelResponse)
def research_warehouse_stocks(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel("warehouse-stocks", symbol=symbol, contract=contract, start=start, end=end)


@router.get("/roll-yield", response_model=FuturesResearchPanelResponse)
def research_roll_yield(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel("roll-yield", symbol=symbol, contract=contract, start=start, end=end)


@router.get("/contract-universe", response_model=FuturesResearchPanelResponse)
def research_contract_universe(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel("contract-universe", symbol=symbol, contract=contract, start=start, end=end)


@router.get("/continuous-contracts", response_model=FuturesResearchPanelResponse)
def research_continuous_contracts(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_panel("continuous-contracts", symbol=symbol, contract=contract, start=start, end=end)


@router.get("/member-rank", response_model=FuturesResearchPanelResponse)
def research_member_rank(
    symbol: str = Query(...),
    contract: str | None = None,
    start: date | None = None,
    end: date | None = None,
    rank_by: str = Query("volume"),
    session: Session = Depends(get_db),
) -> FuturesResearchPanelResponse:
    return FuturesResearchReader(session).get_member_rank_panel(
        symbol=symbol,
        contract=contract,
        start=start,
        end=end,
        rank_by=rank_by,
    )
