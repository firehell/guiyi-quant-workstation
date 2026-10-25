"""Unified read-only bounded history; no event creation or transport calls."""

from datetime import UTC, date, datetime
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app.alerts.history import AlertHistoryQuery, read_alert_history
from app.alerts.models import AlertEvent
from app.api.alerts import _event_outs
from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.product_taxonomy import load_product_taxonomy
from app.market_messages import MessageCursorError
from app.reference_trading.messages import FREQUENCIES, read_messages
from app.services.message_source_scope import read_message_scope
from app.services.message_snapshots import MessageSnapshots, MessageSnapshotBudgetError
from app.schemas.alerts import AlertRuleCode

router = APIRouter(prefix="/api/market", tags=["market"])
ALERT_CAP = 5000
_snapshots = MessageSnapshots()


@router.get("/messages")
def market_messages(
    request: Request,
    start_day: date,
    end_day: date,
    source: Literal["all", "alert", "newow"] = "all",
    symbol: str | None = Query(None, pattern=r"^[a-zA-Z]{1,8}$"),
    rule_code: AlertRuleCode | None = None,
    strategy: Literal["trend", "oscillation", "main_rise", "dual_fusion"] | None = None,
    frequency: Literal["1m", "5m", "15m", "30m", "60m", "1d", "1w"] | None = None,
    search: str = Query("", max_length=80),
    cursor: str | None = Query(None, max_length=4096),
    resume_count: int = Query(0, ge=0, le=300),
):
    allowed = {
        "start_day",
        "end_day",
        "source",
        "symbol",
        "rule_code",
        "strategy",
        "frequency",
        "search",
        "cursor",
        "resume_count",
    }
    keys = [key for key, _ in request.query_params.multi_items()]
    if (
        set(keys) - allowed
        or len(keys) != len(set(keys))
        or start_day > end_day
        or (end_day - start_day).days >= 366
        or (source != "alert" and (end_day - start_day).days > 93)
        or (rule_code and source != "alert")
        or (strategy and source != "newow")
        or (cursor is not None and resume_count != 0)
    ):
        raise HTTPException(422, detail={"code": "MESSAGE_QUERY_INVALID"})
    identity = {
        "start_day": start_day.isoformat(),
        "end_day": end_day.isoformat(),
        "source": source,
        "symbol": symbol.lower() if symbol else None,
        "rule_code": rule_code,
        "strategy": strategy,
        "frequency": frequency,
        "search": search.strip().lower(),
    }
    if cursor is not None:
        try:
            result = _snapshots.read(cursor, identity)
            previous = result["sources"].get("newow")
            if (
                previous
                and previous["status"] == "ready"
                and frequency in (None, *FREQUENCIES)
            ):
                scope = read_message_scope(
                    SessionLocal,
                    product=identity["symbol"],
                    strategy=strategy,
                    frequency=frequency,
                )
                digest = hashlib.sha256(json.dumps(scope).encode()).hexdigest()
                if digest != previous["revision_hash"]:
                    raise MessageCursorError
            return result
        except Exception:  # noqa: BLE001 - failed identity proof invalidates snapshot
            raise HTTPException(
                409, detail={"code": "MESSAGE_SNAPSHOT_STALE", "refresh_required": True}
            ) from None
    snapshot = {"cutoff": datetime.now(UTC).isoformat(), "alert_max_id": None}
    cutoff = datetime.fromisoformat(snapshot["cutoff"])

    rows: list[dict] = []
    sources: dict = {}
    if source != "newow":
        try:
            with (
                SessionLocal() as session,
                readonly_transaction(session, timeout_seconds=20),
            ):
                highwater = snapshot["alert_max_id"]
                if highwater is None:
                    highwater = session.scalar(select(func.max(AlertEvent.id))) or 0
                    snapshot["alert_max_id"] = highwater
                before = None
                loaded = []
                scan_batches = 0
                while True:
                    page = read_alert_history(
                        session,
                        AlertHistoryQuery(
                            start_day,
                            end_day,
                            identity["symbol"],
                            rule_code,
                            min(500, ALERT_CAP - len(loaded)),
                            before,
                            frequency=frequency,
                            max_event_id=highwater,
                        ),
                    )
                    scan_batches += 1
                    loaded.extend(page.items)
                    before = page.next_before
                    if not before or len(loaded) >= ALERT_CAP:
                        break
                rows.extend(
                    {
                        "source": "alert",
                        "id": str(item.id),
                        "bar_end": item.bar_end.isoformat(),
                        "symbol": item.symbol,
                        "event": item.model_dump(mode="json"),
                    }
                    for item in _event_outs(session, tuple(loaded))
                )
                sources["alert"] = {
                    "status": "ready",
                    "truncated": bool(before),
                    "limit": ALERT_CAP,
                    "scanned_count": len(loaded),
                    "scan_batches": scan_batches,
                    "window_days": 366,
                }
        except Exception:  # noqa: BLE001 - failure must not expose database facts
            sources["alert"] = {
                "status": "unavailable",
                "truncated": False,
                "limit": ALERT_CAP,
            }
    if source != "alert":
        try:
            page = (
                read_messages(
                    SessionLocal,
                    since=start_day,
                    through=end_day,
                    product=identity["symbol"],
                    strategy=strategy,
                    frequency=frequency,
                    observed_before=cutoff,
                )
                if frequency in (None, *FREQUENCIES)
                else {"items": [], "truncated": False}
            )
            rows.extend(
                {
                    "source": "newow",
                    "id": item["id"],
                    "bar_end": item["bar_end"],
                    "symbol": item["symbol"],
                    "event": item,
                }
                for item in page["items"]
            )
            sources["newow"] = {
                "status": "ready",
                "truncated": page["truncated"],
                "limit": 500,
                "scanned_count": len(page["items"]),
                "window_days": 93,
                "excluded_streams": page.get("excluded_streams", 0),
                "scope": "ready_forward_streams_only",
                "revision_hash": hashlib.sha256(
                    json.dumps(page.get("revision_snapshot", [])).encode()
                ).hexdigest(),
            }
        except Exception:  # noqa: BLE001 - unavailable source remains explicit
            sources["newow"] = {
                "status": "unavailable",
                "truncated": False,
                "limit": 500,
            }
    if identity["search"]:
        try:
            names = load_product_taxonomy()
        except Exception:  # noqa: BLE001 - cannot claim full-name search without directory
            raise HTTPException(
                503, detail={"code": "MESSAGE_SEARCH_UNAVAILABLE"}
            ) from None
        rows = [
            row
            for row in rows
            if identity["search"]
            in f"{row['symbol']} {names[row['symbol']].name if row['symbol'] in names else ''} {row['event'].get('contract') or ''}".lower()
        ]
    try:
        return _snapshots.create(
            rows, sources, identity, snapshot, resume_count=resume_count
        )
    except MessageSnapshotBudgetError:
        raise HTTPException(
            422, detail={"code": "MESSAGE_QUERY_BUDGET_EXCEEDED"}
        ) from None
    except MessageCursorError:
        raise HTTPException(
            409, detail={"code": "MESSAGE_SNAPSHOT_STALE", "refresh_required": True}
        ) from None
