"""Read-only simulation monitor. Reading it never imports or starts TqSdk."""

from datetime import datetime, UTC, date, timedelta
import base64
import copy
import json
from fastapi import APIRouter, HTTPException, Query, Request
from guiyi_quant.tq_simulation.runtime import read_private, directory
from guiyi_quant.tq_simulation.monitor import VERSION, blank
from guiyi_quant.tq_simulation.journal import digest

router = APIRouter(prefix="/api/simulation/monitor", tags=["simulation-monitor"])


def snapshot():
    path = directory() / "monitor.json"
    if not path.exists():
        return {"overview": blank(datetime.now(UTC)), "records": []}
    try:
        value = read_private(path)
        view = value["overview"]
        records = value["records"]
        if view["version"] != VERSION or not isinstance(records, list):
            raise ValueError
        stamp = datetime.fromisoformat(view["generated_at"])
        now = datetime.now(UTC)
        if stamp.tzinfo is None or stamp > now:
            raise ValueError
        if now - stamp > timedelta(seconds=30):
            value = copy.deepcopy(value)
            view = value["overview"]
            view.update(
                status="partial",
                readback_status="stale",
                position_projection_complete=False,
            )
            if view.get("observer"):
                view["observer"].update(status="stale", opening_enabled=False)
        return value
    except Exception:
        raise HTTPException(
            503, detail={"code": "SIMULATION_SOURCE_UNAVAILABLE"}
        ) from None


def query_keys(request, allowed):
    keys = [k for k, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)) or set(keys) - set(allowed):
        raise HTTPException(422, detail={"code": "MONITOR_QUERY_INVALID"})


@router.get("/overview")
def overview(request: Request):
    query_keys(request, ())
    return snapshot()["overview"]


@router.get("/records")
def records(
    request: Request,
    kind: str = Query("all", pattern=r"^(all|signal|risk|order|fill)$"),
    product: str = Query("", pattern=r"^[A-Za-z]{0,3}$"),
    status: str = Query("", pattern=r"^[A-Z_]{0,40}$"),
    start_day: date | None = None,
    end_day: date | None = None,
    cursor: str | None = Query(None, max_length=4096),
):
    query_keys(request, ("kind", "product", "status", "start_day", "end_day", "cursor"))
    today = (
        datetime.now(UTC)
        .astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
        .date()
    )
    since = start_day or today - timedelta(days=6)
    until = end_day or today
    if since > until or (until - since).days > 93:
        raise HTTPException(422, detail={"code": "MONITOR_QUERY_INVALID"})
    value = snapshot()
    rows = [
        r
        for r in value["records"]
        if (kind == "all" or r["kind"] == kind)
        and (not product or r["product"] == product.upper())
        and (not status or r["status"] == status)
        and since
        <= datetime.fromisoformat(r["at"])
        .astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
        .date()
        <= until
    ]
    identity = digest(
        {
            "account": value["overview"].get("account"),
            "rows": rows,
            "query": [
                kind,
                product.upper(),
                status,
                since.isoformat(),
                until.isoformat(),
            ],
        }
    )
    offset = 0
    if cursor is not None:
        try:
            packet = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            if (
                set(packet) != {"snapshot", "offset"}
                or type(packet["offset"]) is not int
                or packet["offset"] < 0
            ):
                raise ValueError
            if packet["snapshot"] != identity:
                raise HTTPException(409, detail={"code": "MONITOR_SNAPSHOT_CHANGED"})
            offset = packet["offset"]
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, detail={"code": "MONITOR_QUERY_INVALID"}) from None
    page = rows[offset : offset + 100]
    next_offset = offset + len(page)
    token = (
        base64.urlsafe_b64encode(
            json.dumps({"snapshot": identity, "offset": next_offset}).encode()
        )
        .decode()
        .rstrip("=")
        if next_offset < len(rows)
        else None
    )
    return dict(
        version=VERSION,
        snapshot=identity,
        items=page,
        next_cursor=token,
        available_count=len(rows),
        coverage="complete" if value["overview"]["account"] else "unavailable",
    )


@router.get("/records/{record_id:path}")
def detail(request: Request, record_id: str):
    query_keys(request, ())
    if len(record_id) > 4096:
        raise HTTPException(422, detail={"code": "MONITOR_QUERY_INVALID"})
    value = snapshot()
    selected = next((r for r in value["records"] if r["id"] == record_id), None)
    if selected is None:
        raise HTTPException(404, detail={"code": "MONITOR_RECORD_NOT_FOUND"})
    chain = [
        r
        for r in value["records"]
        if r["id"] == record_id
        or selected.get("signal_id")
        and r.get("signal_id") == selected["signal_id"]
        or selected.get("order_id")
        and r.get("order_id") == selected["order_id"]
    ]
    return dict(
        version=VERSION,
        snapshot=digest(value["records"]),
        selected=selected,
        chain=sorted(chain, key=lambda r: (r["at"], r["id"])),
    )
