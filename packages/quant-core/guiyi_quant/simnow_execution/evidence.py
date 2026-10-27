"""Private native snapshots, retained across one-shot sessions for fees/readback."""

from pathlib import Path
import json
import os
import sqlite3
from .inventory import Snapshot, at


class Evidence:
    def __init__(self, path, account_id):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("PRIVATE_EVIDENCE_REQUIRED")
        try:
            fd = os.open(
                self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            if not self.path.is_file() or self.path.stat().st_mode & 0o077:
                raise ValueError("PRIVATE_EVIDENCE_REQUIRED") from None
            created = False
        else:
            os.close(fd)
            created = True
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        if created:
            self.conn.executescript(
                "CREATE TABLE owner(account TEXT);CREATE TABLE snapshots(source TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TRIGGER no_update BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;CREATE TRIGGER no_delete BEFORE DELETE ON snapshots BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"
            )
            self.conn.execute("INSERT INTO owner VALUES (?)", (account_id,))
        if self.conn.execute("SELECT account FROM owner").fetchall() != [(account_id,)]:
            raise ValueError("EVIDENCE_ACCOUNT_MISMATCH")
        self.account_id = account_id

    def append(self, snapshot):
        if snapshot.account_id != self.account_id:
            raise ValueError("EVIDENCE_ACCOUNT_MISMATCH")
        payload = json.dumps(
            dict(
                account_id=snapshot.account_id,
                trading_day=snapshot.trading_day,
                started_at=snapshot.started_at.isoformat(),
                at=snapshot.at.isoformat(),
                source_id=snapshot.source_id,
                payload_json=snapshot.payload_json,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        previous = self.conn.execute(
            "SELECT payload FROM snapshots WHERE source=?", (snapshot.source_id,)
        ).fetchone()
        if previous:
            if previous[0] != payload:
                raise ValueError("NATIVE_EVIDENCE_CONFLICT")
            return
        latest = self.latest()
        if latest and snapshot.started_at < latest.at:
            raise ValueError("NATIVE_EVIDENCE_OVERLAP")
        self.conn.execute(
            "INSERT INTO snapshots VALUES (?,?)", (snapshot.source_id, payload)
        )

    @staticmethod
    def _decode(payload):
        fields = json.loads(payload)
        fields["at"] = at(fields["at"])
        fields["started_at"] = at(fields["started_at"])
        return Snapshot(**fields)

    def snapshots(self, after=0):
        if type(after) is not int or after < 0:
            raise ValueError("EVIDENCE_CURSOR_INVALID")
        result = []
        for (payload,) in self.conn.execute(
            "SELECT payload FROM snapshots WHERE rowid>? ORDER BY rowid", (after,)
        ):
            result.append(self._decode(payload))
        return tuple(result)

    def latest(self):
        row = self.conn.execute(
            "SELECT payload FROM snapshots ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return self._decode(row[0]) if row else None

    def close(self):
        self.conn.close()
