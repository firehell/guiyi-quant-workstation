"""Local financial monitor: GET only, no SDK, login, recovery or execution calls."""

from datetime import datetime, UTC, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import os
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from app.core.env import PROJECT_ROOT
from guiyi_quant.simnow_execution.monitor import MonitorReader, MonitorError

router = APIRouter(prefix="/api/simnow/monitor", tags=["simnow-monitor"])


def reader():
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
