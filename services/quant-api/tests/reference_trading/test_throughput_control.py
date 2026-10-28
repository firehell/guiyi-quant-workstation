from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.reference_trading.runtime import ForwardReferenceWorker, WorkerBudget


def test_durable_scan_uses_batch_metadata_without_loading_idle_checkpoints():
    calls = []
    class Repo:
        def enabled_forward_scan_work_keys(self, **kwargs):
            calls.append(kwargs)
            return ("newow:rb:1d",)

        def enabled_forward_work_keys(self, **kwargs):
            raise AssertionError("idle Live routes must be excluded in SQL")

        def forward_source_context(self, *_):
            raise AssertionError("scan must not deserialize a checkpoint")

    worker = ForwardReferenceWorker(Repo(), lambda _: None, lambda *_: None, enabled=True)
    worker.scan_live = False
    worker.scan()
    assert tuple(worker._queue) == ("newow:rb:1d",)
    assert calls == [{"limit": 512, "after": None}]


def test_scan_obeys_drain_and_cursor_does_not_skip_unvisited_keys():
    stopped, seen = [False], []
    repo = SimpleNamespace(enabled_forward_stream_ids=lambda **_: ("a", "b", "c"))
    worker = ForwardReferenceWorker(repo, lambda _: None, lambda *_: None, enabled=True)
    worker.stop_requested = lambda: stopped[0]
    original = worker.wake
    def wake(key, **kwargs):
        seen.append(key)
        result = original(key, **kwargs)
        stopped[0] = True
        return result
    worker.wake = wake
    worker.scan()
    assert seen == ["a"]
    assert worker._scan_after == "a"


def test_round_stops_before_next_route_and_preserves_group_continuation():
    stopped, seen = [False], []
    repo = SimpleNamespace(enabled_forward_work_routes=lambda _: ("a", "b"),
                           read_pending_capture=lambda _: None)
    def read(route, *_):
        seen.append(route)
        stopped[0] = True
    worker = ForwardReferenceWorker(repo, lambda _: None, read, enabled=True,
        budget=WorkerBudget(max_units_per_round=32))
    worker.stop_requested = lambda: stopped[0]
    worker.wake("newow:rb:1d")
    worker.run_round()
    assert seen == ["a"]
    assert worker._remaining["newow:rb:1d"] == ("b",)


def test_cancelled_input_is_not_blocked_and_route_is_resumable():
    from app.reference_trading.work_control import ForwardWorkCancelled
    def read(*_):
        raise ForwardWorkCancelled()
    repo = SimpleNamespace(read_pending_capture=lambda _: None)
    worker = ForwardReferenceWorker(repo, lambda _: None, read, enabled=True)
    worker.wake("a")
    with pytest.raises(ForwardWorkCancelled):
        worker.run_round()
    assert worker._blocked == {}
    assert tuple(worker._queue) == ("a",)


def test_cancel_after_capture_keeps_capture_without_starting_evaluator():
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.work_control import ForwardWorkCancelled
    stopped, calls = [False], []
    end = datetime(2026, 10, 28, 7, tzinfo=UTC)
    def save(capture):
        calls.append("capture")
        stopped[0] = True
    worker = ForwardReferenceWorker(SimpleNamespace(read_pending_capture=lambda _: None,
        capture_forward=save), lambda _: calls.append("service"),
        lambda *_: ForwardCapture("s", "r", 1, "key", end, end,
                                  "completed_live", {}, {}, "first_seen"), enabled=True)
    worker.stop_requested = lambda: stopped[0]
    with pytest.raises(ForwardWorkCancelled):
        worker.process_inbox_delivery("s", end, delivery_id="d")
    assert calls == ["capture"]
    assert worker._blocked == {}
    assert worker.inbox_delivery_id is None


