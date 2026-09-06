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
    token: str
    expires_at: float
    values: dict[tuple[object, ...], object]
    sizes: dict[tuple[object, ...], int]
    proof: dict[str, str]


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
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._tokens: dict[str, str] = {}
        self._bytes = 0
        self._lock = RLock()

    def _drop(self, fact_key: str) -> None:
        entry = self._entries.pop(fact_key, None)
        if entry is not None:
            self._tokens.pop(entry.token, None)
            self._bytes -= sum(entry.sizes.values())

    def _expire(self) -> None:
        current = self._now()
        for fact_key, entry in tuple(self._entries.items()):
            if entry.expires_at <= current:
                self._drop(fact_key)

    def put(
        self,
        fact_key: str,
        section_key: tuple[object, ...],
        value: object,
        retained_size: int,
        *,
        token: str | None = None,
        proof: dict[str, str] | None = None,
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
        normalized_section = tuple(section_key)
        with self._lock:
            self._expire()
            entry = self._entries.get(fact_key)
            normalized_proof = dict(proof or {})
            if entry is not None and not self._proofs_compatible(
                entry.proof, normalized_proof
            ):
                if token is not None:
                    return None
                self._drop(fact_key)
                entry = None
            if entry is None:
                token = token or token_urlsafe(24)
                entry = _Entry(
                    fact_key,
                    token,
                    self._now() + self._ttl,
                    {},
                    {},
                    normalized_proof,
                )
                self._entries[fact_key] = entry
                self._tokens[token] = fact_key
            elif token is not None and token != entry.token:
                return None
            else:
                entry.proof.update(normalized_proof)
            previous_size = entry.sizes.get(normalized_section, 0)
            retained_total = sum(entry.sizes.values()) - previous_size + retained_size
            if retained_total > self._max_entry_bytes:
                return None
            entry.values[normalized_section] = value
            entry.sizes[normalized_section] = retained_size
            entry.expires_at = self._now() + self._ttl
            self._entries.move_to_end(fact_key)
            self._bytes -= previous_size
            self._bytes += retained_size
            while (
                len(self._entries) > self._max_entries or self._bytes > self._max_bytes
            ):
                self._drop(next(iter(self._entries)))
            return entry.token if fact_key in self._entries else None

    def get(self, fact_key: str, section_key: tuple[object, ...]) -> object | None:
        with self._lock:
            self._expire()
            entry = self._entries.get(fact_key)
            if entry is None:
                return None
            self._entries.move_to_end(fact_key)
            return entry.values.get(tuple(section_key))

    def get_by_token(
        self,
        token: str,
        fact_key: str,
        section_key: tuple[object, ...],
    ) -> object | None:
        with self._lock:
            self._expire()
            bound_fact_key = self._tokens.get(token)
            if bound_fact_key != fact_key:
                return None
            return self.get(fact_key, section_key)

    def fact_key_for_token(self, token: str) -> str | None:
        with self._lock:
            self._expire()
            return self._tokens.get(token)

    def token_is_compatible(
        self, token: str, fact_key: str, proof: dict[str, str]
    ) -> bool:
        with self._lock:
            self._expire()
            if self._tokens.get(token) != fact_key:
                return False
            entry = self._entries.get(fact_key)
            return entry is not None and self._proofs_compatible(entry.proof, proof)

    @staticmethod
    def _proofs_compatible(left: dict[str, str], right: dict[str, str]) -> bool:
        if not left and not right:
            return True
        shared = left.keys() & right.keys()
        shared_bars = tuple(key for key in shared if key.startswith("bar|"))
        return bool(shared_bars) and all(left[key] == right[key] for key in shared)
