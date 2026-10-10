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


def test_cycle_diagnostic_reports_safe_counts_and_clears_ready_on_block():
    worker = ForwardReferenceWorker(_Repository(), lambda _: _Service(), lambda *_args: None, enabled=True)
    proofs = []
    worker.report_health = lambda proof: proofs.append(proof)
    worker._blocked['private-stream-id'] = 'credential=value SQL select'
    calls = [0]
    def stop():
        calls[0] += 1
        return calls[0] > 2
    worker.serve(should_stop=stop, wait=lambda _: None)
    assert proofs[-1]['ready'] is False
    assert proofs[-1]['blocked_counts'] == {'UNCLASSIFIED_FAILURE': 1}
    assert 'private-stream-id' not in str(proofs) and 'credential' not in str(proofs)


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


class GroupedRepository(_Repository):
    def __init__(self, count=180):
        self.groups = {
            f"newow:p{index:03}:60m": tuple(f"{index:03}-{strategy}" for strategy in
                                           ("trend", "oscillation", "main_rise", "dual_fusion"))
            for index in range(count)
        }

    def enabled_forward_work_keys(self, *, limit=512, after=None):
        return tuple(key for key in self.groups if after is None or key > after)[:limit]

    def enabled_forward_work_routes(self, key):
        return self.groups[key]

    def forward_work_key(self, stream_id):
        return next(key for key, routes in self.groups.items() if stream_id in routes)


