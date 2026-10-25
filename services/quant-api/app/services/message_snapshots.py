"""Bounded process-local message snapshots; never an authority for new facts."""

import base64
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import secrets
from threading import Lock
from time import monotonic

from app.market_messages import MessageCursorError


def decode_cursor(value: str) -> dict:
    try:
        if len(value) > 4096:
            raise ValueError
        result = json.loads(
            base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            )
        )
        if (
            not isinstance(result, dict)
            or type(result.get("v")) is not int
            or result["v"] != 2
            or set(result) != {"v", "query", "snapshot", "digest", "offset", "token"}
            or not isinstance(result["token"], str)
            or len(result["token"]) != 32
            or not isinstance(result["query"], dict)
            or not isinstance(result["snapshot"], dict)
            or not isinstance(result["digest"], str)
            or len(result["digest"]) != 64
            or any(
                character not in "0123456789abcdef" for character in result["digest"]
            )
            or type(result["offset"]) is not int
            or not 0 <= result["offset"] <= 10000
        ):
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError):
        raise MessageCursorError from None


def encode_cursor(payload: dict) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


class MessageSnapshotBudgetError(ValueError):
    pass


@dataclass(frozen=True)
class _Snapshot:
    rows: list[dict]
    sources: dict
    query: dict
    snapshot: dict
    digest: str
    created: float
    size: int


class MessageSnapshots:
    def __init__(
        self, *, ttl=120, max_entries=16, max_bytes=32 * 1024 * 1024, clock=monotonic
    ):
        self.ttl, self.max_entries, self.max_bytes = ttl, max_entries, max_bytes
        self.clock = clock
        self._entries: OrderedDict[str, _Snapshot] = OrderedDict()
        self._lock = Lock()

    def create(self, rows, sources, query, snapshot, *, resume_count=0):
        rows = sorted(
            rows,
            key=lambda row: (
                datetime.fromisoformat(
                    row["bar_end"].replace("Z", "+00:00")
                ).timestamp(),
                row["source"],
                str(row["id"]).zfill(24),
            ),
            reverse=True,
        )
        encoded = json.dumps(
            [rows, sources], sort_keys=True, separators=(",", ":")
        ).encode()
        size = len(encoded) + len(json.dumps([query, snapshot]).encode())
        if size > self.max_bytes:
            raise MessageSnapshotBudgetError
        entry = _Snapshot(
            deepcopy(rows),
            deepcopy(sources),
            deepcopy(query),
            deepcopy(snapshot),
            hashlib.sha256(encoded).hexdigest(),
            self.clock(),
            size,
        )
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._expire()
            while self._entries and (
                len(self._entries) >= self.max_entries
                or sum(item.size for item in self._entries.values()) + size
                > self.max_bytes
            ):
                self._entries.popitem(last=False)
            self._entries[token] = entry
        result = self._page(token, entry, 0)
        result["resume_cursor"] = (
            self._cursor(token, entry, resume_count)
            if resume_count < len(rows)
            else None
        )
        return result

    def read(self, cursor, query):
        value = decode_cursor(cursor)
        if value["v"] != 2 or value["query"] != query:
            raise MessageCursorError
        token = value["token"]
        with self._lock:
            self._expire()
            entry = self._entries.get(token)
            if (
                entry is None
                or entry.query != query
                or value["snapshot"] != entry.snapshot
                or value["digest"] != entry.digest
            ):
                raise MessageCursorError
            offset = value["offset"]
            if offset <= 0 or offset >= len(entry.rows):
                raise MessageCursorError
            self._entries.move_to_end(token)
            result = self._page(token, entry, offset)
        return result

    def _expire(self):
        now = self.clock()
        for key, item in list(self._entries.items()):
            if now - item.created >= self.ttl:
                del self._entries[key]

    @staticmethod
    def _cursor(token, entry, offset):
        return encode_cursor(
            dict(
                v=2,
                token=token,
                query=entry.query,
                snapshot=entry.snapshot,
                digest=entry.digest,
                offset=offset,
            )
        )

    def _page(self, token, entry, offset):
        return deepcopy(
            dict(
                items=entry.rows[offset : offset + 20],
                dataset_hash=entry.digest,
                next_cursor=self._cursor(token, entry, offset + 20)
                if offset + 20 < len(entry.rows)
                else None,
                available_count=len(entry.rows),
                sources=entry.sources,
                snapshot=entry.snapshot,
                coverage="partial"
                if any(
                    s.get("status") != "ready"
                    or s.get("truncated")
                    or s.get("excluded_streams", 0)
                    for s in entry.sources.values()
                )
                else "complete",
            )
        )
