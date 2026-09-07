"""Bounded process-local Newow result reuse; never a data authority."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from secrets import token_urlsafe
from threading import RLock
from time import monotonic
import sys


@dataclass(slots=True)
class _Entry:
    fact_key: str
    token: str
    expires_at: float
    values: dict[tuple[object, ...], object]
    retained_bytes: int
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
            self._entries = OrderedDict(self._entries.items())
            self._tokens = dict(self._tokens.items())
            self._bytes = self._retained_bytes(self._entries, self._tokens)

    @staticmethod
    def _retained_bytes(
        entries: OrderedDict[str, _Entry], tokens: dict[str, str]
    ) -> int:
        return (
            sum(entry.retained_bytes for entry in entries.values())
            + sys.getsizeof(entries) + sys.getsizeof(tokens)
        )

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
        *,
        token: str | None = None,
        proof: dict[str, str] | None = None,
    ) -> str | None:
        if (
            not self._enabled
            or not isinstance(fact_key, str)
            or not fact_key
        ):
            return None
        normalized_section = tuple(section_key)
        with self._lock:
            self._expire()
            previous = self._entries.get(fact_key)
            normalized_proof = dict(proof or {})
            compatible = previous is not None and self._proofs_compatible(
                previous.proof, normalized_proof
            )
            if token is not None and (
                previous is None or not compatible or token != previous.token
            ):
                return None
            # Build a candidate off to the side. A rejected extension/revision must
            # not alter the accepted proof, values, token, TTL or LRU position.
            values = dict(previous.values) if compatible and previous else {}
            merged_proof = dict(previous.proof) if compatible and previous else {}
            merged_proof.update(normalized_proof)
            values[normalized_section] = value
            candidate = _Entry(
                fact_key,
                previous.token if compatible and previous else token_urlsafe(24),
                self._now() + self._ttl,
                values,
                0,
                merged_proof,
            )
            # Reserve the final counter integer as well as the complete payload.
            # The zero placeholder can share identity with a value in the graph.
            candidate.retained_bytes = _retained_size(candidate) + sys.getsizeof(
                max(self._max_entry_bytes, self._max_bytes)
            )
            single_entries = OrderedDict([(fact_key, candidate)])
            single_tokens = {candidate.token: fact_key}
            if self._retained_bytes(single_entries, single_tokens) > min(
                self._max_entry_bytes, self._max_bytes
            ):
                return None
            pending = OrderedDict(
                (key, entry) for key, entry in self._entries.items() if key != fact_key
            )
            pending[fact_key] = candidate
            while True:
                # Measure the actual indexes that will be retained, including
                # their allocated capacity; deletions alone do not shrink dicts.
                pending = OrderedDict(pending.items())
                pending_tokens = {entry.token: key for key, entry in pending.items()}
                retained_bytes = self._retained_bytes(pending, pending_tokens)
                if len(pending) <= self._max_entries and retained_bytes <= self._max_bytes:
                    break
                pending.popitem(last=False)
            self._entries = pending
            self._tokens = pending_tokens
            self._bytes = retained_bytes
            return candidate.token

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


def _retained_size(value: object, seen: set[int] | None = None) -> int:
    """Conservative size of the retained graph, counting shared objects once."""
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        attributes = getattr(value, "__dict__", None)
        if attributes is not None:
            return size + _retained_size(attributes, seen)
        return size + sum(
            _retained_size(getattr(value, field.name), seen) for field in fields(value)
        )
    if isinstance(value, Mapping):
        return size + sum(
            _retained_size(key, seen) + _retained_size(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return size + sum(_retained_size(item, seen) for item in value)
    return size
