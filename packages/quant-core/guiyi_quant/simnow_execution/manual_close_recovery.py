"""One management connection for the known manual opening; no opening capability."""

from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
import sqlite3
from zoneinfo import ZoneInfo

from .. import htdy_account_execution as a
from ..htdy_account_execution.model import manual_test_id
from .manual_recovery import private_json
from .monitor import _snapshot
from .inventory import native_order, trade_identity


def baseline_for(folder, source, account):
    path = folder / "native-evidence.sqlite"
    if path.is_symlink() or not path.is_file():
        raise ValueError("CLOSE_RECOVERY_BASELINE_REQUIRED")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if conn.execute("SELECT account FROM owner").fetchall() != [(account,)]:
            raise ValueError("CLOSE_RECOVERY_BASELINE_REQUIRED")
        row = conn.execute(
            "SELECT payload FROM snapshots WHERE source=?", (source,)
        ).fetchone()
        if row is None:
            raise ValueError("CLOSE_RECOVERY_BASELINE_REQUIRED")
        return _snapshot(row[0], source, account)
    finally:
        conn.close()


def claim_close_only(folder, test_id, account, now):
    manual_test_id(test_id)
    prefix = test_id.replace(":", "-")
    _, plan = private_json(folder / (prefix + "-close-only-plan.json"))
    if set(plan) != {
        "schema",
        "test_id",
        "account_id",
        "expires_at",
        "preimages",
        "order_id",
        "contract",
        "trade_id",
        "system_id",
        "baseline_source_id",
        "max_connections",
        "max_total_connections",
    } or (
        plan["schema"] != "simnow_manual_close_only_v1"
        or plan["test_id"] != test_id
        or plan["account_id"] != account
        or plan["contract"].split(".")[0][:2] != "RB"
        or type(plan["max_connections"]) is not int
        or plan["max_connections"] != 1
        or type(plan["max_total_connections"]) is not int
        or plan["max_total_connections"] != 4
    ):
        raise ValueError("CLOSE_RECOVERY_PLAN_INVALID")
    expires = datetime.fromisoformat(plan["expires_at"])
    if (
        expires.tzinfo is None
        or now.tzinfo is None
        or not now < expires <= now + timedelta(hours=1)
    ):
        raise ValueError("CLOSE_RECOVERY_PLAN_EXPIRED")
    if set(plan["preimages"]) != {
        "account.sqlite",
        "dispatch.sqlite",
        "signals.sqlite",
    }:
        raise ValueError("CLOSE_RECOVERY_PREIMAGE_INVALID")
    for name, expected in plan["preimages"].items():
        path = folder / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("CLOSE_RECOVERY_PREIMAGE_DRIFT")
    state = a.LocalStore.inspect(folder / "account.sqlite")
    begins = [x.command for x in state.audit if type(x.command) is a.ManualBeginV1]
    if (
        state.account_id != account
        or len(begins) != 1
        or begins[0].test_id != test_id
        or begins[0].contract != plan["contract"]
    ):
        raise ValueError("CLOSE_RECOVERY_SCOPE_INVALID")
    opens = [o for o in state.orders if o.offset == "OPEN"]
    if (
        len(opens) != 1
        or opens[0].order_id != plan["order_id"]
        or opens[0].signal_id != test_id
        or opens[0].side != "BUY"
        or opens[0].contract != plan["contract"]
        or opens[0].quantity != 1
    ):
        raise ValueError("CLOSE_RECOVERY_SCOPE_INVALID")
    for suffix in ("-login.json", "-diagnostic-login.json", "-recovery-login.json"):
        _, prior = private_json(folder / (prefix + suffix))
        if prior.get("test_id") != test_id or prior.get("account_id") != account:
            raise ValueError("CLOSE_RECOVERY_PRIOR_BUDGET_REQUIRED")
        if (
            type(prior.get("max_connections")) is not int
            or prior["max_connections"] != 1
        ):
            raise ValueError("CLOSE_RECOVERY_PRIOR_BUDGET_REQUIRED")
        expected_field, expected_count = {
            "-login.json": ("connections", 1),
            "-diagnostic-login.json": ("cumulative_manual_connections_after_claim", 2),
            "-recovery-login.json": ("cumulative_manual_connections", 3),
        }[suffix]
        if (
            type(prior.get(expected_field)) is not int
            or prior[expected_field] != expected_count
        ):
            raise ValueError("CLOSE_RECOVERY_PRIOR_BUDGET_REQUIRED")
    path = folder / "dispatch.sqlite"
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT order_id,kind,payload FROM actions").fetchall()
        if len(rows) != 1 or rows[0][:2] != (plan["order_id"], "SUBMIT"):
            raise ValueError("CLOSE_RECOVERY_CLAIM_REQUIRED")
        payload = json.loads(rows[0][2])
        if (
            payload["contract"] != plan["contract"]
            or payload["side"] != "BUY"
            or payload["offset"] != "0"
            or payload.get("account_id") != account
        ):
            raise ValueError("CLOSE_RECOVERY_CLAIM_REQUIRED")
        trades = [
            json.loads(r[0])
            for r in conn.execute("SELECT payload FROM events")
            if json.loads(r[0]).get("kind") == "trade"
        ]
        if (
            len(trades) != 1
            or trades[0]["trade_id"] != plan["trade_id"]
            or trades[0]["system_id"] != plan["system_id"]
            or trades[0]["order_id"] != plan["order_id"]
        ):
            raise ValueError("CLOSE_RECOVERY_TRADE_REQUIRED")
    finally:
        conn.close()
    baseline = baseline_for(folder, plan["baseline_source_id"], account)
    if (
        baseline.at >= opens[0].created_at
        or baseline.data["positions"]
        or baseline.data["orders"]
        or baseline.data["trades"]
    ):
        raise ValueError("CLOSE_RECOVERY_BASELINE_REQUIRED")
    fd = os.open(
        folder / (prefix + "-close-only-login.json"),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as stream:
        json.dump(
            dict(
                schema=plan["schema"],
                test_id=test_id,
                account_id=account,
                order_id=plan["order_id"],
                at=now.isoformat(),
                max_connections=1,
                cumulative_manual_connections=4,
                opening_enabled=False,
                plan_sha256=sha256(
                    (folder / (prefix + "-close-only-plan.json")).read_bytes()
                ).hexdigest(),
            ),
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
    return baseline, plan


def validate_events(market, snapshot, contract):
    day = datetime.strptime(snapshot.trading_day, "%Y%m%d").date()
    data = snapshot.data
    for kind, date_field, time_field in (
        ("orders", "InsertDate", "InsertTime"),
        ("trades", "TradeDate", "TradeTime"),
    ):
        for row in data[kind]:
            raw = datetime.strptime(
                row[date_field] + row[time_field], "%Y%m%d%H:%M:%S"
            ).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            authority = market.authority("RB", day, raw, contract)
            if authority.contract != contract or not authority.session.can_trade:
                raise ValueError("NATIVE_EVENT_SESSION_UNPROVEN")


def validate_close_inventory(snapshot, plan, journal, binding):
    """The management connection can act only on the one reported opening."""
    data = snapshot.data
    orders, trades = data["orders"], data["trades"]
    if (
        len(orders) != 1
        or len(trades) != 1
        or native_order(orders[0], journal) != plan["order_id"]
        or orders[0]["OrderStatus"] != "0"
        or orders[0]["VolumeTraded"] != 1
        or orders[0]["OrderSysID"].strip() != plan["system_id"]
        or trade_identity(trades[0]) != plan["trade_id"]
        or trades[0]["OrderSysID"].strip() != plan["system_id"]
        or trades[0]["Volume"] != 1
    ):
        raise ValueError("CLOSE_RECOVERY_NATIVE_TRADE_UNPROVEN")
    held = [
        p
        for p in data["positions"]
        if p["Position"] or p["LongFrozen"] or p["ShortFrozen"]
    ]
    if (
        len(held) != 1
        or held[0]["InstrumentID"] != binding.native
        or held[0]["ExchangeID"] != binding.exchange
        or held[0]["HedgeFlag"] != "1"
        or held[0]["PosiDirection"] != "2"
        or held[0]["Position"] != 1
        or held[0]["LongFrozen"]
        or held[0]["ShortFrozen"]
    ):
        raise ValueError("CLOSE_RECOVERY_ONE_LONG_REQUIRED")
