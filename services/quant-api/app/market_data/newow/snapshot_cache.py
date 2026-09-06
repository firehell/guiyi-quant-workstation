"""Bounded process-local Newow result reuse; never a data authority."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import RLock
from time import monotonic


@dataclass(slots=True)
class _Entry:
    fact_key: str
    section_key: tuple[object, ...]
    value: object
    size: int
    token: str
    expires_at: float


class SnapshotCache:
    def __init__(
        self,
        *,
        max_entries: int = 32,
        max_bytes: int = 128 * 1024 * 1024,
        max_entry_bytes: int = 32 * 1024 * 1024,
        ttl_seconds: float = 300,
        enabled: bool = True,
        now: Callable[[], float] = monotonic,
    ) -> None:
        if min(max_entries, max_bytes, max_entry_bytes) <= 0 or ttl_seconds <= 0:
            raise ValueError("NEWOW_CACHE_INVALID_BUDGET")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._max_entry_bytes = max_entry_bytes
        self._ttl = ttl_seconds
        self._enabled = enabled
        self._now = now
        self._entries: OrderedDict[tuple[str, tuple[object, ...]], _Entry] = (
            OrderedDict()
        )
        self._tokens: dict[str, tuple[str, tuple[object, ...]]] = {}
        self._bytes = 0
        self._lock = RLock()

    def _drop(self, key: tuple[str, tuple[object, ...]]) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._tokens.pop(entry.token, None)
            self._bytes -= entry.size

    def _expire(self) -> None:
        current = self._now()
        for key, entry in tuple(self._entries.items()):
            if entry.expires_at <= current:
                self._drop(key)

    def put(
        self,
        fact_key: str,
        section_key: tuple[object, ...],
        value: object,
        retained_size: int,
        *,
        token: str | None = None,
    ) -> str | None:
        if (
            not self._enabled
            or not isinstance(fact_key, str)
            or not fact_key
            or type(retained_size) is not int
            or retained_size < 0
            or retained_size > self._max_entry_bytes
            or retained_size > self._max_bytes
        ):
            return None
        key = (fact_key, tuple(section_key))
        with self._lock:
            self._expire()
            self._drop(key)
            token = token or token_urlsafe(24)
            entry = _Entry(
                fact_key,
                key[1],
                value,
                retained_size,
                token,
                self._now() + self._ttl,
            )
            self._entries[key] = entry
            self._tokens[token] = key
            self._bytes += retained_size
            while (
                len(self._entries) > self._max_entries or self._bytes > self._max_bytes
            ):
                self._drop(next(iter(self._entries)))
            return token if key in self._entries else None

    def get(self, fact_key: str, section_key: tuple[object, ...]) -> object | None:
        key = (fact_key, tuple(section_key))
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry.value

    def get_by_token(
        self,
        token: str,
        fact_key: str,
        section_key: tuple[object, ...],
    ) -> object | None:
        with self._lock:
            self._expire()
            key = self._tokens.get(token)
            expected = (fact_key, tuple(section_key))
            if key != expected:
                return None
            return self.get(fact_key, section_key)

    def fact_key_for_token(self, token: str) -> str | None:
        with self._lock:
            self._expire()
            key = self._tokens.get(token)
            return None if key is None else key[0]
