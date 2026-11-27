"""Immutable reference audit reads; official history pages add Canonical source admission."""

from __future__ import annotations

from datetime import date, datetime
from asyncio import gather
from functools import partial

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.db.session import SessionLocal
from app.market_data.product_retirement import ProductRetiredError
from app.reference_trading.presentation import PresentationUnavailable
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.health import ForwardReferenceHealth, read_completed_recording_endpoints


router = APIRouter(prefix="/api/v1/reference-trading", tags=["reference-trading"])
_query = HistoricalReferenceQuery(SessionLocal)
_health = ForwardReferenceHealth(
    SessionLocal,
    endpoint_reader=partial(read_completed_recording_endpoints, session_factory=SessionLocal),
)


def _bound_market_sessions(request: Request):
    return getattr(request.app.state, "market_foundation_reference_sessions", None)


def _reader(request: Request) -> HistoricalReferenceQuery:
    factory = _bound_market_sessions(request)
    return _query if factory is None else HistoricalReferenceQuery(factory, market_scope=True)


def _only_existing_runtime(request: Request) -> None:
    if _bound_market_sessions(request) is not None:
        raise HTTPException(status_code=404, detail={"code": "MARKET_REFERENCE_NOT_ENABLED"})


def _keys(request: Request, allowed: frozenset[str]) -> None:
    keys = [key for key, _ in request.query_params.multi_items()]
    if set(keys) - allowed or len(keys) != len(set(keys)):
        raise HTTPException(422, detail={"code": "QUERY_INVALID"})


def _run(call):
    try:
        return call()
    except ProductRetiredError as exc:
        raise HTTPException(410, detail={"code": exc.code}) from None
    except QueryConflict as exc:
        code = exc.code
        status = (
            404 if code == "STREAM_NOT_FOUND" else
            422 if code in {"QUERY_INVALID", "MODE_NOT_AVAILABLE", "TOKEN_INVALID"} else
            503 if code in {"NOT_BUILT", "STALE_INVALID", "QUERY_BUDGET_EXCEEDED", "PRESENTATION_NOT_MATERIALIZED"} else 409
        )
        raise HTTPException(status, detail={"code": code}) from None
    except PresentationUnavailable as exc:
        raise HTTPException(503, detail={"code": str(exc)}) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "REFERENCE_SCHEMA_UNAVAILABLE"}) from None
    except OSError:
        raise HTTPException(503, detail={"code": "MARKET_REFERENCE_SECTION_UNAVAILABLE"}) from None
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"code": "QUERY_INVALID"}) from None


@router.get("/capabilities")
def capabilities(request: Request):
    _keys(request, frozenset())
    return _reader(request).capabilities()


@router.get("/health")
async def health(request: Request):
    _only_existing_runtime(request)
    _keys(request, frozenset())
    from app.reference_trading.inbox_protocol import read_receiving_health
    detail, receiving = await gather(
        run_in_threadpool(_health.read),
        run_in_threadpool(read_receiving_health, SessionLocal),
    )
    return JSONResponse({**detail, "receiving": jsonable_encoder(receiving)})


@router.get("/health/summary")
def health_summary(request: Request):
    _only_existing_runtime(request)
    _keys(request, frozenset())
    from app.reference_trading.health import read_worker_health_summary
    from app.reference_trading.inbox_protocol import read_receiving_health

    try:
        return {
            "worker": read_worker_health_summary(),
            "receiving": read_receiving_health(SessionLocal),
        }
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        raise HTTPException(503, detail={"code": "REFERENCE_HEALTH_UNAVAILABLE"}) from None


@router.get("/streams")
def streams(request: Request, strategy: str, product: str, frequency: str,
            mode: str = "historical_replay"):
    _keys(request, frozenset({"strategy", "product", "frequency", "mode"}))
    return {"items": _run(lambda: _reader(request).streams(
        strategy=strategy, product=product, frequency=frequency, mode=mode,
    ))}


_VIEW_FIELDS = frozenset({"since", "through", "cutoff", "limit", "cursor", "snapshot"})


