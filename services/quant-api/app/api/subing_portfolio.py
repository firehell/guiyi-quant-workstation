"""Read committed portfolio snapshots without running the model in HTTP requests."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.new_subing_research.store import _read_file, _safe_root
from app.private_settings import read_private_settings_content
from app.subing_model.store import ModelStore, events, runs
from app.subing_portfolio_paths import ACTIVE_PORTFOLIO, HEARTBEAT, HISTORY, DB_PATH
from app.subing_portfolio_journal import KIND, LEGACY_KIND
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS, PORTFOLIO_PRODUCTS, portfolio_policy

router = APIRouter(prefix="/api/v1/subing-portfolio", tags=["subing-portfolio"])


def read_registration(path):
    if not path.exists() and not path.is_symlink():
        return None
    return json.loads(read_private_settings_content(path))


def verified_scope(policy):
    products = tuple(policy.get("products", PORTFOLIO_PRODUCTS))
    if policy != portfolio_policy(products):
        raise ValueError("PORTFOLIO_POLICY_INVALID")
    return products


def project(result, *, products, status, **metadata):
    accounts = result["accounts"]
    charts = metadata.pop("charts", {})
    by_product = {}
    rows = []
    fields = ("contract", "valuation_at", "status", "summary", "open_layers", "pending",
              "latest_decision", "decision_state")
    for product in EXPANDED_PORTFOLIO_PRODUCTS:
        contracts = [
            {**{key: row.get(key) for key in fields},
             **{key: row.get(key, [])[-100:] for key in ("fills", "decisions_with_actions")}}
            for contract, row in accounts.items() if contract[:-4].lower() == product
        ]
        contracts.sort(key=lambda row: (row.get("valuation_at") or "", row["contract"]), reverse=True)
        rows.append(dict(product=product, enabled=product in products, accounts=contracts))
        if contracts:
            contract = contracts[0]["contract"]
            by_product[product] = charts.get(contract, [])
    day = result.get("daily", {}).get(metadata.get("trading_day"))
    day_net = str(Decimal(day["equity"]) - Decimal(day["day_start"])) if day else None
    return dict(
        **metadata,
        status=status,
        charts=by_product,
        day_net=day_net,
        products=rows,
        account={key: value for key, value in result.items() if key not in ("accounts", "risk_records")},
        auto_order=False,
    )


@router.get("/status")
def status():
    store = None
    try:
        active = read_registration(ACTIVE_PORTFOLIO)
        if active is None:
            heartbeat = read_registration(HEARTBEAT) or {}
            if heartbeat.get("run_id") is None and heartbeat.get("at"):
                seen_at = datetime.fromisoformat(heartbeat["at"])
                fresh = 0 <= (datetime.now(UTC) - seen_at).total_seconds() < 90
                return project({"accounts": {}}, products=(),
                    status=heartbeat["status"] if fresh else "STALE_OR_STOPPED",
                    worker_code=heartbeat.get("code"), worker_at=seen_at,
                    next_open=heartbeat.get("next_open") if fresh else None, run_id=None)
            return project({"accounts": {}}, products=(), status="NOT_STARTED", worker_code=None, run_id=None)
        run_id = active["run_id"]
        store = ModelStore(read_private_settings_content(DB_PATH).decode())
        with Session(store.engine, autoflush=False) as session, readonly_transaction(
            session, timeout_seconds=5
        ) as connection:
            row = connection.execute(
                select(runs.c.identity, runs.c.sequence, runs.c.state, events.c.payload)
                .select_from(runs.outerjoin(events, (runs.c.run_id == events.c.run_id) &
                                           (runs.c.sequence == events.c.sequence)))
                .where(runs.c.run_id == run_id)
            ).one()
        identity, sequence, state, last = row
        if identity["kind"] not in (KIND, LEGACY_KIND) or state["kind"] != identity["kind"] or state["sequence"] != sequence:
            raise ValueError("PORTFOLIO_SNAPSHOT_INVALID")
        products = verified_scope(identity["policy"])
        if products != EXPANDED_PORTFOLIO_PRODUCTS:
            raise ValueError("PORTFOLIO_ACTIVE_SCOPE_RETIRED")
        if state["result"]["policy"] != identity["policy"]:
            raise ValueError("PORTFOLIO_SNAPSHOT_POLICY_MISMATCH")
        heartbeat = read_registration(HEARTBEAT) or {}
        fresh = heartbeat.get("run_id") == run_id and heartbeat.get("at") and (
            0 <= (datetime.now(UTC) - datetime.fromisoformat(heartbeat["at"])).total_seconds() < 30
        )
        return project(
            state["result"], products=products,
            status=heartbeat["status"] if fresh else "STALE_OR_STOPPED",
            run_id=run_id, sequence=sequence, observed_at=last["observed_at"] if last else None,
            trading_day=last["day"] if last else None,
            worker_code=heartbeat.get("code") if heartbeat.get("run_id") == run_id else None,
            charts=state.get("charts", {}),
        )
    except Exception:
        raise HTTPException(503, detail={"code": "PORTFOLIO_STATUS_UNAVAILABLE"}) from None
    finally:
        if store:
            store.engine.dispose()


@router.get("/history")
def history(index: int | None = Query(default=None, ge=0)):
    try:
        entry = read_registration(HISTORY)
        if entry is None:
            return project({"accounts": {}}, products=(), status="NOT_REGISTERED", run_id=None)
        path = Path(entry["path"])
        _safe_root(path.parent)
        raw = _read_file(path)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("PORTFOLIO_HISTORY_HASH_MISMATCH")
        asset = json.loads(raw)
        result = asset["result"]
        products = verified_scope(result["policy"])
        timeline = asset.get("timeline", [])
        if index is not None and index >= len(timeline):
            raise HTTPException(404, detail={"code": "PORTFOLIO_CURSOR_UNAVAILABLE"})
        position = (len(timeline) - 1 if index is None else index) if timeline else None
        charts = {}
        metadata = {}
        if position is not None:
            frame = timeline[position]
            at = datetime.fromisoformat(frame["at"])
            daily = frame["daily"]
            accounts = {}
            for mark in frame["accounts"].values():
                contract = mark["contract"]
                try:
                    final = result["accounts"][contract]
                except KeyError:
                    continue
                accounts[contract] = dict(
                    contract=contract, valuation_at=frame["at"],
                    status="OPEN" if mark["quantity"] else "PENDING" if mark["pending"] else "COMPLETED",
                    summary={"open_quantity": mark["quantity"]},
                    open_layers=mark["layers"], pending=mark["pending"],
                    latest_decision=mark["decision"],
                    decision_state={"initial_stop": mark["stop"], "profit_target": mark["target"]},
                    **{key: [r for r in final[key] if datetime.fromisoformat(r[field]) <= at][-100:]
                       for key, field in (("decisions_with_actions", "at"), ("fills", "fill_at"))},
                )
            result = {**result, "accounts": accounts, "equity": daily["equity"],
                      "margin": daily["margin"], "daily": {frame["day"]: daily},
                      "pending_exit_contracts": frame["pending_exit_contracts"],
                      "valuation_unproven": frame["valuation_unproven"]}
            # Final cash is not known at the playback cursor.
            result.pop("cash", None)
            for points in asset.get("charts", {}).values():
                for point in points:
                    if datetime.fromisoformat(point["at"]) <= at:
                        charts.setdefault(point["contract"], []).append(point)
            charts = {contract: points[-128:] for contract, points in charts.items()}
            metadata = dict(index=position, length=len(timeline), observed_at=frame["at"], trading_day=frame["day"])
        return project(
            result, products=products, status="HISTORICAL_RESULT", run_id=entry["sha256"],
            window=asset["requested"], coverage=asset["coverage"], charts=charts, **metadata,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail={"code": "PORTFOLIO_HISTORY_UNAVAILABLE"}) from None