def test_grouped_newow_scan_has_180_keys_and_covers_all_720_streams_fairly():
    repository = GroupedRepository()
    seen, units = [], []
    worker = ForwardReferenceWorker(
        repository, lambda _: _Service(), lambda sid, *_: seen.append(sid),
        enabled=True, begin_unit=lambda: units.append("begin"),
        end_unit=lambda: units.append("end"),
    )
    worker.scan()
    assert worker.health().pending_keys == 180
    for _ in range(23):
        worker.scan()
        before = len(seen)
        worker.run_round()
        assert len(seen) - before <= 32
    assert set(seen) == {sid for routes in repository.groups.values() for sid in routes}
    assert seen[:4] == list(repository.groups["newow:p000:60m"])
    assert units == [part for _ in range(len(units) // 2) for part in ("begin", "end")]


def test_group_continuation_respects_tiny_stream_budget_and_fusion_order():
    repository = GroupedRepository(count=1)
    seen = []
    worker = ForwardReferenceWorker(
        repository, lambda _: _Service(), lambda sid, kind, end: seen.append((sid, kind, end)),
        enabled=True, budget=WorkerBudget(max_pending_keys=1, max_units_per_round=2),
    )
    end = datetime(2026, 9, 23, 1, tzinfo=UTC)
    worker.wake("000-trend", kind="live_event", bar_end=end)
    worker.wake("000-dual_fusion", kind="live_event", bar_end=end)
    assert worker.health().pending_keys == 1
    worker.run_round()
    assert len(seen) == 2
    worker.run_round()
    assert [item[0] for item in seen] == list(repository.groups["newow:p000:60m"])
    assert all(item[1:] == ("live_event", end) for item in seen)


def test_repository_groups_only_target_newow_strategies_and_orders_dependencies():
    from sqlalchemy import create_engine, update
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.reference_trading.models import ReferenceStream
    from app.reference_trading.repository import ReferenceRepository
    from guiyi_quant.reference_trading import StreamIdentity

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    streams = {}
    for strategy in ("newow_dual_fusion", "newow_main_rise", "newow_oscillation", "newow_trend", "htdy"):
        identity = StreamIdentity(
            strategy_code=strategy, formula_versions=("v1",), profile_id="default",
            reference_model_version="reference-v2", futures_adaptation_version="futures-v1",
            product="RB", frequency="60m", series_kind="actual_dominant",
            recording_mode="forward_observation", observation_policy_version="v1",
        )
        repository.ensure_stream(identity)
        streams[strategy] = identity.stream_id
    with factory.begin() as session:
        session.execute(update(ReferenceStream).values(enabled=True))
    keys = repository.enabled_forward_work_keys(limit=1)
    assert keys == ("newow:rb:60m",)
    assert repository.enabled_forward_work_routes(keys[0]) == tuple(
        streams[f"newow_{name}"] for name in ("trend", "oscillation", "main_rise", "dual_fusion")
    )
    assert repository.forward_work_key(streams["newow_trend"]) == keys[0]
    assert repository.enabled_forward_work_keys(after=keys[0]) == (f"stream:{streams['htdy']}",)


def test_group_hooks_release_source_cache_even_when_a_stream_fails():
    units, seen = [], []
    repository = GroupedRepository(count=1)

    def read(sid, *_):
        seen.append(sid)
        if sid.endswith("trend"):
            raise ValueError("source unavailable")

    worker = ForwardReferenceWorker(
        repository, lambda _: _Service(), read, enabled=True,
        begin_unit=lambda: units.append("begin"), end_unit=lambda: units.append("end"),
    )
    worker.scan()
    worker.run_round()
    assert seen == list(repository.groups["newow:p000:60m"])
    assert units == ["begin", "end"]
    assert worker.health().blocked == (("000-trend", "ValueError"),)


def test_stale_live_wake_does_not_replace_a_newer_queued_event():
    repository = GroupedRepository(count=1)
    seen = []
    worker = ForwardReferenceWorker(repository, lambda _: _Service(),
                                    lambda sid, kind, end: seen.append(end), enabled=True)
    old = datetime(2026, 9, 23, 1, tzinfo=UTC)
    new = datetime(2026, 9, 23, 2, tzinfo=UTC)
    worker.wake("000-trend", kind="live_event", bar_end=new)
    worker.wake("000-dual_fusion", kind="live_event", bar_end=old)
    worker.run_round()
    assert seen == [new] * 4


def test_scan_past_small_group_queue_visits_every_group_without_first_page_starvation():
    repository = GroupedRepository(count=180)
    seen = []
    worker = ForwardReferenceWorker(
        repository, lambda _: _Service(), lambda sid, *_: seen.append(sid), enabled=True,
        budget=WorkerBudget(max_pending_keys=3, max_units_per_round=2),
    )
    for _ in range(370):
        worker.scan()
        worker.run_round()
    assert set(seen) == {sid for routes in repository.groups.values() for sid in routes}


def test_invalid_group_routes_do_not_stop_other_work_keys():
    class Repository(GroupedRepository):
        def enabled_forward_work_routes(self, key):
            if key == "newow:p000:60m":
                raise ValueError("scope conflict")
            return super().enabled_forward_work_routes(key)

    repository = Repository(count=2)
    seen = []
    worker = ForwardReferenceWorker(repository, lambda _: _Service(),
                                    lambda sid, *_: seen.append(sid), enabled=True)
    worker.scan()
    worker.run_round()
    assert seen == list(repository.groups["newow:p001:60m"])
    assert worker.health().blocked == (("newow:p000:60m", "ValueError"),)

def test_1260_routes_share_360_keys_and_keep_fusion_after_base_without_starvation():
    from app.reference_trading.recording_scope import FREQUENCIES, strategies_for
    repository = GroupedRepository(count=0)
    repository.groups = {
        f"newow:p{product:03}:{frequency}": tuple(f"{product:03}-{frequency}-{strategy}" for strategy in strategies_for(frequency))
        for product in range(60) for frequency in sorted(FREQUENCIES)
    }
    seen = []
    worker = ForwardReferenceWorker(repository, lambda _: _Service(), lambda sid, *_: seen.append(sid), enabled=True)
    worker.scan()
    assert worker.health().pending_keys == 360
    for _ in range(40):
        worker.run_round()
    assert len(seen) == len(set(seen)) == 1260
    assert worker.health().pending_keys == 0
    for routes in repository.groups.values():
        positions = [seen.index(sid) for sid in routes]
        assert positions == sorted(positions)
