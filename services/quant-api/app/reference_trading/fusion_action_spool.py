"""Temporary indexed actions for one verified historical Fusion read."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from itertools import groupby
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory


def _instant(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
    return value.astimezone(UTC).isoformat()


def _decode(row):
    from app.reference_trading.inputs import _action_from_wire

    if sha256(row[6].encode()).hexdigest() != row[5]:
        raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
    action = _action_from_wire(json.loads(row[6]))
    if (
        row[:4] != (
            _instant(action.bar_end), action.physical_contract,
            action.segment_id, action.calculation_segment_id,
        )
        or row[4] != action.signal_id
    ):
        raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
    return action


class FusionActionSpool:
    """Keep decoded source actions off heap until their matching bar is read."""

    def __init__(self):
        self._directory = TemporaryDirectory(prefix="guiyi-fusion-actions-")
        self._path = Path(self._directory.name) / "actions.sqlite"
        self._connection: sqlite3.Connection | None = None
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            connection = sqlite3.connect(self._path)
            self._connection = connection
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA cache_size=-2048")
            connection.execute(
                "CREATE TABLE actions ("
                "ordinal INTEGER PRIMARY KEY, bar_end TEXT NOT NULL, "
                "physical_contract TEXT NOT NULL, segment_id TEXT NOT NULL, "
                "calculation_segment_id TEXT NOT NULL, signal_id TEXT NOT NULL, "
                "payload_sha256 TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX actions_by_bar ON actions "
                "(bar_end, physical_contract, segment_id, calculation_segment_id, ordinal)"
            )
        except BaseException:
            self.close()
            raise

    def append(self, action):
        from app.reference_trading.inputs import _action_wire

        if self._connection is None:
            raise ValueError("REFERENCE_FUSION_ACTION_SPOOL_CLOSED")
        wire = _action_wire(action)
        payload = json.dumps(wire, sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            self._connection.execute(
                "INSERT INTO actions "
                "(bar_end, physical_contract, segment_id, calculation_segment_id, "
                "signal_id, payload_sha256, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _instant(action.bar_end), action.physical_contract,
                    action.segment_id, action.calculation_segment_id,
                    action.signal_id, sha256(payload.encode()).hexdigest(), payload,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY") from error

    def get(self, key, default=()):
        if self._connection is None:
            raise ValueError("REFERENCE_FUSION_ACTION_SPOOL_CLOSED")
        if not isinstance(key, tuple) or len(key) != 4:
            raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
        cursor = self._connection.execute(
            "SELECT bar_end, physical_contract, segment_id, calculation_segment_id, "
            "signal_id, payload_sha256, payload FROM actions "
            "WHERE bar_end=? AND physical_contract=? "
            "AND segment_id=? AND calculation_segment_id=? ORDER BY ordinal",
            (_instant(key[0]), *key[1:]),
        )
        try:
            values = tuple(_decode(row) for row in cursor)
        finally:
            cursor.close()
        return values if values else default

    def items(self):
        if self._connection is None:
            raise ValueError("REFERENCE_FUSION_ACTION_SPOOL_CLOSED")
        cursor = self._connection.execute(
            "SELECT bar_end, physical_contract, segment_id, calculation_segment_id, "
            "signal_id, payload_sha256, payload "
            "FROM actions ORDER BY bar_end, physical_contract, segment_id, "
            "calculation_segment_id, ordinal"
        )
        try:
            for raw_key, rows in groupby(cursor, key=lambda row: row[:4]):
                yield (
                    (datetime.fromisoformat(raw_key[0]), *raw_key[1:]),
                    tuple(_decode(row) for row in rows),
                )
        finally:
            cursor.close()

    def close(self):
        connection, self._connection = self._connection, None
        try:
            if connection is not None:
                connection.close()
        finally:
            self._directory.cleanup()
