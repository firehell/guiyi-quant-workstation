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
    ) -> None:
        self._repository = repository
        self._service_for = service_for
        self._read_input = read_input
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
        if stream_id in self._queued:
            if kind == "live_event":
                self._queued[stream_id] = (kind, bar_end)
            return False
        if len(self._queue) >= self._budget.max_pending_keys:
            self._blocked[stream_id] = "WORKER_QUEUE_FULL"
            return False
        self._queue.append(stream_id)
        self._queued[stream_id] = (kind, bar_end)
        return True

    def scan(self) -> None:
        if not self._enabled:
            return
        available = self._budget.max_pending_keys - len(self._queue)
        if available <= 0:
            return
        stream_ids = self._repository.enabled_forward_stream_ids(
            limit=available, after=self._scan_after,
        )
        if not stream_ids and self._scan_after is not None:
            self._scan_after = None
            stream_ids = self._repository.enabled_forward_stream_ids(limit=available)
        for stream_id in stream_ids:
            self.wake(stream_id, kind="scan")
        if stream_ids:
            self._scan_after = stream_ids[-1]

    def run_round(self) -> int:
        if not self._enabled:
            return 0
        completed = 0
        for _ in range(min(len(self._queue), self._budget.max_units_per_round)):
            stream_id = self._queue.popleft()
            kind, event_bar_end = self._queued.pop(stream_id)
            started = monotonic()
            try:
                service = self._service_for(stream_id)
                pending = self._repository.read_pending_capture(stream_id)
                if pending is not None:
                    result = service.process_pending(stream_id)
                    self.wake(stream_id, kind="scan")
                else:
                    # A scan can discover gaps, but cannot manufacture first_seen.
                    capture = self._read_input(stream_id, kind, event_bar_end)
                    result = None
                    if capture is not None:
                        self._repository.capture_forward(capture)
                        result = service.process_pending(stream_id)
                if result is not None:
                    completed += 1
                    self._last_success = datetime.now(UTC)
                self._blocked.pop(stream_id, None)
            except Exception as error:  # noqa: BLE001 - one stream must not stop the worker
                self._blocked[stream_id] = (
                    str(error) if isinstance(error, ForwardInputUnavailable)
                    else type(error).__name__
                )
            if monotonic() - started >= self._budget.max_stream_seconds:
                self.wake(stream_id, kind="scan")
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
            enabled_count=len(self._repository.enabled_forward_stream_ids()) if self._enabled else 0,
            pending_keys=len(self._queue), last_success=self._last_success,
            blocked=tuple(sorted(self._blocked.items())),
        )
