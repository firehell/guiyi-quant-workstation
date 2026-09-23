"""Read-only persisted historical reference API."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.reference_trading.presentation import PresentationUnavailable
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.health import ForwardReferenceHealth


router = APIRouter(prefix="/api/v1/reference-trading", tags=["reference-trading"])
_query = HistoricalReferenceQuery(SessionLocal)
_health = ForwardReferenceHealth(SessionLocal)


def _keys(request: Request, allowed: frozenset[str]) -> None:
    keys = [key for key, _ in request.query_params.multi_items()]
    if set(keys) - allowed or len(keys) != len(set(keys)):
        raise HTTPException(422, detail={"code": "QUERY_INVALID"})


def _run(call):
    try:
        return call()
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
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"code": "QUERY_INVALID"}) from None


@router.get("/capabilities")
def capabilities(request: Request):
    _keys(request, frozenset())
    return _query.capabilities()


@router.get("/health")
def health(request: Request):
    _keys(request, frozenset())
    return _health.read()


@router.get("/streams")
def streams(request: Request, strategy: str, product: str, frequency: str,
            mode: str = "historical_replay"):
    _keys(request, frozenset({"strategy", "product", "frequency", "mode"}))
    return {"items": _run(lambda: _query.streams(
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
    return _run(lambda: _query.trades(
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
    return _run(lambda: _query.signals(
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
    return _run(lambda: _query.signals(
        stream_id, since=since, through=through, cutoff=cutoff,
        limit=limit, cursor=cursor, snapshot_token=snapshot,
        point_kind="indicator",
    ))


@router.get("/streams/{stream_id}/summary")
def summary(request: Request, stream_id: str, since: date, through: date,
            cutoff: datetime | None = None,
            snapshot: str | None = Query(None, max_length=2048)):
    _keys(request, frozenset({"since", "through", "cutoff", "snapshot"}))
    return _run(lambda: _query.summary(
        stream_id, since=since, through=through, cutoff=cutoff,
        snapshot_token=snapshot,
    ))
