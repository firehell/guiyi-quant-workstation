"""Historical research API, independent of Market and legacy Newow Run storage."""

from asyncio import to_thread
from contextlib import asynccontextmanager
from datetime import date
import os
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.backtest_center.contracts import (
    BacktestError,
    Frequency,
    Key,
    RetryRequest,
    Status,
    SubmitRequest,
    TemplateRequest,
    eligibility,
)
from app.backtest_center.store import RunStore
from app.backtest_center.worker import Settings, Worker

router = APIRouter(prefix="/api/v1/backtests", tags=["backtest-center"])
_setup_lock = Lock()
_DEVELOP_ORIGINS = frozenset(f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 5175))
Offset = Annotated[int, Query(ge=0, le=1_000_000)]
Limit = Annotated[int, Query(ge=1, le=200)]


def _setup(app, settings):
    with _setup_lock:
        if getattr(app.state, "backtest_store", None) is None:
            store = RunStore(settings.path, settings.submission)
            worker = Worker(settings, store)
            worker.start()
            app.state.backtest_store = store
            app.state.backtest_worker = worker
        return app.state.backtest_store


@asynccontextmanager
async def workstation_lifespan(app):
    settings = Settings.local()
    if settings.path.is_file() or os.getenv("GUIYI_BACKTEST_STORE"):
        await to_thread(_setup, app, settings)
    try:
        yield
    finally:
        if worker := getattr(app.state, "backtest_worker", None):
            await to_thread(worker.close)
            del app.state.backtest_worker
            del app.state.backtest_store


def get_store(request: Request) -> RunStore:
    store = getattr(request.app.state, "backtest_store", None)
    return store if store is not None else _setup(request.app, Settings.local())


def require_local_write(request: Request) -> None:
    if origin := request.headers.get("origin"):
        allowed = {*_DEVELOP_ORIGINS, str(request.base_url).rstrip("/")}
        allowed.update(item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip())
        if origin.rstrip("/") not in allowed:
            raise HTTPException(403, detail={"code": "BACKTEST_ORIGIN_FORBIDDEN"})


Store = Annotated[RunStore, Depends(get_store)]
Writes = [Depends(require_local_write)]


def _error(exc: BacktestError) -> HTTPException:
    if exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif exc.code == "BACKTEST_QUEUE_FULL":
        status = 429
    else:
        status = 409
    return HTTPException(status, detail={"code": exc.code})


@router.get("/eligibility")
def combinations():
    return {"items": eligibility()}


@router.get("/templates")
def templates(store: Store):
    return {"items": store.templates()}


@router.put("/templates/{template_id}", dependencies=Writes)
def save_template(template_id: Key, body: TemplateRequest, store: Store):
    if body.config.sample_type != "historical":
        raise HTTPException(422, detail={"code": "BACKTEST_SAMPLE_TYPE_RESERVED"})
    return store.save_template(template_id, body.name, body.config)


@router.get("/runs")
def runs(
    store: Store, strategy_id: Key | None = None, product: str | None = None,
    signal_frequency: Frequency | None = None, start: date | None = None, end: date | None = None,
    status: Status | None = None, sort: Literal["net_return"] | None = None, offset: Offset = 0, limit: Limit = 50,
):
    if start and end and start > end:
        raise HTTPException(422, detail={"code": "BACKTEST_WINDOW_INVALID"})
    return store.list(
        offset=offset, limit=limit, strategy_id=strategy_id, product=product.lower() if product else None,
        signal_frequency=signal_frequency, start=start.isoformat() if start else None,
        end=end.isoformat() if end else None, status=status, sort=sort,
    )


@router.post("/runs", status_code=202, dependencies=Writes)
def submit(body: SubmitRequest, store: Store):
    if body.config.sample_type != "historical":
        raise HTTPException(422, detail={"code": "BACKTEST_SAMPLE_TYPE_RESERVED"})
    try:
        return store.submit(body.request_key, body.config.model_dump(mode="json"))
    except BacktestError as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}")
def get_run(run_id: Key, store: Store):
    run = store.get(run_id)
    if run is None:
        raise _error(BacktestError("BACKTEST_RUN_NOT_FOUND"))
    return run


@router.post("/runs/{run_id}/cancel", status_code=202, dependencies=Writes)
def cancel(run_id: Key, store: Store):
    try:
        return store.cancel(run_id)
    except BacktestError as exc:
        raise _error(exc) from None


@router.post("/runs/{run_id}/rerun", status_code=202, dependencies=Writes)
def rerun(run_id: Key, body: RetryRequest, store: Store):
    try:
        return store.rerun(run_id, body.request_key)
    except BacktestError as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/events")
def events(run_id: Key, store: Store):
    try:
        return store.events(run_id)
    except BacktestError as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/report")
def report(run_id: Key, store: Store):
    try:
        return store.report(run_id)
    except BacktestError as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/replay/{trade_id}")
def replay(run_id: Key, trade_id: Key, store: Store):
    try:
        return store.replay(run_id, trade_id)
    except BacktestError as exc:
        raise _error(exc) from None


@router.get("/runs/{run_id}/{kind}")
def rows(run_id: Key, kind: str, store: Store, offset: Offset = 0, limit: Limit = 50):
    if kind not in ("trades", "equity"):
        raise HTTPException(404, detail={"code": "BACKTEST_RESOURCE_NOT_FOUND"})
    try:
        return store.page(run_id, kind, offset, limit)
    except BacktestError as exc:
        raise _error(exc) from None