@router.get("/streams/{stream_id}/trades")
def trades(request: Request, stream_id: str, since: date, through: date,
           cutoff: datetime | None = None, limit: int = Query(50, ge=1, le=200),
           cursor: str | None = Query(None, max_length=2048),
           snapshot: str | None = Query(None, max_length=2048)):
    _keys(request, _VIEW_FIELDS)
    if cursor is not None and snapshot is None:
        raise HTTPException(409, detail={"code": "CURSOR_CONFLICT"})
    return _run(lambda: _reader(request).trades(
        stream_id, since=since, through=through, cutoff=cutoff,
        limit=limit, cursor=cursor, snapshot_token=snapshot,
    ))


@router.get("/streams/{stream_id}/signals")
def signals(request: Request, stream_id: str, since: date, through: date,
            cutoff: datetime | None = None, limit: int = Query(50, ge=1, le=200),
            cursor: str | None = Query(None, max_length=2048),
            snapshot: str | None = Query(None, max_length=2048)):
    _keys(request, _VIEW_FIELDS)
    if cursor is not None and snapshot is None:
        raise HTTPException(409, detail={"code": "CURSOR_CONFLICT"})
    return _run(lambda: _reader(request).signals(
        stream_id, since=since, through=through, cutoff=cutoff,
        limit=limit, cursor=cursor, snapshot_token=snapshot,
        point_kind="display_signal",
    ))


@router.get("/streams/{stream_id}/indicators")
def indicators(request: Request, stream_id: str, since: date, through: date,
               cutoff: datetime | None = None, limit: int = Query(50, ge=1, le=200),
               cursor: str | None = Query(None, max_length=2048),
               snapshot: str | None = Query(None, max_length=2048)):
    _keys(request, _VIEW_FIELDS)
    if cursor is not None and snapshot is None:
        raise HTTPException(409, detail={"code": "CURSOR_CONFLICT"})
    return _run(lambda: _reader(request).signals(
        stream_id, since=since, through=through, cutoff=cutoff,
        limit=limit, cursor=cursor, snapshot_token=snapshot,
        point_kind="indicator",
    ))


@router.get("/streams/{stream_id}/panel")
def forward_reference_panel(request: Request, stream_id: str, since: date, through: date,
                            cutoff: datetime | None = None):
    from app.reference_trading.forward_panel import forward_panel
    _keys(request, frozenset({"since", "through", "cutoff"}))
    return _run(lambda: forward_panel(_reader(request), stream_id, since=since, through=through, cutoff=cutoff))


@router.get("/streams/{stream_id}/summary")
def summary(request: Request, stream_id: str, since: date, through: date,
            cutoff: datetime | None = None,
            snapshot: str | None = Query(None, max_length=2048)):
    _keys(request, frozenset({"since", "through", "cutoff", "snapshot"}))
    return _run(lambda: _reader(request).summary(
        stream_id, since=since, through=through, cutoff=cutoff,
        snapshot_token=snapshot,
    ))


@router.get("/newow/after-close")
def newow_after_close(request: Request, product: str, strategy: str, frequency: str):
    from app.services.newow_reference_mode import market_foundation_isolated

    factory = _bound_market_sessions(request)
    if factory is None:
        if not market_foundation_isolated():
            raise HTTPException(status_code=404, detail={"code": "MARKET_REFERENCE_NOT_ENABLED"})
        from app.db.session import engine
        from app.market_data.composition import canonical_root
        from app.market_data.market_archive import require_isolated_archive
        from app.redis_connections import REDIS_URL
        try:
            require_isolated_archive(engine.url, REDIS_URL, canonical_root())
        except (OSError, ValueError):
            raise HTTPException(status_code=503, detail={"code": "MARKET_REFERENCE_NOT_ENABLED"}) from None
        factory = SessionLocal
    _keys(request, frozenset({"product", "strategy", "frequency"}))
    from app.market_data.market_foundation_scope import formal_tick_requested
    from app.market_data.newow.market_reference_after_close import latest_formal_reference, latest_reference

    resolve = latest_formal_reference if formal_tick_requested() else latest_reference
    return {"result": _run(lambda: resolve(product, strategy, frequency, session_factory=factory))}