def test_foreground_cancellation_does_not_mark_inbox_or_request_history():
    from app.reference_trading.live_wake import InboxForwardLiveWake
    from app.reference_trading.work_control import ForwardWorkCancelled
    end = datetime(2026, 10, 28, 7, tzinfo=UTC)
    calls = []
    event = SimpleNamespace(confirmed_at=end, raw_received_at=end,
                            data={"bar_end": end.isoformat()})
    def cancelled(*_, **__):
        raise ForwardWorkCancelled()
    wake = object.__new__(InboxForwardLiveWake)
    wake._inbox = SimpleNamespace(next_heads=lambda **_: (SimpleNamespace(stream_id="s",
        delivery_id="d", status="PENDING", envelope=event),), validate_delivery=lambda _: None,
        mark_blocked=lambda *_: calls.append("blocked"), mark_unknown=lambda *_: calls.append("unknown"))
    wake._worker = SimpleNamespace(assert_owned=lambda: None, process_inbox_delivery=cancelled)
    wake._after_stream_id = None
    wake._retry_after_by_stream = {}
    wake.stop_requested = lambda: False
    wake._calculate_heads()
    assert calls == []
    assert wake._worker.retained_source_observations == ()


def test_retained_originals_are_deferred_until_the_capture_needs_them():
    from app.reference_trading.live_wake import InboxForwardLiveWake
    end = datetime(2026, 10, 28, 7, tzinfo=UTC)
    calls = []
    event = SimpleNamespace(confirmed_at=end, raw_received_at=end,
                            data={"bar_end": end.isoformat()})
    wake = object.__new__(InboxForwardLiveWake)
    wake._inbox = SimpleNamespace(next_heads=lambda **_: (SimpleNamespace(stream_id="s",
        delivery_id="d", status="PENDING", envelope=event),), validate_delivery=lambda _: None,
        retained_observations=lambda _: calls.append("prefix") or ())
    wake._worker = SimpleNamespace(assert_owned=lambda: None, process_inbox_delivery=lambda *_, **__: None)
    wake._after_stream_id = None
    wake._retry_after_by_stream = {}
    wake.stop_requested = lambda: False
    wake._calculate_heads()
    assert calls == []


def test_historical_refresh_permission_is_withheld_for_real_foreground_backlog():
    from app.reference_trading.refresh_priority import RefreshPriority
    from app.reference_trading.worker_entry import defer_historical_refresh
    pending, starts = [True], []
    gate = RefreshPriority()
    worker = SimpleNamespace(has_foreground_work=lambda: pending[0])
    refresh = SimpleNamespace(start=lambda: starts.append(1))
    defer_historical_refresh(worker, refresh, should_stop=lambda: False, priority=gate)
    worker.after_healthy_round()
    assert not gate.can_run() and starts == []
    pending[0] = False
    worker.after_healthy_round()
    assert gate.can_run() and starts == [1]


def test_stage_timings_are_bounded_and_never_contain_exception_text():
    from app.reference_trading.work_control import StageTimings
    clock = iter((1.0, 1.25, 2.0, 2.5))
    timings = StageTimings(clock=lambda: next(clock))
    with timings.measure("input"):
        pass
    with pytest.raises(ValueError):
        with timings.measure("input"):
            raise ValueError("secret SQL credentials")
    assert timings.snapshot() == {"input": {"count": 2, "seconds": .75, "last_seconds": .5,
                                           "max_seconds": .5}}
    assert "secret" not in str(timings.snapshot())
    with pytest.raises(ValueError):
        with timings.measure("unbounded stream id"):
            pass


def test_drain_after_pure_evaluation_never_starts_commit():
    from app.reference_trading.forward_service import ForwardReferenceService
    from app.reference_trading.work_control import ForwardWorkCancelled
    from decimal import Decimal
    from app.reference_trading.contracts import PreparedBatch
    from app.reference_trading.presentation import envelope
    from guiyi_quant.reference_trading import CompletedReferenceBar, reduce_reference
    from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
    # Use the existing real capture/repository fixture; only the cancellation
    # instant is injected, not the outcome of a transaction.
    from test_forward_capture import _active, _capture
    from app.reference_trading.repository import ReferenceRepository
    factory, identity, revision, _ = _active()
    repo = ReferenceRepository(factory)
    capture = _capture(identity, revision)
    repo.capture_forward(capture)
    stopped = [False]
    def evaluate(token, cp, evidence):
        transition = reduce_reference(cp.reference_state, completed_bar=CompletedReferenceBar(
            "RB2610", "owner", "calc", capture.bar_end, capture.bar_end.date(), Decimal("3500")))
        checkpoint = AdapterCheckpoint(cp.strategy_state, capture.bar_end, capture.capture_hash,
            "RB2610", "owner", "calc", identity, transition.state)
        prepared = PreparedBatch(identity.stream_id, revision, "forward:cancel", token,
            {"source": "fixture"}, (), (transition,), checkpoint, "newow_product_replay_v1",
            {"forward_capture_v1": {"capture_id": evidence["capture_id"],
                "hash": capture.capture_hash, "generation": 1}, "presentation_v1": envelope([])},
            capture.observed_at)
        stopped[0] = True
        return prepared
    def check():
        if stopped[0]:
            raise ForwardWorkCancelled()
    service = ForwardReferenceService(repo, evaluate, check_cancelled=check)
    before = repo.load_checkpoint(identity.stream_id)[0]
    with pytest.raises(ForwardWorkCancelled):
        service.process_pending(identity.stream_id)
    assert repo.load_checkpoint(identity.stream_id)[0] == before
    assert repo.read_pending_capture(identity.stream_id) is not None


