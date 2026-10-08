"""Default-off, single-thread forward reference worker scheduler."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic, sleep

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.forward_service import ForwardReferenceService
from app.reference_trading.forward_inputs import ForwardInputUnavailable
from app.reference_trading.repository import ReferenceRepository


@dataclass(frozen=True, slots=True)
class WorkerBudget:
    max_pending_keys: int = 512
    max_units_per_round: int = 32
    max_stream_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_pending_keys <= 512 or not 1 <= self.max_units_per_round <= 32:
            raise ValueError("FORWARD_WORKER_BUDGET_INVALID")
        if not 0 < self.max_stream_seconds <= 5:
            raise ValueError("FORWARD_WORKER_BUDGET_INVALID")


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    enabled_count: int
    pending_keys: int
    last_success: datetime | None
    blocked: tuple[tuple[str, str], ...]


class ForwardReferenceWorker:
    def __init__(
        self, repository: ReferenceRepository,
        service_for: Callable[[str], ForwardReferenceService],
        read_input: Callable[[str, str, datetime | None], ForwardCapture | None],
        *, enabled: bool = False, budget: WorkerBudget = WorkerBudget(),
        begin_unit: Callable[[], None] = lambda: None,
        end_unit: Callable[[], None] = lambda: None,
    ) -> None:
        self._repository = repository
        self._service_for = service_for
        self._read_input = read_input
        self._begin_unit = begin_unit
        self._end_unit = end_unit
        self._remaining: dict[str, tuple[str, ...]] = {}
        self._deferred: dict[str, tuple[str, datetime | None]] = {}
        self._enabled = enabled
        self._budget = budget
        self._queue: deque[str] = deque()
        self._queued: dict[str, tuple[str, datetime | None]] = {}
        self._blocked: dict[str, str] = {}
        self._last_success: datetime | None = None
        self._scan_after: str | None = None

    def wake(
        self, stream_id: str, *, kind: str = "scan",
        bar_end: datetime | None = None,
    ) -> bool:
        if kind not in {"live_event", "scan"}:
            raise ValueError("WORKER_WAKE_INVALID")
        if kind == "live_event" and (
            not isinstance(bar_end, datetime) or bar_end.tzinfo is None
            or bar_end.utcoffset() is None
        ):
            raise ValueError("WORKER_EVENT_BAR_INVALID")
        if kind == "scan" and bar_end is not None:
            raise ValueError("WORKER_EVENT_BAR_INVALID")
        if not self._enabled:
            return False
        stream_id = self._work_key(stream_id)
        if stream_id in self._remaining:
            if kind == "live_event":
                previous = self._deferred.get(stream_id)
                if previous is None or previous[0] != "live_event" or bar_end > previous[1]:
                    self._deferred[stream_id] = (kind, bar_end)
            return False
        if stream_id in self._queued:
            if kind == "live_event":
                previous_kind, previous_end = self._queued[stream_id]
                if previous_kind != "live_event" or bar_end > previous_end:
                    self._queued[stream_id] = (kind, bar_end)
            return False
        if len(self._queue) >= self._budget.max_pending_keys:
            self._blocked[stream_id] = "WORKER_QUEUE_FULL"
            return False
        self._queue.append(stream_id)
        self._queued[stream_id] = (kind, bar_end)
        return True

    def _work_key(self, stream_id: str) -> str:
        resolver = getattr(self._repository, "forward_work_key", None)
        if resolver is None or stream_id.startswith(("newow:", "stream:")):
            return stream_id
        return resolver(stream_id) or f"stream:{stream_id}"

    def _work_routes(self, key: str) -> tuple[str, ...]:
        resolver = getattr(self._repository, "enabled_forward_work_routes", None)
        return resolver(key) if resolver is not None else (key,)

    def _enabled_keys(self, *, limit: int = 512, after: str | None = None):
        reader = getattr(self._repository, "enabled_forward_work_keys", None)
        if reader is None:
            reader = self._repository.enabled_forward_stream_ids
        return reader(limit=limit, after=after)

    def scan(self) -> None:
        if not self._enabled:
            return
        available = self._budget.max_pending_keys - len(self._queue)
        if available <= 0:
            return
        keys = self._enabled_keys(limit=available, after=self._scan_after)
        if not keys and self._scan_after is not None:
            self._scan_after = None
            keys = self._enabled_keys(limit=available)
        for key in keys:
            self.wake(key, kind="scan")
        if keys:
            self._scan_after = keys[-1]

    def run_round(self) -> int:
        if not self._enabled:
            return 0
        completed, units = 0, 0
        for _ in range(len(self._queue)):
            if units >= self._budget.max_units_per_round:
                break
            key = self._queue.popleft()
            kind, event_bar_end = self._queued.pop(key)
            routes = self._remaining.pop(key, None)
            if routes is None:
                try:
                    routes = self._work_routes(key)
                except Exception as error:  # noqa: BLE001 - isolate scope conflicts
                    self._blocked[key] = type(error).__name__
                    continue
            self._blocked.pop(key, None)
            started, consumed, needs_scan = monotonic(), 0, False
            self._begin_unit()
            try:
                for stream_id in routes:
                    if units >= self._budget.max_units_per_round:
                        break
                    units += 1
                    consumed += 1
                    try:
                        service = self._service_for(stream_id)
                        pending = self._repository.read_pending_capture(stream_id)
                        if pending is not None:
                            result = service.process_pending(stream_id)
                            needs_scan = True
                        else:
                            capture = self._read_input(stream_id, kind, event_bar_end)
                            result = None
                            if capture is not None:
                                self._repository.capture_forward(capture)
                                result = service.process_pending(stream_id)
                        if result is not None:
                            completed += 1
                            self._last_success = datetime.now(UTC)
                        self._blocked.pop(stream_id, None)
                    except Exception as error:  # noqa: BLE001
                        self._blocked[stream_id] = (
                            str(error) if isinstance(error, ForwardInputUnavailable)
                            else type(error).__name__
                        )
                    if monotonic() - started >= self._budget.max_stream_seconds:
                        needs_scan = True
                        break
            finally:
                self._end_unit()
            remaining = routes[consumed:]
            if remaining:
                if needs_scan and key not in self._deferred:
                    self._deferred[key] = ("scan", None)
                self._queue.append(key)
                self._queued[key] = (kind, event_bar_end)
                self._remaining[key] = remaining
            else:
                deferred = self._deferred.pop(key, None)
                if deferred is not None:
                    self.wake(key, kind=deferred[0], bar_end=deferred[1])
                elif needs_scan:
                    self.wake(key, kind="scan")
        return completed

    def serve(
        self, *, should_stop: Callable[[], bool],
        wait: Callable[[float], None] = sleep, scan_interval_seconds: float = 5.0,
    ) -> None:
        """Recover pending captures first, then scan enabled streams every cycle."""
        if not 0 < scan_interval_seconds <= 5:
            raise ValueError("WORKER_SCAN_INTERVAL_INVALID")
        if not self._enabled:
            return
        while not should_stop():
            self.scan()
            self.run_round()
            if not should_stop():
                wait(scan_interval_seconds)

    def health(self) -> WorkerHealth:
        return WorkerHealth(
            enabled_count=self._enabled_count(),
            pending_keys=len(self._queue), last_success=self._last_success,
            blocked=tuple(sorted(self._blocked.items())),
        )

    def _enabled_count(self) -> int:
        if not self._enabled:
            return 0
        count, after = 0, None
        while True:
            page = self._repository.enabled_forward_stream_ids(limit=512, after=after)
            count += len(page)
            if len(page) < 512:
                return count
            after = page[-1]
