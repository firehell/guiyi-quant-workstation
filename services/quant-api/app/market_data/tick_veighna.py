"""Headless VeighNa dispatch. At most one bounded ingress batch is outstanding."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, TimeoutError
from importlib.metadata import version
from threading import Lock
from typing import Any

_EVENT = "guiyi.market.tick.batch"


class VeighNaTickDispatch:
    def __init__(self) -> None:
        if version("vnpy") != "4.4.0":
            raise ValueError("TICK_EVENT_ENGINE_VERSION_UNPROVED")
        from vnpy.event import Event, EventEngine  # type: ignore[import-not-found, import-untyped]

        self._event = Event
        self._engine = EventEngine()
        self._engine.register(_EVENT, self._consume)
        self._admission = Lock()
        self._closed = False
        self._failed = False
        self._engine.start()

    @staticmethod
    def _consume(event: Any) -> None:
        function, items, result = event.data
        try:
            result.set_result(function(items))
        except Exception as exc:
            result.set_exception(exc)

    def __call__(self, function: Callable, items: tuple) -> Any:
        if not self._admission.acquire(blocking=False):
            raise ConnectionError("TICK_EVENT_ENGINE_BUSY")
        try:
            if self._closed or self._failed:
                raise ConnectionError("TICK_EVENT_ENGINE_UNAVAILABLE")
            result: Future = Future()
            self._engine.put(self._event(_EVENT, (function, items, result)))
            try:
                return result.result(timeout=2)
            except TimeoutError:
                self._failed = True
                raise ConnectionError("TICK_EVENT_ENGINE_TIMEOUT") from None
        finally:
            self._admission.release()

    def close(self) -> None:
        with self._admission:
            if not self._closed:
                self._closed = True
                self._engine.stop()
