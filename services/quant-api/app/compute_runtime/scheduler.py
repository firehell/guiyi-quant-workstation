"""Separate, bounded application work queues for the three compute modes."""

from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, RLock


class ComputeBusy(RuntimeError):
    """The mode's running and waiting work has reached its configured bound."""


class JobQueue[T]:
    def __init__(self, name: str, max_pending: int) -> None:
        if max_pending < 1:
            raise ValueError("COMPUTE_QUEUE_LIMIT_INVALID")
        self._name = name
        self._limit = max_pending
        self._lock = RLock()
        self._closed = False
        self._peak_pending = 0
        self._rejected = 0
        self._jobs: dict[Hashable, tuple[Future[T], Event]] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"compute-{name}")

    def submit(self, key: Hashable, run: Callable[[Event], T]) -> Future[T]:
        with self._lock:
            if self._closed:
                raise RuntimeError("COMPUTE_QUEUE_CLOSED")
            existing = self._jobs.get(key)
            if existing is not None:
                if existing[1].is_set():
                    raise ValueError("COMPUTE_REVISION_INVALIDATED")
                return _waiter(existing[0])
            if len(self._jobs) >= self._limit:
                self._rejected += 1
                raise ComputeBusy(self._name)
            invalidated = Event()
            job = self._executor.submit(run, invalidated)
            self._jobs[key] = (job, invalidated)
            self._peak_pending = max(self._peak_pending, len(self._jobs))
            job.add_done_callback(lambda _: self._remove(key))
            return _waiter(job)

    def invalidate(self, matches: Callable[[Hashable], bool]) -> None:
        with self._lock:
            for key, (_, invalidated) in self._jobs.items():
                if matches(key):
                    invalidated.set()

    def _remove(self, key: Hashable) -> None:
        with self._lock:
            del self._jobs[key]

    def queue_load(self) -> dict[str, int]:
        with self._lock:
            return {
                "pending": len(self._jobs), "peak_pending": self._peak_pending, "rejected": self._rejected,
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
        # Executor cancellation invokes callbacks that acquire this queue's lock.
        self._executor.shutdown(wait=True, cancel_futures=True)


def _waiter[T](job: Future[T]) -> Future[T]:
    shared = Future[T]()

    def relay(done: Future[T]) -> None:
        if not shared.set_running_or_notify_cancel():
            return
        if done.cancelled():
            shared.set_exception(RuntimeError("COMPUTE_QUEUE_CLOSED"))
        elif (error := done.exception()) is not None:
            shared.set_exception(error)
        else:
            shared.set_result(done.result())

    job.add_done_callback(relay)
    return shared