def test_recovery_receipt_proofs_are_reused_only_inside_one_validation(monkeypatch):
    from test_inbox_recovery import fixture
    from app.reference_trading import inbox_recovery as module
    factory, _, recovery, plan, evaluator = fixture()
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluator)
    original, calls = module.stable_receipt_hash, []
    def hashed(receipt):
        calls.append(receipt.receipt_id)
        return original(receipt)
    monkeypatch.setattr(module, "stable_receipt_hash", hashed)
    with factory() as session:
        assert module.verified_resolution_ids(session) == (plan.delivery_id,)
    assert len(calls) == 1
    with factory() as session:
        assert module.verified_resolution_ids(session) == (plan.delivery_id,)
    assert len(calls) == 2  # A fresh transaction must revalidate, never trust a TTL.


def test_recovery_validates_each_shared_original_only_once_per_readback(monkeypatch):
    from test_inbox_recovery import fixture
    from app.reference_trading import inbox as inbox_module
    from app.reference_trading.inbox_recovery import verified_resolution_ids
    factory, _, recovery, plan, evaluator = fixture()
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluator)
    original, calls = inbox_module._verified_input, []
    def verified(item):
        calls.append(item.input_id)
        return original(item)
    monkeypatch.setattr(inbox_module, "_verified_input", verified)
    with factory() as session:
        assert verified_resolution_ids(session) == (plan.delivery_id,)
    assert calls == [plan.input_id]


def test_warmup_checks_cancellation_between_kernel_steps():
    from app.reference_trading.subing_forward import subing_warmup_checkpoint
    from app.reference_trading.work_control import ForwardWorkCancelled
    from test_forward_inputs import _Read
    from guiyi_quant.reference_trading import StreamIdentity, RecordingMode
    identity = StreamIdentity("subing_reference", ("v1",), "v1", "v1", "v1", "rb", "15m",
                              "actual_dominant", RecordingMode.FORWARD_OBSERVATION, "v1")
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 2:
            raise ForwardWorkCancelled()
    with pytest.raises(ForwardWorkCancelled):
        subing_warmup_checkpoint(identity, "RB2610", "owner", "calc", _Read().bars,
                                 check_cancelled=check)
    assert len(calls) == 2


def test_physical_partition_read_checks_cancel_before_and_after_io():
    from app.market_data.market_data_service import MarketDataService
    from app.reference_trading.work_control import ForwardWorkCancelled
    stopped, reads = [False], []
    def check():
        if stopped[0]:
            raise ForwardWorkCancelled()
    def read(_):
        reads.append(1)
        stopped[0] = True
        return ()
    market = MarketDataService(None, SimpleNamespace(read_catalog_partition=read), check_cancelled=check)
    with pytest.raises(ForwardWorkCancelled):
        market._partition_bars(SimpleNamespace(source_quality=()))
    assert reads == [1]
    with pytest.raises(ForwardWorkCancelled):
        market._partition_bars(SimpleNamespace(source_quality=()))
    assert reads == [1]


def test_serve_treats_cooperative_drain_as_clean_return():
    from app.reference_trading.work_control import ForwardWorkCancelled
    stopped = [False]
    worker = ForwardReferenceWorker(SimpleNamespace(enabled_forward_stream_ids=lambda **_: ()),
                                    lambda _: None, lambda *_: None, enabled=True)
    def poll():
        stopped[0] = True
        raise ForwardWorkCancelled()
    worker.poll_observations = poll
    worker.serve(should_stop=lambda: stopped[0])


