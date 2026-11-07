"""Account-scoped immutable TqKq evidence and at-most-once transport claims."""

from pathlib import Path
from hashlib import sha256
import json
import os
import sqlite3
import stat
from datetime import datetime
from decimal import Decimal


def read_equity_history(path, account, published_tail):
    """Read retained equity only through the exact published monitor endpoint.

    Never construct Journal here: its constructor can create a database.
    """
    path = Path(path)
    if path.parent.resolve(strict=True) != path.parent:
        raise ValueError("TQ_PRIVATE_PATH_REQUIRED")
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o077):
        raise ValueError("TQ_PRIVATE_JOURNAL_REQUIRED")
    with path.open("rb") as stream:
        header = stream.read(20)
    # Refuse WAL: a read-only SQLite connection could create an shm sidecar.
    if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
        raise ValueError("TQ_JOURNAL_MODE_UNSUPPORTED")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("SELECT account,profile FROM identity").fetchall() != [
            (account, "TQKQ:htdy_tqkq_v1")
        ]:
            raise ValueError("TQ_JOURNAL_IDENTITY_MISMATCH")
        rows = db.execute(
            "SELECT rowid,payload FROM events WHERE kind=? AND at=?",
            ("equity", published_tail["at"]),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("TQ_EQUITY_ENDPOINT_MISSING")
        endpoint, raw = rows[0]
        tail = json.loads(raw)
        if any(tail[key] != published_tail[key] for key in ("at", "equity", "trading_day")):
            raise ValueError("TQ_EQUITY_ENDPOINT_MISMATCH")
        curve, previous = [], None
        for (raw,) in db.execute(
            "SELECT payload FROM events WHERE kind=? AND rowid<=? ORDER BY rowid",
            ("equity", endpoint),
        ):
            point = json.loads(raw)
            at = datetime.fromisoformat(point["at"])
            if (at.tzinfo is None or previous is not None and at <= previous
                    or not isinstance(point["equity"], str)
                    or not Decimal(point["equity"]).is_finite()):
                raise ValueError("TQ_EQUITY_HISTORY_INVALID")
            previous = at
            curve.append(dict(at=point["at"], equity=point["equity"],
                              net_profit=None, trading_day=point["trading_day"]))
        after = path.lstat()
        if (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("TQ_PRIVATE_JOURNAL_DRIFT")
        return curve
    finally:
        db.close()


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
