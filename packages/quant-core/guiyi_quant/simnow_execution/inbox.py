"""Account-bound durable first-observation queue; acknowledgment never sends orders."""

from datetime import UTC, datetime
from pathlib import Path
import json
import os
import re
import sqlite3

from ..htdy_account_execution import codec
from ..htdy_execution import Signal


class SignalInbox:
    def __init__(self, path, account_id, products):
        if re.fullmatch(r"[a-f0-9]{64}", account_id) is None:
            raise ValueError("INBOX_ACCOUNT_INVALID")
        self.products = tuple(sorted(products))
        if not self.products or len(set(self.products)) != len(self.products):
            raise ValueError("INBOX_SCOPE_INVALID")
        path = Path(path)
        try:
            fd = os.open(
                path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_mode & 0o077
                or path.stat().st_uid != os.getuid()
            ):
                raise ValueError("INBOX_PRIVATE_REQUIRED") from None
            created = False
        else:
            os.close(fd)
            created = True
        self.conn = sqlite3.connect(path, isolation_level=None)
        if created:
            self.conn.executescript("""
            CREATE TABLE identity(account TEXT, scope TEXT);
            CREATE TABLE signals(id INTEGER PRIMARY KEY, product TEXT NOT NULL, bar TEXT NOT NULL,
              source TEXT NOT NULL UNIQUE, observed TEXT NOT NULL, payload TEXT NOT NULL,
              hash TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(product,bar));
            CREATE TRIGGER frozen_signal BEFORE UPDATE OF product,bar,source,observed,payload,hash ON signals
              BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TRIGGER retained_signal BEFORE DELETE ON signals
              BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TABLE attempts(day TEXT PRIMARY KEY, count INTEGER NOT NULL);
            CREATE TABLE blocks(day TEXT PRIMARY KEY, code TEXT NOT NULL);
            """)
            self.conn.execute(
                "INSERT INTO identity VALUES (?,?)",
                (account_id, json.dumps(self.products)),
            )
        if self.conn.execute("SELECT account,scope FROM identity").fetchall() != [
            (account_id, json.dumps(self.products))
        ]:
            self.conn.close()
            raise ValueError("INBOX_IDENTITY_MISMATCH")

    def enqueue(self, signal):
        if type(signal) is not Signal or signal.product not in self.products:
            raise ValueError("INBOX_SIGNAL_SCOPE_INVALID")
        payload = codec.json_text(codec.encode(signal))
        prior = self.conn.execute(
            "SELECT hash FROM signals WHERE source=? OR (product=? AND bar=?)",
            (
                signal.source_id,
                signal.product,
                signal.bar_end.astimezone(UTC).isoformat(),
            ),
        ).fetchone()
        if prior:
            return "DUPLICATE" if prior[0] == codec.digest(signal) else "REDRAW_IGNORED"
        if (
            self.conn.execute(
                "SELECT COUNT(*) FROM signals WHERE status='QUEUED'"
            ).fetchone()[0]
            >= 2048
        ):
            raise ValueError("INBOX_CAPACITY_REACHED")
        self.conn.execute(
            "INSERT INTO signals(product,bar,source,observed,payload,hash,status) VALUES (?,?,?,?,?,?,'QUEUED')",
            (
                signal.product,
                signal.bar_end.astimezone(UTC).isoformat(),
                signal.source_id,
                signal.observed_at.astimezone(UTC).isoformat(),
                payload,
                codec.digest(signal),
            ),
        )
        return "QUEUED"

    def pending(self):
        rows = self.conn.execute(
            "SELECT source,payload,hash FROM signals WHERE status='QUEUED' ORDER BY observed,product,source"
        ).fetchall()
        result = []
        for source, payload, digest in rows:
            signal = codec.decode(json.loads(payload))
            if (
                type(signal) is not Signal
                or codec.digest(signal) != digest
                or signal.source_id != source
            ):
                raise ValueError("INBOX_SIGNAL_DAMAGED")
            result.append(signal)
        return tuple(result)

    def mark(self, source, status):
        if status not in {"APPLIED", "OBSERVED", "RESTART_DROPPED", "RECOVERY_DROPPED"}:
            raise ValueError("INBOX_STATUS_INVALID")
        self.conn.execute(
            "UPDATE signals SET status=? WHERE source=? AND status='QUEUED'",
            (status, source),
        )

    @staticmethod
    def command_key(signal):
        return "portfolio-signal:" + signal.source_id

    def recover_queue(self, store=None):
        # A commit-before-ack crash is acknowledged from immutable command evidence.
        # An uncommitted first observation can never become a delayed opening.
        for signal in self.pending():
            receipt = (
                store.receipt(self.command_key(signal)) if store is not None else None
            )
            if receipt is not None and receipt["command_hash"] != codec.digest(signal):
                raise ValueError("INBOX_COMMAND_CONFLICT")
            self.mark(signal.source_id, "APPLIED" if receipt else "RESTART_DROPPED")

    def deliver(self, store):
        for signal in self.pending():
            store.execute(self.command_key(signal), signal)
            self.mark(signal.source_id, "APPLIED")

    def attempt(self, day):
        # Durable daily connection budget, including failed/unknown login outcomes.
        datetime.strptime(day, "%Y%m%d")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT count FROM attempts WHERE day=?", (day,)
            ).fetchone()
            count = row[0] if row else 0
            if count >= 3:
                raise ValueError("CONNECTION_BUDGET_EXHAUSTED")
            self.conn.execute(
                "INSERT OR REPLACE INTO attempts VALUES (?,?)", (day, count + 1)
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return count + 1

    def block(self, day, code):
        datetime.strptime(day, "%Y%m%d")
        self.conn.execute("INSERT OR IGNORE INTO blocks VALUES (?,?)", (day, code))

    def blocked(self, day):
        return (
            self.conn.execute("SELECT code FROM blocks WHERE day=?", (day,)).fetchone()
            is not None
        )

    def close(self):
        self.conn.close()
