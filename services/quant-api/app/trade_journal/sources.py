"""Project individually owned evidence onto the journal's read interface."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sqlite3
from stat import S_ISREG

import psycopg
from fastapi import HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.api import reference_trading, subing_portfolio
from app.backtest_center.store import read_published_runs, read_published_trades
from app.backtest_center.worker import Settings
from app.reference_trading.query import QueryConflict
from app.simulation_center.store import read_committed_fills
from guiyi_quant.htdy_account_execution.store import LocalStore
from guiyi_quant.htdy_account_execution.tq_types import TqKqFill
from guiyi_quant.tq_simulation.gateway import instant_ns
from guiyi_quant.tq_simulation.manual_reconcile import validate_snapshot

from .contracts import SourceKey
from .store import JournalError

_LIMIT = 200
_ACCOUNT = re.compile(r"^[0-9a-f]{64}$")


def _amount(value):
    if value is None:
        return None
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("JOURNAL_NATIVE_AMOUNT_INVALID")
    return str(amount)


def _direction(side: str, opening: bool):
    if side in ("BUY", "LONG"):
        return "LONG" if opening else "SHORT"
    if side in ("SELL", "SHORT"):
        return "SHORT" if opening else "LONG"
    raise ValueError("JOURNAL_NATIVE_SIDE_INVALID")


def _row(native_id, contract, occurred_at, direction, action, *, price=None, fee=None, quantity=None, **details):
    if not isinstance(contract, str) or not contract or not isinstance(native_id, str) or not native_id:
        raise ValueError("JOURNAL_NATIVE_IDENTITY_INVALID")
    at = occurred_at if isinstance(occurred_at, datetime) else datetime.fromisoformat(occurred_at)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("JOURNAL_NATIVE_TIME_INVALID")
    return {"native_id": native_id, "contract": contract.upper(), "occurred_at": at.isoformat(),
            "direction": direction, "action": action, "price": _amount(price), "fee": _amount(fee),
            "quantity": quantity, **details}


def _result(scope, rows=(), *, status=None, scopes=(), scope_labels=None):
    return {"scope": scope, "scopes": list(scopes), "status": status or ("AVAILABLE" if rows else "VERIFIED_EMPTY"),
            "scope_labels": scope_labels or {}, "items": list(rows[:_LIMIT]), "has_more": len(rows) > _LIMIT}


def _simnow(day, scope, native_id):
    dsn = os.getenv("GUIYI_SIMULATION_READER_DSN")
    if not dsn:
        return _result(scope, status="NOT_CONFIGURED")
    scopes, sampled, rows = read_committed_fills(dsn, day.isoformat(), scope, native_id)
    if scope is None:
        return _result(scope, status="SCOPE_REQUIRED" if scopes else "NO_EVIDENCE", scopes=scopes)
    if not sampled:
        return _result(scope, status="NO_EVIDENCE", scopes=scopes)
    return _result(scope, [
        _row(fill["id"], fill["contract"], fill["occurred_at"],
             _direction(fill["direction"], fill["offset"] == "OPEN"), fill["offset"],
             price=fill["price"], fee=fill.get("fee"), quantity=fill["quantity"])
        for fill in rows
    ], scopes=scopes)


def _paper(day, scope, native_id, contract):
    if contract is None:
        return _result(scope, status="CONTRACT_REQUIRED")
    scope, sampled, rows = subing_portfolio.read_committed_fills(day, contract, scope, native_id)
    if not rows and not sampled:
        return _result(scope, status="NO_EVIDENCE")
    return _result(scope, [
        _row(fill["fill_id"], fill["contract"], fill["fill_at"], fill["side"], fill["action"],
             price=fill["price"], fee=fill["fee"], quantity=fill["quantity"],
             gross_realized=_amount(fill.get("gross_realized")))
        for fill in rows
    ])


def _newow(request, day, scope, native_id, contract):
    reader = reference_trading._reader(request)
    if scope is None:
        if contract is None:
            return _result(scope, status="CONTRACT_REQUIRED")
        streams = reader.journal_streams(contract.rstrip("0123456789").lower())
        labels = {
            row["stream_id"]: f'{row["strategy_code"]} · {row["frequency"]}'
            for row in streams
        }
        return _result(scope, status="SCOPE_REQUIRED" if labels else "NO_EVIDENCE", scopes=labels, scope_labels=labels)
    page = reader.trades(scope, since=day, through=day, limit=200)
    if not page["stream"]["strategy_code"].startswith(("newow_", "newow-")):
        return _result(scope, status="NO_EVIDENCE")
    rows = page["items"]
    cursor = page["next_cursor"]
    if native_id:
        snapshot = page["snapshot"]
        for _ in range(4):
            exact = [row for row in rows if row["reference_trade_id"] == native_id
                     and row["entry_trading_day"] == day.isoformat()]
            if exact or not cursor:
                rows = exact
                break
            page = reader.trades(scope, since=day, through=day, limit=200, snapshot_token=snapshot, cursor=cursor)
            rows, cursor = page["items"], page["next_cursor"]
        else:
            return _result(scope, status="UNAVAILABLE")
    result = _result(scope, [
        _row(trade["reference_trade_id"], trade["physical_contract"], trade["entry_bar_end"],
             trade["side"], trade["status"], price=trade["entry_reference_price"],
             exit_price=_amount(trade.get("exit_reference_price")), reference_return=_amount(trade.get("reference_return")))
        for trade in rows if trade["entry_trading_day"] == day.isoformat()
    ])
    result["has_more"] = bool(cursor) if not native_id else False
    return result


def _backtest(day, scope, native_id, contract):
    path = Settings.local().path
    if not path.is_file():
        return _result(scope, status="NOT_CONFIGURED")
    if scope is None:
        if contract is None:
            return _result(scope, status="CONTRACT_REQUIRED")
        labels = dict(read_published_runs(path, day, contract))
        return _result(scope, status="SCOPE_REQUIRED" if labels else "NO_EVIDENCE", scopes=labels, scope_labels=labels)
    rows = read_published_trades(path, scope, day, native_id)
    return _result(scope, [
        _row(trade["trade_id"], trade["contract"], trade["entry_at"], trade["direction"], trade["status"],
             price=trade["entry_price"], fee=trade.get("fees"), quantity=trade["quantity"],
             exit_price=_amount(trade.get("exit_price")), net_pnl=_amount(trade.get("net_pnl")))
        for trade in rows
    ], status=None if rows else "NO_EVIDENCE")


def _tq_archive(day, scope, native_id):
    configured = os.getenv("GUIYI_TRADE_JOURNAL_TQKQ_ARCHIVE")
    if not configured:
        return _result(scope, status="NOT_CONFIGURED")
    root = Path(configured)
    account_path, dispatch_path = root / "account.sqlite", root / "dispatch.sqlite"
    for path in (account_path, dispatch_path):
        info = path.lstat()
        if (path.resolve(strict=True) != path or not S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError("TQ_PRIVATE_JOURNAL_REQUIRED")
        with path.open("rb") as stream:
            header = stream.read(20)
        if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
            raise ValueError("TQ_JOURNAL_MODE_UNSUPPORTED")
    state = LocalStore.inspect_tip(account_path)
    if not _ACCOUNT.fullmatch(state.account_id) or (scope is not None and state.account_id != scope):
        return _result(scope, status="NO_EVIDENCE")
    db = sqlite3.connect(dispatch_path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("SELECT account,profile FROM identity").fetchall() != [(state.account_id, "TQKQ:htdy_tqkq_v1")]:
            raise ValueError("TQ_JOURNAL_IDENTITY_MISMATCH")
        snapshots = {}
        for (payload,) in db.execute("""
            SELECT payload FROM events WHERE kind='snapshot'
                AND json_extract(payload, '$.trading_day') IN (?, ?)
        """, (day.isoformat(), day.strftime("%Y%m%d"))):
            snapshot = json.loads(payload)
            validate_snapshot(snapshot)
            if snapshot["account_id"] != state.account_id:
                raise ValueError("TQ_ACCOUNT_IDENTITY_MISMATCH")
            snapshots[snapshot["snapshot_id"]] = {trade["trade_id"]: trade for trade in snapshot["trades"]}
    finally:
        db.close()
    orders = {order.order_id: order for order in state.orders}
    rows = []
    for fill in state.fills:
        if (not isinstance(fill, TqKqFill) or fill.trade_id in state.unresolved_fill_ids
                or native_id is not None and native_id != fill.trade_id):
            continue
        trade = snapshots.get(fill.snapshot_sha256, {}).get(fill.native_trade_id)
        order = orders.get(fill.order_id)
        if (trade is None or order is None or trade["order_id"] != fill.native_order_id
                or instant_ns(trade["trade_date_time"]) != fill.filled_at or trade["direction"] != order.side
                or (trade["offset"] != order.offset and not (
                    order.offset == "CLOSE" and trade["offset"] == "CLOSETODAY"
                    and trade["exchange_id"] in {"SHFE", "INE"}
                ))
                or Decimal(str(trade["price"])) != fill.price):
            continue
        rows.append(_row(fill.trade_id, fill.contract, fill.filled_at, _direction(order.side, order.offset == "OPEN"),
                         trade["offset"], price=fill.price, fee=fill.fee, quantity=fill.quantity))
    return _result(state.account_id, rows, status=None if rows else "NO_EVIDENCE")


def read_evidence(request: Request, source: str, day: date, scope: str | None, *,
                  contract: str | None = None, native_id: str | None = None):
    try:
        if source == "SIMNOW":
            return _simnow(day, scope, native_id)
        if source == "SUBING_PAPER":
            return _paper(day, scope, native_id, contract)
        if source == "TQKQ_HISTORY":
            return _tq_archive(day, scope, native_id)
        if source == "NEWOW_REFERENCE":
            return _newow(request, day, scope, native_id, contract)
        return _backtest(day, scope, native_id, contract)
    except LookupError as exc:
        return _result(scope, status="NO_EVIDENCE" if type(exc) is LookupError else "UNAVAILABLE")
    except QueryConflict as exc:
        return _result(scope, status="NO_EVIDENCE" if str(exc) == "STREAM_NOT_FOUND" else "UNAVAILABLE")
    except (OSError, RuntimeError, ValueError, TypeError, InvalidOperation, SQLAlchemyError,
            psycopg.Error, sqlite3.Error, HTTPException):
        return _result(scope, status="UNAVAILABLE")


def resolve(request: Request, key: SourceKey, contract: str):
    result = read_evidence(request, key.source, key.trading_day, key.scope, contract=contract, native_id=key.native_id)
    rows = [row for row in result["items"] if row["native_id"] == key.native_id]
    if len(rows) != 1 or result["scope"] != key.scope:
        status = result["status"]
        raise JournalError("JOURNAL_SOURCE_" + status if status in {"UNAVAILABLE", "NOT_CONFIGURED"}
                           else "JOURNAL_EVIDENCE_NOT_FOUND", 503 if status == "UNAVAILABLE" else 404)
    return rows[0]
