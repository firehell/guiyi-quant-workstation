"""Private at-most-once dispatch claims. A claim is never permission to retry."""

import json
import os
from pathlib import Path
import sqlite3
import threading
from ..htdy_account_execution.codec import json_text


class Journal:
    def __init__(self, path, account_id):
        self.path = Path(path)
        self.account_id = account_id
        self.lock = threading.RLock()
        if self.path.is_symlink():
            raise ValueError("PRIVATE_DISPATCH_JOURNAL_REQUIRED")
        try:
            fd = os.open(
                self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            if not self.path.is_file() or self.path.stat().st_mode & 0o077:
                raise ValueError("PRIVATE_DISPATCH_JOURNAL_REQUIRED") from None
            created = False
        else:
            os.close(fd)
            created = True
        self.conn = sqlite3.connect(
            self.path, isolation_level=None, timeout=5, check_same_thread=False
        )
        self.uncertain = False
        try:
            if created:
                self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE identity (account TEXT NOT NULL, schema TEXT NOT NULL);
                CREATE TABLE actions (id INTEGER PRIMARY KEY AUTOINCREMENT, action_key TEXT UNIQUE NOT NULL,
                  order_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  order_ref TEXT NOT NULL, front_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
                  request_id INTEGER UNIQUE NOT NULL, intent TEXT UNIQUE NOT NULL);
                CREATE TABLE results (action_id INTEGER PRIMARY KEY, outcome TEXT NOT NULL);
                CREATE TABLE events (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, received_at TEXT NOT NULL);
                CREATE TRIGGER no_action_update BEFORE UPDATE ON actions BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
                CREATE TRIGGER no_action_delete BEFORE DELETE ON actions BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
                CREATE TRIGGER no_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
                CREATE TRIGGER no_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
                COMMIT;
                """)
                self.conn.execute(
                    "INSERT INTO identity VALUES (?,?)",
                    (account_id, "simnow_dispatch_v1"),
                )
            if self.conn.execute("SELECT account,schema FROM identity").fetchall() != [
                (account_id, "simnow_dispatch_v1")
            ]:
                raise ValueError("DISPATCH_IDENTITY_MISMATCH")
        except Exception:
            self.conn.close()
            raise ValueError("DISPATCH_JOURNAL_INVALID") from None

    def close(self):
        self.conn.close()

    def find(self, order_id):
        row = self.conn.execute(
            "SELECT payload,order_ref,front_id,session_id,request_id FROM actions WHERE order_id=? AND kind='SUBMIT'",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("NATIVE_ORDER_BINDING_MISSING")
        payload, ref, front, session, request = row
        return {
            **json.loads(payload),
            "order_ref": ref,
            "front_id": front,
            "session_id": session,
            "request_id": request,
        }

    def find_ref(self, ref, front=None, session=None):
        rows = self.conn.execute(
            "SELECT order_id,front_id,session_id FROM actions WHERE order_ref=? AND kind='SUBMIT'",
            (ref,),
        ).fetchall()
        matches = [r for r in rows if front is None or r[1:] == (front, session)]
        if len(matches) != 1:
            raise ValueError("NATIVE_ORDER_IDENTITY_UNKNOWN")
        return matches[0][0]

    def claimed(self, order_id, kind="SUBMIT"):
        return (
            self.conn.execute(
                "SELECT 1 FROM actions WHERE order_id=? AND kind=?", (order_id, kind)
            ).fetchone()
            is not None
        )

    def request_order(self, request_id):
        row = self.conn.execute(
            "SELECT order_id,kind FROM actions WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError("NATIVE_REQUEST_UNKNOWN")
        return row

    def claim(self, key, order_id, kind, payload, session, intent):
        with self.lock:
            if self.uncertain:
                raise ValueError("DISPATCH_COMMIT_UNKNOWN")
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                row = self.conn.execute(
                    "SELECT id FROM actions WHERE action_key=?", (key,)
                ).fetchone()
                if row:
                    self.conn.execute("ROLLBACK")
                    return None
                next_id = self.conn.execute(
                    "SELECT COALESCE(MAX(id),0)+1 FROM actions"
                ).fetchone()[0]
                ref_max = self.conn.execute(
                    "SELECT COALESCE(MAX(CAST(order_ref AS INTEGER)),0) FROM actions WHERE kind='SUBMIT'"
                ).fetchone()[0]
                ref = (
                    str(max(session.max_order_ref, ref_max) + 1)
                    if kind == "SUBMIT"
                    else self.find(order_id)["order_ref"]
                )
                if len(ref) > 12:
                    raise ValueError("ORDER_REF_EXHAUSTED")
                request_id = 10000 + next_id
                self.conn.execute(
                    "INSERT INTO actions VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        next_id,
                        key,
                        order_id,
                        kind,
                        json_text(payload),
                        ref,
                        session.front_id,
                        session.session_id,
                        request_id,
                        intent,
                    ),
                )
                try:
                    self.conn.execute("COMMIT")
                except sqlite3.Error:
                    self.uncertain = True
                    raise ValueError("DISPATCH_COMMIT_UNKNOWN") from None
                return next_id, ref, request_id
            except Exception:
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise ValueError("DISPATCH_CLAIM_FAILED") from None

    def result(self, action_id, outcome):
        try:
            self.conn.execute("INSERT INTO results VALUES (?,?)", (action_id, outcome))
        except sqlite3.Error:
            self.uncertain = True
            raise ValueError("DISPATCH_RESULT_UNKNOWN") from None

    def event(self, identity, payload, at):
        with self.lock:
            encoded = json_text(payload)
            row = self.conn.execute(
                "SELECT payload,received_at FROM events WHERE event_id=?", (identity,)
            ).fetchone()
            if row:
                if row[0] != encoded:
                    raise ValueError("NATIVE_EVENT_CONFLICT")
                return row[1]
            self.conn.execute(
                "INSERT INTO events VALUES (?,?,?)", (identity, encoded, at.isoformat())
            )
            return at.isoformat()

    def events(self):
        return [
            (identity, json.loads(payload), at)
            for identity, payload, at in self.conn.execute(
                "SELECT event_id,payload,received_at FROM events ORDER BY rowid"
            )
        ]
