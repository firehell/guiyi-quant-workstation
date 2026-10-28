"""Local financial monitor: GET only, no SDK, login, recovery or execution calls."""

from datetime import datetime, UTC, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from app.core.env import PROJECT_ROOT
from guiyi_quant.simnow_execution.monitor import MonitorReader, MonitorError
from guiyi_quant.simnow_execution.settings import load_settings

router = APIRouter(prefix="/api/simnow/monitor", tags=["simnow-monitor"])
MONITOR_SOURCE_CONFIG = Path.home() / 'Library/Application Support/GuiyiQuant/simnow-monitor.private.json'


def reader():
    # Publish this exact private binding only after the observe host is verified.
    # Read per request so promotion does not restart the market API.
    if MONITOR_SOURCE_CONFIG.exists() or MONITOR_SOURCE_CONFIG.is_symlink():
        try:
            settings = load_settings(MONITOR_SOURCE_CONFIG)
            if settings.schema != 2 or settings.mode != 'observe' or not settings.enabled:
                raise ValueError('MONITOR_OBSERVE_BINDING_REQUIRED')
            return MonitorReader(settings.state_root)
        except Exception:
            raise HTTPException(503, detail={'code': 'MONITOR_SOURCE_UNAVAILABLE'}) from None
    return MonitorReader(
        Path(
            os.environ.get(
                "GUIYI_SIMNOW_MONITOR_ROOT",
                str(PROJECT_ROOT / "output/simnow-controlled"),
            )
        )
    )


def query_keys(request, allowed):
    keys = [k for k, _ in request.query_params.multi_items()]
    if set(keys) - set(allowed) or len(keys) != len(set(keys)):
        raise HTTPException(422, detail={"code": "MONITOR_QUERY_INVALID"})


@router.get("/overview")
def overview(request: Request):
    query_keys(request, ())
    return reader().overview(datetime.now(UTC))


@router.get("/records")
def records(
    request: Request,
    kind: Literal["all", "signal", "risk", "order", "fill"] = "all",
    product: str = Query("", pattern=r"^[A-Za-z]{0,3}$"),
    status: str = Query("", pattern=r"^[A-Z_]{0,40}$"),
    start_day: date | None = None,
    end_day: date | None = None,
    cursor: str | None = Query(None, max_length=4096),
):
    query_keys(request, ("kind", "product", "status", "start_day", "end_day", "cursor"))
    today = datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).date()
    since = start_day or today - timedelta(days=6)
    until = end_day or today
    if since > until or (until - since).days > 93:
        raise HTTPException(422, detail={"code": "MONITOR_QUERY_INVALID"})
    try:
        return reader().records(
            datetime.now(UTC),
            kind=kind,
            product=product,
            status=status,
            start_day=since,
            end_day=until,
            cursor=cursor,
        )
    except MonitorError as exc:
        code = str(exc)
        raise HTTPException(
            409 if code == "MONITOR_SNAPSHOT_CHANGED" else 503,
            detail={
                "code": code
                if code in ("MONITOR_SNAPSHOT_CHANGED", "MONITOR_QUERY_INVALID")
                else "MONITOR_SOURCE_UNAVAILABLE"
            },
        ) from None


@router.get("/records/{identity}")
def detail(request: Request, identity: str):
    import re

    query_keys(request, ())
    if re.fullmatch(r"[a-f0-9]{64}", identity) is None:
        raise HTTPException(422, detail={"code": "MONITOR_RECORD_ID_INVALID"})
    try:
        return reader().detail(datetime.now(UTC), identity)
    except MonitorError as exc:
        raise HTTPException(
            404 if str(exc) == "MONITOR_RECORD_NOT_FOUND" else 503,
            detail={
                "code": "MONITOR_RECORD_NOT_FOUND"
                if str(exc) == "MONITOR_RECORD_NOT_FOUND"
                else "MONITOR_SOURCE_UNAVAILABLE"
            },
        ) from None
