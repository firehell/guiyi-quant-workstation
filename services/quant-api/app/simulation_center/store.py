"""Account-isolated PostgreSQL persistence and read-only workstation queries."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import re

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.simulation_center.config import ACCOUNT_ALIAS, ObserverConfig, native_account_key
from app.simulation_center.readback import ReadbackError

SOURCE = "SIMNOW_CTP"
MAX_READ_AGE = timedelta(seconds=120)


def connect(dsn: str):
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3,
                           options="-c statement_timeout=4000 -c lock_timeout=1500")


def register_account(conn, alias: str, native_key: str) -> None:
    """Bind an existing SimNow identity without starting an observer or changing its state."""
    if not re.fullmatch(ACCOUNT_ALIAS, alias) or not re.fullmatch(r"[0-9a-f]{64}", native_key):
        raise ReadbackError("ACCOUNT_BINDING_INVALID")
    with conn.transaction():
        conn.execute(
            """INSERT INTO guiyi_simulation.accounts (alias, native_key, status)
               VALUES (%s, %s, 'REGISTERED') ON CONFLICT DO NOTHING""", (alias, native_key))
        account = conn.execute("SELECT native_key FROM guiyi_simulation.accounts WHERE alias = %s",
                               (alias,)).fetchone()
        if account is None or account["native_key"] != native_key:
            raise ReadbackError("ACCOUNT_BINDING_CONFLICT")


class Writer:
    def __init__(self, connection, alias: str):
        self.connection = connection
        self.alias = alias

    @classmethod
    @contextmanager
    def claim(cls, dsn: str, config: ObserverConfig) -> Iterator["Writer"]:
        native_key = native_account_key(config.user)
        with connect(dsn) as conn:
            with conn.transaction():
                locked = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked",
                                      ("guiyi_simulation:" + native_key,)).fetchone()
                if not locked["locked"]:
                    raise ReadbackError("ACCOUNT_ALREADY_OWNED")
                register_account(conn, config.alias, native_key)
                deployment = asdict(config.deployment) if config.deployment else None
                conn.execute("""UPDATE guiyi_simulation.accounts SET deployment = %s, status = 'CONNECTING',
                                status_at = clock_timestamp() WHERE alias = %s""",
                             (Jsonb(deployment), config.alias))
            yield cls(conn, config.alias)

    def status(self, status: str):
        with self.connection.transaction():
            self.connection.execute(
                """UPDATE guiyi_simulation.accounts SET status = %s, status_at = clock_timestamp()
                   WHERE alias = %s""", (status, self.alias))

    def publish(self, *snapshots: dict):
        """Persist one round or a verified pair with their immutable fills atomically."""
        with self.connection.transaction():
            for snapshot in snapshots:
                self._persist(snapshot)
            self.status("OBSERVING")

    def _persist(self, snapshot: dict):
        with self.connection.transaction():
            previous = self.connection.execute(
                """SELECT facts FROM guiyi_simulation.readbacks WHERE alias = %s
                   ORDER BY observed_at DESC LIMIT 1""", (self.alias,)).fetchone()
            if previous:
                check_order_prefix(previous["facts"], snapshot)
            self.connection.execute(
                """INSERT INTO guiyi_simulation.fills (alias, native_id, occurred_at, facts)
                   SELECT %s, item->>'id', (item->>'occurred_at')::timestamptz, item
                   FROM jsonb_array_elements(%s) AS item
                   ON CONFLICT DO NOTHING""", (self.alias, Jsonb(snapshot["fills"])))
            day_prefix = snapshot["trading_day"] + ":"
            recorded = self.connection.execute(
                """SELECT native_id, facts FROM guiyi_simulation.fills
                   WHERE alias = %s AND native_id >= %s AND native_id < %s""",
                (self.alias, day_prefix, snapshot["trading_day"] + ";")).fetchall()
            if {row["native_id"]: row["facts"] for row in recorded} != {
                fill["id"]: fill for fill in snapshot["fills"]
            }:
                raise ReadbackError("RETAINED_FILL_CONFLICT")
            self.connection.execute(
                """INSERT INTO guiyi_simulation.readbacks (alias, observed_at, facts)
                   VALUES (%s, %s, %s)""",
                (self.alias, datetime.fromisoformat(snapshot["observed_at"]), Jsonb(snapshot)))


def check_order_prefix(previous: dict, current: dict):
    if (current["trading_day"] < previous["trading_day"]
            or datetime.fromisoformat(current["observed_at"]) <= datetime.fromisoformat(previous["observed_at"])):
        raise ReadbackError("READBACK_REGRESSION")
    if previous["trading_day"] != current["trading_day"]:
        return
    current_orders = {order["id"]: order for order in current["orders"]}
    for old in previous["orders"]:
        new = current_orders.get(old["id"])
        if (not new or new["filled"] < old["filled"]
                or old["system_id"] and new["system_id"] != old["system_id"]
                or any(new[field] != old[field] for field in ("contract", "direction", "offset", "quantity", "price"))
                or old["status"] in {"0", "2", "4", "5"} and new != old):
            raise ReadbackError("RETAINED_ORDER_REGRESSION")


def _accounts(conn, now):
    rows = conn.execute(
        """SELECT a.alias, a.deployment, a.status, a.status_at,
                  (SELECT max(observed_at) FROM guiyi_simulation.readbacks r WHERE r.alias = a.alias) AS observed_at
           FROM guiyi_simulation.accounts a ORDER BY a.alias LIMIT 128"""
    ).fetchall()
    return [
        {**row, "status": "STALE" if row["status"] != "REGISTERED" and now - row["status_at"] > MAX_READ_AGE
         else row["status"]}
        for row in rows
    ]


def read_workstation(dsn: str, alias: str | None, before: str | None, *, now: datetime | None = None):
    with connect(dsn) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        accounts = _accounts(conn, now or datetime.now(UTC))
        if alias is not None and not any(account["alias"] == alias for account in accounts):
            raise LookupError("SIMULATION_ACCOUNT_NOT_FOUND")
        selected = alias if alias is not None else (accounts[0]["alias"] if accounts else None)
        result = {"source": SOURCE, "status": "AVAILABLE", "accounts": accounts, "selected": selected,
                  "readback": None, "equity": [], "fills": [], "next_fill": None}
        if selected is None:
            return result
        latest = conn.execute(
            """SELECT facts FROM guiyi_simulation.readbacks WHERE alias = %s
               ORDER BY observed_at DESC LIMIT 1""", (selected,)).fetchone()
        result["readback"] = {key: value for key, value in latest["facts"].items() if key != "fills"} if latest else None
        result["equity"] = conn.execute(
            """SELECT observed_at, facts->'account'->>'equity' AS equity
               FROM guiyi_simulation.readbacks WHERE alias = %s ORDER BY observed_at DESC LIMIT 120""",
            (selected,)).fetchall()[::-1]
        if before is None:
            fills = conn.execute(
                """SELECT native_id, facts FROM guiyi_simulation.fills WHERE alias = %s
                   ORDER BY occurred_at DESC, native_id DESC LIMIT 101""", (selected,)).fetchall()
        else:
            fills = conn.execute(
                """SELECT native_id, facts FROM guiyi_simulation.fills
                   WHERE alias = %s AND (occurred_at, native_id) <
                       (SELECT occurred_at, native_id FROM guiyi_simulation.fills WHERE alias = %s AND native_id = %s)
                   ORDER BY occurred_at DESC, native_id DESC LIMIT 101""", (selected, selected, before)).fetchall()
        result["fills"] = [row["facts"] for row in fills[:100]]
        result["next_fill"] = fills[99]["native_id"] if len(fills) > 100 else None
        return result


def read_committed_fills(dsn: str, trading_day: str, alias: str | None, native_id: str | None):
    """Read the day's registered evidence, with an exact lookup independent of UI pagination."""
    with connect(dsn) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        accounts = [account["alias"] for account in _accounts(conn, datetime.now(UTC))]
        if alias is None:
            return accounts, None, []
        if alias not in accounts:
            raise LookupError("SIMULATION_ACCOUNT_NOT_FOUND")
        sampled = conn.execute("""
            SELECT 1 FROM guiyi_simulation.readbacks
            WHERE alias=%s AND facts->>'trading_day'=%s LIMIT 1
        """, (alias, trading_day)).fetchone()
        fills = conn.execute("""
            SELECT facts FROM guiyi_simulation.fills
            WHERE alias=%s AND native_id >= %s AND native_id < %s
                AND (%s::text IS NULL OR native_id=%s)
            ORDER BY occurred_at, native_id LIMIT 201
        """, (alias, trading_day + ":", trading_day + ";", native_id, native_id)).fetchall()
        return accounts, sampled is not None, [fill["facts"] for fill in fills]
