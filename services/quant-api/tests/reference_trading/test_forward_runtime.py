from __future__ import annotations

from datetime import UTC, datetime

from app.reference_trading.runtime import ForwardReferenceWorker, WorkerBudget


class _Repository:
    def enabled_forward_stream_ids(self, *, limit=512, after=None):
        return tuple(item for item in ("a", "b", "c") if after is None or item > after)[:limit]

    def read_pending_capture(self, stream_id):
        return None


class _Service:
    def process_pending(self, stream_id):
        raise AssertionError("no pending capture")


def test_worker_defaults_off_and_rotates_bounded_wakes():
    seen = []
    repository = _Repository()
    off = ForwardReferenceWorker(repository, lambda _: _Service(), lambda *args: seen.append(args))
    assert not off.wake("a")
    off.scan()
    assert off.run_round() == 0 and seen == []

    worker = ForwardReferenceWorker(
        repository, lambda _: _Service(), lambda *args: seen.append(args),
        enabled=True, budget=WorkerBudget(max_pending_keys=3, max_units_per_round=2),
    )
    event_end = datetime(2026, 9, 23, 1, tzinfo=UTC)
    worker.scan()
    worker.wake("a", kind="live_event", bar_end=event_end)
    assert worker.run_round() == 0
    assert seen == [("a", "live_event", event_end), ("b", "scan", None)]
    assert worker.health().pending_keys == 1
    worker.run_round()
    assert seen[-1] == ("c", "scan", None)


def test_scan_rotates_past_first_page_of_enabled_streams():
    class Many(_Repository):
        def enabled_forward_stream_ids(self, *, limit=512, after=None):
            return tuple(
                item for item in (f"stream-{index:03}" for index in range(540))
                if after is None or item > after
            )[:limit]

    seen = []
    worker = ForwardReferenceWorker(
        Many(), lambda _: _Service(), lambda stream_id, _kind, _end: seen.append(stream_id),
        enabled=True,
    )
    for _ in range(20):
        worker.scan()
        worker.run_round()
    assert "stream-539" in seen


def test_serve_scans_immediately_and_stops_without_extra_wait():
    seen = []
    worker = ForwardReferenceWorker(
        _Repository(), lambda _: _Service(),
        lambda stream_id, _kind, _end: seen.append(stream_id), enabled=True,
    )
    worker.serve(should_stop=lambda: len(seen) == 3,
                 wait=lambda _seconds: (_ for _ in ()).throw(AssertionError("unexpected wait")))
    assert seen == ["a", "b", "c"]


def test_pending_recovery_never_reuses_old_live_event_for_next_bar():
    event_end = datetime(2026, 9, 23, 1, tzinfo=UTC)
    seen = []

    class Repository(_Repository):
        pending = True

        def enabled_forward_stream_ids(self, *, limit=512, after=None):
            return ("a",) if after is None else ()

        def read_pending_capture(self, _stream_id):
            return ("captured-a", {}) if self.pending else None

    repository = Repository()

    class Service:
        def process_pending(self, _stream_id):
            repository.pending = False
            return object()

    worker = ForwardReferenceWorker(
        repository, lambda _: Service(),
        lambda stream_id, kind, bar_end: seen.append((stream_id, kind, bar_end)),
        enabled=True,
    )
    worker.wake("a", kind="live_event", bar_end=event_end)
    assert worker.run_round() == 1
    worker.run_round()
    assert seen == [("a", "scan", None)]
