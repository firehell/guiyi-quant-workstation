"""Bounded source curve retaining each trading day's first/min/max/last valuations."""
from __future__ import annotations

from decimal import Decimal


class CurveRecorder:
    def __init__(self) -> None:
        self._done: list[dict] = []
        self._key = None
        self._first = self._low = self._high = self._last = None

    def add(self, key: tuple, point: dict) -> None:
        if self._key != key:
            self._flush()
            self._key = key
            self._first = self._low = self._high = point
        self._last = point
        if Decimal(point['value']) < Decimal(self._low['value']):
            self._low = point
        if Decimal(point['value']) > Decimal(self._high['value']):
            self._high = point

    def _flush(self) -> None:
        points = {p['at']: p for p in (self._first, self._low, self._high, self._last) if p is not None}
        self._done.extend(points[t] for t in sorted(points))

    def finish(self) -> list[dict]:
        self._flush()
        self._first = self._low = self._high = self._last = None
        self._key = None
        return self._done
