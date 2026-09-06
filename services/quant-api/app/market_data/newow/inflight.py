"""Request-scoped in-flight reuse with last-consumer cancellation semantics."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from threading import Condition, RLock
from typing import TypeVar, cast


_T = TypeVar("_T")


class NewowComputationCancelled(RuntimeError):
    code = "NEWOW_REQUEST_CANCELLED"


@dataclass(slots=True)
class _Call:
    condition: Condition
    consumers: dict[object, Callable[[], bool]] = field(default_factory=dict)
    done: bool = False
    result: object | None = None
    error: BaseException | None = None


class InFlightCoordinator:
    """Deduplicate identical work without making the result a data authority."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._calls: dict[Hashable, _Call] = {}

    def execute(
        self,
        key: Hashable,
        operation: Callable[[Callable[[], bool]], _T],
        cancelled: Callable[[], bool] | None = None,
    ) -> _T:
        caller_cancelled = cancelled or (lambda: False)
        consumer = object()
        with self._lock:
            call = self._calls.get(key)
            leader = call is None
            if call is None:
                call = _Call(Condition(self._lock))
                self._calls[key] = call
            call.consumers[consumer] = caller_cancelled

        if leader:
            try:
                result = operation(lambda: self._all_consumers_cancelled(call))
            except BaseException as error:
                with self._lock:
                    call.error = error
                    call.done = True
                    call.condition.notify_all()
            else:
                with self._lock:
                    call.result = result
                    call.done = True
                    call.condition.notify_all()

        with self._lock:
            try:
                while not call.done:
                    if caller_cancelled():
                        raise NewowComputationCancelled(NewowComputationCancelled.code)
                    call.condition.wait(0.05)
                if caller_cancelled():
                    raise NewowComputationCancelled(NewowComputationCancelled.code)
                if call.error is not None:
                    raise call.error
                return cast(_T, call.result)
            finally:
                call.consumers.pop(consumer, None)
                if call.done and not call.consumers:
                    self._calls.pop(key, None)
                call.condition.notify_all()

    def _all_consumers_cancelled(self, call: _Call) -> bool:
        with self._lock:
            return not call.consumers or all(
                callback() for callback in call.consumers.values()
            )
