"""FIFO process-local admission control for heavy read-only Newow calculations."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from threading import Condition
from time import monotonic


class NewowResourceBusy(RuntimeError):
    code = "NEWOW_RESOURCE_BUSY"


class _Lease(AbstractContextManager["_Lease"]):
    def __init__(self, gate: "HeavyResourceGate") -> None:
        self._gate = gate
        self._released = False

    def __enter__(self) -> "_Lease":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._gate._release()


class HeavyResourceGate:
    def __init__(
        self,
        *,
        max_running: int = 1,
        max_waiting: int = 2,
        wait_timeout: float = 5,
    ) -> None:
        if max_running <= 0 or max_waiting < 0 or wait_timeout <= 0:
            raise ValueError("NEWOW_RESOURCE_INVALID_BUDGET")
        self._max_running = max_running
        self._max_waiting = max_waiting
        self._timeout = wait_timeout
        self._running = 0
        self._waiters: deque[object] = deque()
        self._condition = Condition()

    @property
    def running(self) -> int:
        with self._condition:
            return self._running

    @property
    def waiting(self) -> int:
        with self._condition:
            return len(self._waiters)

    def acquire(self, cancelled: Callable[[], bool] | None = None) -> _Lease:
        with self._condition:
            if self._running < self._max_running and not self._waiters:
                self._running += 1
                return _Lease(self)
            if len(self._waiters) >= self._max_waiting:
                raise NewowResourceBusy(NewowResourceBusy.code)
            ticket = object()
            self._waiters.append(ticket)
            deadline = monotonic() + self._timeout
            try:
                while True:
                    if cancelled is not None and cancelled():
                        raise NewowResourceBusy("NEWOW_RESOURCE_CANCELLED")
                    if (
                        self._waiters
                        and self._waiters[0] is ticket
                        and self._running < self._max_running
                    ):
                        self._waiters.popleft()
                        self._running += 1
                        return _Lease(self)
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise NewowResourceBusy(NewowResourceBusy.code)
                    self._condition.wait(min(remaining, 0.05))
            except BaseException:
                if ticket in self._waiters:
                    self._waiters.remove(ticket)
                    self._condition.notify_all()
                raise

    def _release(self) -> None:
        with self._condition:
            if self._running <= 0:
                raise RuntimeError("NEWOW_RESOURCE_RELEASE_CONFLICT")
            self._running -= 1
            self._condition.notify_all()
