"""Strategy Center API. Requests only read existing domain projections."""

from asyncio import gather
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.db.session import SessionLocal
from app.market_data.market_foundation_scope import formal_tick_requested
from app.services.newow_reference_mode import market_reference_receipts_only
from app.strategy_center import htdy, newow, subing
from app.strategy_center.catalog import CATALOG, DOMAINS, VERSION, Strategy
from app.strategy_center.reads import DomainReads, projection

router = APIRouter(prefix="/api/v1/strategies", tags=["strategy-center"])
_reads = DomainReads()

Product = Annotated[str | None, Query(pattern=r"^[a-z]{1,8}$")]
Frequency = Annotated[str | None, Query(pattern=r"^(5m|15m|30m|60m|1d|1w)$")]


def definition(strategy_id):
    strategy = CATALOG.get(strategy_id)
    if strategy is None:
        raise HTTPException(404, detail={"code": "STRATEGY_NOT_FOUND"})
    return strategy


def _newow(request):
    sessions = getattr(request.app.state, "market_foundation_reference_sessions", None)
    return newow.Newow(
        sessions if sessions is not None else SessionLocal,
        receipt_only=sessions is not None or market_reference_receipts_only(),
        formal=formal_tick_requested(),
    )


def _runtime_readers(request) -> dict[str, tuple[str, Callable]]:
    return {
        "newow": (newow.RUNTIME, _newow(request).runtime),
        "htdy": (htdy.SOURCE, htdy.runtime),
        "subing": (subing.SOURCE, subing.runtime),
    }


@router.get("")
async def catalog():
    return {"version": VERSION, "items": tuple(CATALOG.values())}


@router.get("/runtime")
async def runtime_overview(request: Request):
    readers = _runtime_readers(request)
    values = await gather(*(_reads.run(domain, *readers[domain]) for domain in DOMAINS))
    return {"version": VERSION, "read_at": datetime.now(UTC), "domains": dict(zip(DOMAINS, values, strict=True))}


@router.get("/{strategy_id}")
def detail(request: Request, strategy_id: str):
    strategy = definition(strategy_id)
    match strategy.domain:
        case "newow":
            try:
                value = _newow(request).overview(strategy)
            except (OSError, ValueError):
                value = projection(newow.CAPABILITY, "UNAVAILABLE", diagnostic="NEWOW_CAPABILITY_UNAVAILABLE")
        case "htdy":
            value = htdy.overview()
        case "subing":
            value = subing.overview()
    return {"version": VERSION, "strategy": strategy, **value}


@router.get("/{strategy_id}/runtime")
async def runtime(request: Request, strategy_id: str):
    strategy = definition(strategy_id)
    return await _reads.run(strategy.domain, *_runtime_readers(request)[strategy.domain])


def _selection(strategy: Strategy, product, frequency):
    if (product is None) != (frequency is None) or strategy.domain != "newow" and product is not None:
        raise HTTPException(422, detail={"code": "STRATEGY_SELECTION_INVALID"})


def _selected(reader, strategy, product, frequency, resource):
    source = newow.BINDINGS if resource == "bindings" else newow.EVIDENCE
    if product and product not in reader.capability(strategy).get(frequency, ()):
        return projection(source, "UNSUPPORTED", diagnostic="STRATEGY_CAPABILITY_UNAVAILABLE")
    return getattr(reader, resource)(strategy, product, frequency)


async def _resource(request, strategy, product, frequency, resource):
    _selection(strategy, product, frequency)
    if strategy.domain == "newow":
        source = newow.BINDINGS if resource == "bindings" else newow.EVIDENCE
        return await _reads.run(strategy.domain, source, _selected, _newow(request),
                                strategy, product, frequency, resource)
    adapter = htdy if strategy.domain == "htdy" else subing
    return await _reads.run(strategy.domain, adapter.SOURCE, getattr(adapter, resource))


@router.get("/{strategy_id}/bindings")
async def bindings(request: Request, strategy_id: str, product: Product = None, frequency: Frequency = None):
    return await _resource(request, definition(strategy_id), product, frequency, "bindings")


@router.get("/{strategy_id}/evidence")
async def evidence(request: Request, strategy_id: str, product: Product = None, frequency: Frequency = None):
    return await _resource(request, definition(strategy_id), product, frequency, "evidence")