def test_scan_metadata_query_includes_pending_live_group_and_canonical_but_not_idle_live():
    from test_inbox_recovery import fixture
    from app.reference_trading.repository import ReferenceRepository
    factory, _, recovery, plan, evaluator = fixture(frequency="60m")
    repository = ReferenceRepository(factory)
    canonical = repository.enabled_forward_scan_work_keys()
    assert len(canonical) == 1 and canonical[0].endswith(":1d")
    repository.capture_forward(plan.capture)
    keys = repository.enabled_forward_scan_work_keys()
    assert keys == tuple(sorted((*canonical, "newow:rb:60m")))
    assert repository.enabled_forward_scan_work_keys(limit=1) == keys[:1]
    assert repository.enabled_forward_scan_work_keys(after=keys[0]) == keys[1:]
    assert repository.has_pending_forward_capture()
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluator)
    assert repository.enabled_forward_scan_work_keys() == canonical
    assert not repository.has_pending_forward_capture()


def test_shared_bridge_readback_still_checks_each_original_time_and_sequence():
    from test_inbox_recovery import _exercise_one_gap_bridge
    from app.reference_trading.inbox_recovery import _verify_stored_bridge
    from app.reference_trading.models import (ReferenceInboxRecoveryResult as R,
        ReferenceInboxDelivery as D, ReferenceInboxInput as I, ReferenceActivationReceipt as A,
        ReferenceBatch as B)
    from sqlalchemy import select
    factory, _, _, plan = _exercise_one_gap_bridge()
    with factory() as db:
        row = db.get(R, plan.delivery_id)
        delivery = db.get(D, row.delivery_id)
        item = db.get(I, row.input_id)
        old, target = db.get(A, delivery.activation_receipt_id), db.get(A, row.target_receipt_id)
        gaps = db.scalars(select(B).where(B.kind == "capture",
            B.payload_hash == target.budget["bounded_recovery_capture_sha256"])).all()
        calculations = {cap.consumed_by_batch_id: db.get(B, cap.consumed_by_batch_id) for cap in gaps}
        cache = {}
        _verify_stored_bridge(delivery, item, old, target, row, gaps, calculations, cache=cache)
        assert len(cache) == 1
        wrong_row = SimpleNamespace(**{c.name: getattr(row, c.name) for c in R.__table__.columns})
        wrong_row.calculation_seq = calculations[gaps[0].consumed_by_batch_id].seq
        with pytest.raises(ValueError):
            _verify_stored_bridge(delivery, item, old, target, wrong_row, gaps, calculations, cache=cache)
        wrong_item = SimpleNamespace(bar_end=datetime.fromisoformat(
            gaps[0].source_evidence["forward_capture_v1"]["bar_end"]))
        with pytest.raises(ValueError):
            _verify_stored_bridge(delivery, wrong_item, old, target, row, gaps, calculations, cache=cache)


def test_resources_cannot_report_closed_while_background_thread_remains_alive():
    from app.reference_trading.worker_entry import close_worker_resources
    calls = []
    with pytest.raises(RuntimeError, match="REFERENCE_BACKGROUND_DRAIN_INCOMPLETE"):
        close_worker_resources(SimpleNamespace(is_alive=lambda: True, stop=lambda: None),
            SimpleNamespace(stop=lambda **_: None, is_alive=lambda: False),
            SimpleNamespace(close=lambda: calls.append("wake_closed")), warmup=False)
    assert calls == ["wake_closed"]


def test_durable_intake_requests_refresh_yield_before_persisting_original():
    from app.reference_trading.live_wake import InboxForwardLiveWake
    from app.reference_trading.refresh_priority import RefreshPriority
    from test_inbox_wake import Journal
    priority, timeline = RefreshPriority(), []
    priority.grant()
    assert priority.begin()
    def ingest(*_, **__):
        assert priority.yield_requested()
        timeline.append("ingested")
    wake = object.__new__(InboxForwardLiveWake)
    wake._stream = Journal([SimpleNamespace(stream_id="1-0")], timeline)
    wake._inbox = SimpleNamespace(ingest=ingest)
    wake._worker = SimpleNamespace(assert_owned=lambda: None, observation_priority=priority.observation)
    wake.stop_requested = lambda: False
    wake._calculate_heads = lambda: None
    wake.poll()
    assert getattr(wake, "intake_error", None) is None
    assert timeline == ["ingested", "ack"]
    assert priority.yield_requested()  # Only the real background finish clears it.
