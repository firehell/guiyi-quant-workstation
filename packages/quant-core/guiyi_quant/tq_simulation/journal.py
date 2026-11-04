"""Account-scoped immutable TqKq evidence and at-most-once transport claims."""

from pathlib import Path
from hashlib import sha256
import json
import os
import sqlite3


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(wire(value).encode()).hexdigest()


class Journal:
    def __init__(self, path, account):
        path = Path(path)
        try:
            fd = os.open(
                path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_nlink != 1
                or path.stat().st_uid != os.getuid()
                or path.stat().st_mode & 0o077
            ):
                raise ValueError("TQ_PRIVATE_JOURNAL_REQUIRED") from None
            created = False
        else:
            os.close(fd)
            created = True
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        if created:
            self.db.executescript("""
            CREATE TABLE identity(account TEXT NOT NULL,profile TEXT NOT NULL);
            CREATE TABLE claims(id TEXT PRIMARY KEY,kind TEXT NOT NULL,order_id TEXT NOT NULL,
              native_id TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL,
              UNIQUE(kind,order_id));
            CREATE TABLE events(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL);
            CREATE TRIGGER no_claim_update BEFORE UPDATE ON claims BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TRIGGER no_claim_delete BEFORE DELETE ON claims BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TRIGGER no_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TRIGGER no_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TRIGGER no_identity_update BEFORE UPDATE ON identity BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            CREATE TRIGGER no_identity_delete BEFORE DELETE ON identity BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
            """)
            self.db.execute(
                "INSERT INTO identity VALUES (?,?)", (account, "TQKQ:htdy_tqkq_v1")
            )
        if self.db.execute("SELECT account,profile FROM identity").fetchall() != [
            (account, "TQKQ:htdy_tqkq_v1")
        ]:
            raise ValueError("TQ_JOURNAL_IDENTITY_MISMATCH")
        self.account = account

    def claim(self, kind, order, payload, at):
        if kind not in {"SUBMIT", "CANCEL"}:
            raise ValueError("TQ_ACTION_INVALID")
        native = "gq" + sha256((self.account + ":" + order).encode()).hexdigest()[:30]
        key = kind + ":" + order
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT payload FROM claims WHERE id=?", (key,)
            ).fetchone()
            if prior:
                if prior[0] != wire(payload):
                    raise ValueError("TQ_CLAIM_DRIFT")
                self.db.execute("ROLLBACK")
                return None
            self.db.execute(
                "INSERT INTO claims VALUES (?,?,?,?,?,?)",
                (key, kind, order, native, wire(payload), at.isoformat()),
            )
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        return native

    def submit_payload(self, order):
        row = self.db.execute(
            "SELECT payload FROM claims WHERE kind='SUBMIT' AND order_id=?", (order,)
        ).fetchone()
        if row is None:
            raise ValueError("TQ_ORDER_JOURNAL_MISSING")
        return json.loads(row[0])

    def mappings(self):
        return dict(
            self.db.execute("SELECT native_id,order_id FROM claims WHERE kind='SUBMIT'")
        )

    def event(self, kind, payload, at, *, identity=None):
        raw = wire(payload)
        key = identity or kind + ":" + digest(payload)
        prior = self.db.execute(
            "SELECT kind,payload FROM events WHERE id=?", (key,)
        ).fetchone()
        if prior:
            if prior != (kind, raw):
                raise ValueError("TQ_EVENT_IDENTITY_CONFLICT")
            return key
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?)", (key, kind, raw, at.isoformat())
        )
        return key

    def events(self, kind):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM events WHERE kind=? ORDER BY rowid", (kind,)
            )
        ]

    def close(self):
        self.db.close()
