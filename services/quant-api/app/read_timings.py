"""Bounded, request-local phase durations. Never retain input or result data.

Phases may nest (replay is part of compute); durations are not additive.
Context propagation into FastAPI's sync worker shares only this small collector.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock
from time import perf_counter
from typing import Callable, ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")
_NAMES = frozenset({"queue", "read", "verify", "cache", "compute", "replay", "projection",
                    "catalog", "mapping", "session", "file_read", "integrity", "parquet", "assemble", "response_encode"})


class DetailTimings:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self._lock = Lock()
        self.projected_at: float | None = None

    def add(self, name: str, milliseconds: float) -> None:
        with self._lock:
            self.values[name] = self.values.get(name, 0) + milliseconds
            self.counts[name] = self.counts.get(name, 0) + 1

    def header(self, total_ms: float) -> str:
        with self._lock:
            entries = sorted(self.values.items())
            if self.projected_at is not None and "response_encode" not in self.values:
                # FastAPI response-model encoding and response construction
                # after the final projection; excludes network/gzip delivery.
                entries.append(("response_encode", (perf_counter() - self.projected_at) * 1000))
        return ", ".join(f'{name};dur={duration:.2f};desc="{self.counts.get(name, 1)} calls"' for name, duration in
                         [("total", total_ms), *entries])


_current: ContextVar[DetailTimings | None] = ContextVar("newow_read_timings", default=None)


@contextmanager
def detail_timings():
    metrics = DetailTimings()
    token = _current.set(metrics)
    try:
        yield metrics
    finally:
        _current.reset(token)


@contextmanager
def phase(name: str):
    if name not in _NAMES:
        raise ValueError("unknown timing phase")
    metrics = _current.get()
    if metrics is None:
        yield
        return
    started = perf_counter()
    try:
        yield
        if name == "projection":
            metrics.projected_at = perf_counter()
    finally:
        metrics.add(name, (perf_counter() - started) * 1000)


def timed(name: str) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def decorate(function: Callable[_P, _T]) -> Callable[_P, _T]:
        @wraps(function)
        def measured(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with phase(name):
                return function(*args, **kwargs)
        return measured
    return decorate
