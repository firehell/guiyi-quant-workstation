"""Read-only access to published Newow research results."""

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.services.newow_backtest_results import ResultStore, ResultStoreError, SeriesKey


router = APIRouter(prefix="/api/v1/newow/backtests", tags=["newow-backtests"])


def _failure(exc: ResultStoreError) -> HTTPException:
    status = {
        "BACKTEST_RUN_NOT_FOUND": 404,
        "BACKTEST_SERIES_INVALID": 422,
        "BACKTEST_CURSOR_INVALID": 422,
        "BACKTEST_PAGE_INVALID": 422,
    }.get(exc.code, 503)
    return HTTPException(status, detail={"code": exc.code})


def _store():
    try:
        store = ResultStore(os.getenv("GUIYI_NEWOW_BACKTEST_READ_DSN", ""), read_only=True)
    except ResultStoreError as exc:
        raise _failure(exc) from None
    try:
        yield store
    finally:
        store.close()


Store = Annotated[ResultStore, Depends(_store)]
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageCursor = Annotated[str | None, Query(max_length=140)]


class Attempt(BaseModel):
    run_id: str
    generation: int
    status: Literal["RUNNING", "SUCCEEDED", "FAILED"]
    error_code: str | None
    as_of_trading_day: str
    started_at: str
    finished_at: str | None


class PublishedResult(BaseModel):
    run_id: str
    as_of_trading_day: str
    qualification: Literal["QUALIFIED", "TRIAL"]
    manifest: dict
    summary: dict


class LatestResponse(BaseModel):
    result: PublishedResult | None
    last_attempt: Attempt | None


class TradeItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq: int
    physical_contract: str
    side: Literal["BUY", "SELL"]
    position_effect: Literal["OPEN", "CLOSE", "CLOSE_TODAY"]
    quantity: int
    price: str
    fee: str
    commission: str | None
    tax: str | None
    gross_pnl: str | None
    net_pnl: str | None
    entry_seq: int | None = None
    trading_day: str | None = None
    signal_bar_end: str | None = None
    signal_available_at: str | None = None
    modeled_fill_at: str | None = None
    native_order_at: str | None = None
    native_fill_event_at: str | None = None
    decision: dict | None = None


class EquityItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq: int
    trading_day: str
    equity: str
    cash: str
    margin: str
    fees: str
    unrealized_pnl: str
    drawdown: str
    kind: Literal["INITIAL", "SETTLED"] | None = None
    valuation_at: str | None = None


class TradesResponse(BaseModel):
    run_id: str
    items: list[TradeItem]
    next_cursor: str | None


class EquityResponse(BaseModel):
    run_id: str
    items: list[EquityItem]
    next_cursor: str | None


@router.get("/latest", response_model=LatestResponse)
def latest(
    product: str, strategy: str, frequency: str, research_profile_id: str, store: Store,
) -> dict:
    try:
        return store.latest(SeriesKey(product, strategy, frequency, research_profile_id))
    except ResultStoreError as exc:
        raise _failure(exc) from None


def _page(store: ResultStore, run_id: str, kind: str, limit: int, cursor: str | None) -> dict:
    try:
        return store.page(run_id, kind, limit, cursor)
    except ResultStoreError as exc:
        raise _failure(exc) from None


@router.get("/{run_id}/trades", response_model=TradesResponse)
def trades(run_id: str, store: Store, limit: PageLimit = 50, cursor: PageCursor = None) -> dict:
    return _page(store, run_id, "trades", limit, cursor)


@router.get("/{run_id}/equity", response_model=EquityResponse)
def equity(run_id: str, store: Store, limit: PageLimit = 50, cursor: PageCursor = None) -> dict:
    return _page(store, run_id, "equity", limit, cursor)
