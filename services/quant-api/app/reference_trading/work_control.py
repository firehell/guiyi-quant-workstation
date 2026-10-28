"""Cooperative pure-work cancellation and bounded, non-persistent timing counters."""
from contextlib import contextmanager
from threading import Lock
from time import monotonic


class ForwardWorkCancelled(RuntimeError):
    def __init__(self):
        super().__init__("REFERENCE_WORK_CANCELLED")


class StageTimings:
    STAGES = frozenset({"ingest", "recovery", "heads", "originals", "input", "evaluate",
                        "capture", "commit", "scan", "background_wait", "foreground"})

    def __init__(self, *, clock=monotonic):
        self._clock = clock
        self._values = {}
        self._lock = Lock()

    @contextmanager
    def measure(self, stage):
        if stage not in self.STAGES:
            raise ValueError("REFERENCE_TIMING_STAGE_INVALID")
        started = self._clock()
        try:
            yield
        finally:
            elapsed = max(0.0, self._clock() - started)
            with self._lock:
                row = self._values.setdefault(stage, {"count": 0, "seconds": 0.0,
                    "last_seconds": 0.0, "max_seconds": 0.0})
                row.update(count=row["count"] + 1, seconds=row["seconds"] + elapsed,
                    last_seconds=elapsed, max_seconds=max(row["max_seconds"], elapsed))

    def snapshot(self):
        with self._lock:
            return {stage: {key: round(value, 6) if isinstance(value, float) else value
                           for key, value in row.items()} for stage, row in sorted(self._values.items())}