@router.get("/newow/after-close/presentation")
def newow_after_close_presentation(
    request: Request, stream_id: str, since: date, through: date, cutoff: datetime,
    snapshot: str = Query(..., max_length=2048),
    bar_from: datetime = Query(...), bar_through: datetime = Query(...),
):
    if _bound_market_sessions(request) is None:
        raise HTTPException(status_code=404, detail={"code": "MARKET_REFERENCE_NOT_ENABLED"})
    _keys(request, frozenset({"stream_id", "since", "through", "cutoff", "snapshot", "bar_from", "bar_through"}))
    from app.market_data.newow.market_reference_after_close import present_saved_chart
    return _run(lambda: present_saved_chart(
        _reader(request), stream_id, since=since, through=through, cutoff=cutoff,
        snapshot=snapshot, bar_from=bar_from, bar_through=bar_through,
    ))


@router.get("/newow/after-close/section")
def newow_after_close_section(request: Request, product: str, strategy: str, frequency: str,
                              section: str, component: str | None = None):
    factory = _bound_market_sessions(request)
    sandbox = getattr(request.app.state, "market_foundation_section_root", None)
    if sandbox is None and factory is not None:
        from app.market_data.market_archive import formal_archive_root
        from app.market_data.market_foundation_scope import formal_tick_requested

        if formal_tick_requested():
            try:
                sandbox = formal_archive_root()
            except (OSError, ValueError):
                raise HTTPException(503, detail={"code": "MARKET_REFERENCE_SECTION_UNAVAILABLE"}) from None
    if factory is None or sandbox is None:
        raise HTTPException(status_code=404, detail={"code": "MARKET_REFERENCE_NOT_ENABLED"})
    _keys(request, frozenset({"product", "strategy", "frequency", "section", "component"}))
    if section not in {"auxiliary", "comparator"} or (component is None) != (section == "comparator"):
        raise HTTPException(status_code=422, detail={"code": "QUERY_INVALID"})
    from app.market_data.market_foundation_scope import formal_tick_requested
    from app.market_data.newow.market_reference_after_close import latest_formal_reference, latest_reference
    from app.market_data.newow.market_reference_sections import saved_section

    def read():
        formal = formal_tick_requested()
        resolve = latest_formal_reference if formal else latest_reference
        reference = resolve(product, strategy, frequency, session_factory=factory)
        if reference is None:
            return {"status": "pending", "receipt": None, "result": None, "chart": None}
        try:
            result = saved_section(sandbox, reference, strategy=strategy, frequency=frequency,
                                   section=section, component=component)
            if formal and result["status"] == "ready" and result["receipt"] != reference["receipt"]:
                return {"status": "pending", "receipt": None, "result": None, "chart": None}
            return result
        except (OSError, ValueError):
            raise HTTPException(503, detail={"code": "MARKET_REFERENCE_SECTION_UNAVAILABLE"}) from None
    return _run(read)


@router.get("/newow/matrix")
def newow_matrix(request: Request):
    _only_existing_runtime(request)
    _keys(request, frozenset())
    from app.market_data.operational_universe import load_operational_products
    from app.reference_trading.recording_matrix import newow_recording_matrix

    products = tuple(product.lower() for product in load_operational_products())
    return _run(lambda: newow_recording_matrix(products, _health.read(products=products)))


@router.get("/newow/messages")
def newow_messages(request: Request, since: date, through: date, product: str | None = None,
                   strategy: str | None = None, frequency: str | None = None,
                   limit: int = Query(500, ge=1, le=500)):
    from app.reference_trading.messages import read_messages
    _keys(request, frozenset({"since", "through", "product", "strategy", "frequency", "limit"}))
    factory = _bound_market_sessions(request)

    def read():
        products = None
        if factory is not None:
            from app.market_data.operational_universe import load_operational_products
            from app.market_data.product_retirement import assert_not_retired

            if product is not None:
                assert_not_retired(product)
            products = load_operational_products()
        return read_messages(factory or SessionLocal, since=since, through=through, product=product,
                             strategy=strategy, frequency=frequency, limit=limit, market_products=products)

    return _run(read)
