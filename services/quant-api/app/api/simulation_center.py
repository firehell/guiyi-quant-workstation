"""Read-only SimNow evidence API. The gateway runs in a separate process."""

import os
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
import psycopg

from app.simulation_center import SIMULATION_CENTER_VERSION
from app.simulation_center.config import ACCOUNT_ALIAS
from app.simulation_center.store import SOURCE, read_workstation

router = APIRouter(prefix="/api/v1/simulations", tags=["simulation-center"])

Alias = Annotated[str | None, Query(pattern=ACCOUNT_ALIAS)]
Cursor = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}:[A-Z]+:[0-9A-Za-z_-]{1,32}$")]


@router.get("")
def workstation(account: Alias = None, before: Cursor = None):
    dsn = os.getenv("GUIYI_SIMULATION_READER_DSN")
    if before and account is None:
        raise HTTPException(422, detail={"code": "ACCOUNT_REQUIRED_FOR_CURSOR"})
    if not dsn:
        return {"version": SIMULATION_CENTER_VERSION, "source": SOURCE, "status": "NOT_CONFIGURED",
                "accounts": [], "selected": None,
                "readback": None, "equity": [], "fills": [], "next_fill": None}
    try:
        return {"version": SIMULATION_CENTER_VERSION, **read_workstation(dsn, account, before)}
    except LookupError:
        raise HTTPException(404, detail={"code": "SIMULATION_ACCOUNT_NOT_FOUND"}) from None
    except psycopg.Error:
        raise HTTPException(503, detail={"code": "SIMULATION_READ_UNAVAILABLE"}) from None
