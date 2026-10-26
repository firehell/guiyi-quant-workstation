import pytest

from app.reference_trading import worker_entry


@pytest.mark.parametrize('release_after', [0.2, None])
def test_warmup_lease_wait_is_bounded_by_shared_deadline(monkeypatch, release_after):
    from types import SimpleNamespace
    clock, attempts = [0.0], []
    lease = object()
    monkeypatch.setattr(worker_entry, 'monotonic', lambda: clock[0], raising=False)
    def sleep(seconds):
        clock[0] += seconds
    monkeypatch.setattr(worker_entry, 'sleep', sleep, raising=False)
    def acquire():
        attempts.append(clock[0])
        return lease if release_after is not None and clock[0] >= release_after else None
    catalog = SimpleNamespace(acquire_maintenance_lock=acquire)
    if release_after is None:
        with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_TIMEOUT'):
            worker_entry._acquire_canonical_lease(catalog, deadline=120.0)
        assert clock[0] == pytest.approx(120.0)
        assert max(attempts) < 120.0
    else:
        assert worker_entry._acquire_canonical_lease(catalog, deadline=120.0) is lease
        assert clock[0] == pytest.approx(release_after)


def test_formal_canonical_lease_does_not_wait(monkeypatch):
    from types import SimpleNamespace
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    monkeypatch.setattr(worker_entry, 'sleep', lambda _: pytest.fail('formal mode waited'), raising=False)
    calls = []
    catalog = SimpleNamespace(acquire_maintenance_lock=lambda: calls.append(1))
    with pytest.raises(ForwardInputUnavailable, match='SOURCE_BUSY'):
        worker_entry._acquire_canonical_lease(catalog, deadline=None)
    assert calls == [1]


def test_warmup_lease_acquired_after_deadline_is_released(monkeypatch):
    from types import SimpleNamespace
    clock, released = [0.0], []
    monkeypatch.setattr(worker_entry, 'monotonic', lambda: clock[0])
    lease = SimpleNamespace(release=lambda: released.append(True))
    def acquire():
        clock[0] = 120.0
        return lease
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_TIMEOUT'):
        worker_entry._acquire_canonical_lease(SimpleNamespace(acquire_maintenance_lock=acquire), deadline=120.0)
    assert released == [True]


def test_entire_warmup_shares_one_deadline(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    clock, checked = [10.0], []
    monkeypatch.setattr(worker_entry, 'monotonic', lambda: clock[0])
    repository = SimpleNamespace(
        enabled_forward_stream_ids=lambda **_: ('first', 'second'),
        read_pending_capture=lambda _: None,
        forward_source_context=lambda _: (SimpleNamespace(frequency='1d'),),
        load_checkpoint=lambda _: (None, None))
    worker = SimpleNamespace(_repository=repository, scan_live=False,
        _enabled_keys=repository.enabled_forward_stream_ids, _work_routes=lambda key: (key,),
        _begin_unit=lambda: None, _end_unit=lambda: None,
        _service_for=lambda name: checked.append(name), _read_input=lambda *_: None)
    @contextmanager
    def opened(**kwargs):
        assert kwargs == {'warmup': True, 'warmup_deadline': 130.0}
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    def compute(*_):
        clock[0] = 130.0
    monkeypatch.setattr(worker_entry, '_warmup_saved_capture', compute)
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_TIMEOUT'):
        worker_entry.warmup_reference_worker()
    assert checked == ['first']


def test_worker_stays_off_without_exact_marker(tmp_path, monkeypatch):
    marker = tmp_path / "reference-worker-enabled"
    monkeypatch.setattr(worker_entry, "ACTIVATION_MARKER", marker)
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        with worker_entry.open_forward_worker():
            raise AssertionError("disabled worker must not open resources")
    marker.write_text("enabled", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        worker_entry.require_worker_enabled()


def test_unknown_historical_attempt_survives_release_root_change(tmp_path, monkeypatch):
    from pathlib import Path
    from app.reference_trading import worker_entry
    from app.reference_trading.historical_refresh import RefreshStateStore, VERSION
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(worker_entry, "PROJECT_ROOT", tmp_path / "release-one")
    old_path = worker_entry.historical_refresh_state_path()
    unknown = {"version": VERSION, "cursor": "", "routes": {"stream": {"status": "inflight"}}}
    RefreshStateStore(old_path).write(unknown)
    monkeypatch.setattr(worker_entry, "PROJECT_ROOT", tmp_path / "release-two")
    assert worker_entry.historical_refresh_state_path() == old_path
    assert RefreshStateStore(worker_entry.historical_refresh_state_path()).read() == unknown


def test_main_signal_stops_batch_after_current_observation(monkeypatch):
    from contextlib import contextmanager
    from copy import deepcopy
    import signal
    from types import SimpleNamespace
    from app import runtime_bindings, runtime_handover
    from tests.reference_trading.test_live_wake import _durable_wake_with_backlog
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    first = wake._stream.read()[0]
    second = deepcopy(first)
    second.stream_id = '2-0'
    wake._stream.read = lambda *_, **__: (first, second)
    handlers, reads = {}, []
    monkeypatch.setattr(worker_entry.signal, 'signal', lambda name, handler: handlers.setdefault(name, handler))
    def read(*_):
        reads.append('read')
        handlers[signal.SIGTERM](signal.SIGTERM, None)
    worker._read_input = read
    def serve(*, should_stop, wait):
        assert not should_stop()
        wake.poll()
        assert should_stop()
    worker.serve = serve
    @contextmanager
    def opened(**_):
        yield worker, wake, SimpleNamespace()
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(runtime_bindings, 'read_bindings', lambda: object())
    monkeypatch.setattr(runtime_handover, 'run_supervised', lambda _name, run, **_: run(
        SimpleNamespace(should_drain=lambda: False)))
    monkeypatch.setenv('GUIYI_RUNTIME_LEGACY_MODE', '0')
    assert worker_entry.main() == 0
    assert reads == ['read'] and len(acknowledgements) == 1


def test_main_signal_during_round_does_not_grant_or_start_history(monkeypatch):
    from contextlib import contextmanager
    import signal
    from types import SimpleNamespace
    from app import runtime_bindings, runtime_handover
    handlers, starts = {}, []
    monkeypatch.setattr(worker_entry.signal, 'signal', lambda name, handler: handlers.setdefault(name, handler))
    worker = SimpleNamespace()
    worker_entry.defer_historical_refresh(worker, SimpleNamespace(start=lambda: starts.append(True)),
        should_stop=lambda: False)
    def serve(*, should_stop, wait):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        worker.after_healthy_round()
        assert should_stop()
    worker.serve = serve
    @contextmanager
    def opened(**_):
        yield worker, SimpleNamespace(), SimpleNamespace()
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(runtime_bindings, 'read_bindings', lambda: object())
    monkeypatch.setattr(runtime_handover, 'run_supervised', lambda _name, run, **_: run(
        SimpleNamespace(should_drain=lambda: False)))
    monkeypatch.setenv('GUIYI_RUNTIME_LEGACY_MODE', '0')
    assert worker_entry.main() == 0
    assert starts == []


def _initialized_route(engine=None, frequency="1w"):
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.subing_activation import apply_subing_activation, plan_subing_activation
    from tests.reference_trading.test_subing_activation import NOW
    engine = engine or create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    plan = plan_subing_activation("m", frequency, operational={"m"},
        start=NOW + timedelta(minutes=2), expiry=NOW + timedelta(minutes=1),
        now=NOW, host="isolated", environment="isolated")
    result = apply_subing_activation(factory, plan, expected_plan_hash=plan["plan_hash"],
        operational={"m"}, now=NOW)
    return factory, ReferenceRepository(factory), result


def _never_evaluate_initialization():
    from types import SimpleNamespace
    return SimpleNamespace(_evaluator=lambda *_: pytest.fail("initialization is not a calculation"))


@pytest.mark.parametrize("frequency", ("5m", "15m", "30m", "60m", "1d", "1w"))
def test_saved_warmup_accepts_exact_flat_activation_seed_without_calculation(frequency):
    from sqlalchemy import select, func
    from app.reference_trading.models import ReferenceBatch
    factory, repository, result = _initialized_route(frequency=frequency)
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(ReferenceBatch))
    assert worker_entry._warmup_saved_capture(repository, result["stream_id"],
        _never_evaluate_initialization()) == "initialized"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceBatch)) == before
        assert session.scalar(select(func.count()).select_from(ReferenceBatch).where(
            ReferenceBatch.kind.in_(("calculation", "capture")))) == 0


def test_initialized_only_warmup_is_successful_but_calculated_count_is_zero(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    factory, repository, result = _initialized_route()
    worker = SimpleNamespace(_repository=repository, scan_live=False,
        _enabled_keys=repository.enabled_forward_work_keys, _work_routes=repository.enabled_forward_work_routes,
        _begin_unit=lambda: None, _end_unit=lambda: None,
        _service_for=lambda _: _never_evaluate_initialization(), _read_input=lambda *_: None)
    @contextmanager
    def opened(**_):
        yield worker, None, None
    monkeypatch.setattr(worker_entry, "open_forward_worker", opened)
    assert worker_entry.warmup_reference_worker() == {"calculated": 0, "initialized": 1}


@pytest.mark.parametrize("drift", (
    "missing_receipt", "receipt_disabled", "receipt_generation", "receipt_revision", "receipt_plan",
    "receipt_start", "stream_generation", "stream_identity", "stream_identity_hash", "revision_status",
    "revision_digest", "seal_payload", "seal_hash", "seal_key", "seal_manifest", "seal_pre_hash",
    "seal_checkpoint", "seal_source_root", "chunk_content", "chunk_payload", "nonflat_checkpoint",
))
def test_initialized_warmup_rejects_broken_seed_activation_and_manifest(drift):
    from dataclasses import replace
    from datetime import timedelta
    from sqlalchemy import select
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream
    from app.reference_trading.repository import _checkpoint_hash
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
    factory, repository, result = _initialized_route()
    with factory() as session, session.begin():
        stream = session.get(ReferenceStream, result["stream_id"])
        revision = session.get(ReferenceRevision, (stream.stream_id, result["revision_id"]))
        seal = session.get(ReferenceBatch, revision.checkpoint_batch_id)
        receipt = session.get(ReferenceActivationReceipt, result["receipt_id"])
        chunk = session.scalar(select(ReferenceBatch).where(ReferenceBatch.kind == "seed_chunk"))
        if drift == "missing_receipt":
            session.delete(receipt)
        elif drift == "receipt_disabled":
            receipt.disabled_at = receipt.activated_at
        elif drift == "receipt_generation":
            receipt.generation = 2
        elif drift == "receipt_revision":
            receipt.revision_id = "another-revision"
        elif drift == "receipt_plan":
            receipt.plan_hash = "0" * 64
        elif drift == "receipt_start":
            receipt.recording_start += timedelta(seconds=1)
        elif drift == "stream_generation":
            stream.activation_generation = 2
        elif drift == "stream_identity":
            stream.profile_id = "another-profile"
        elif drift == "stream_identity_hash":
            stream.identity_hash = "0" * 64
        elif drift == "revision_status":
            revision.status = "candidate"
        elif drift == "revision_digest":
            revision.dependency_digest = "0" * 64
        elif drift == "seal_payload":
            seal.payload_hash = "0" * 64
        elif drift == "seal_hash":
            seal.post_state_hash = "0" * 64
        elif drift == "seal_key":
            seal.batch_key = "another-seed"
        elif drift == "seal_manifest":
            seal.dependency_manifest = {"changed": True}
        elif drift == "seal_pre_hash":
            seal.pre_state_hash = "0" * 64
        elif drift == "seal_checkpoint":
            seal.checkpoint_text = "{}"
        elif drift == "seal_source_root":
            seal.source_evidence = {"seed_root_hash": "0" * 64}
        elif drift == "chunk_content":
            chunk.seed_chunk_text += "changed"
        elif drift == "chunk_payload":
            chunk.payload_hash = "0" * 64
        elif drift == "nonflat_checkpoint":
            _, checkpoint = repository.load_checkpoint(stream.stream_id)
            changed = replace(checkpoint, reference_state=replace(checkpoint.reference_state, last_input_hash="not-initial"))
            seal.checkpoint_text = adapter_checkpoint_to_json(changed, strategy_schema=seal.strategy_schema)
            seal.post_state_hash = _checkpoint_hash(seal.checkpoint_text)
    with pytest.raises((RuntimeError, ValueError), match="REFERENCE_WARMUP_"):
        worker_entry._warmup_saved_capture(repository, result["stream_id"], _never_evaluate_initialization())


def test_initialized_warmup_rejects_any_capture_even_without_calculation():
    from datetime import timedelta
    from app.reference_trading.capture import ForwardCapture
    from tests.reference_trading.test_subing_activation import NOW
    _, repository, result = _initialized_route()
    capture = ForwardCapture(result["stream_id"], result["revision_id"], 1, "M2601:original",
        NOW + timedelta(minutes=3), NOW + timedelta(minutes=4), "completed_live", {}, {}, "first_seen")
    repository.capture_forward(capture)
    with pytest.raises(RuntimeError, match="REFERENCE_WARMUP_"):
        worker_entry._warmup_saved_capture(repository, result["stream_id"], _never_evaluate_initialization())


def test_prior_calculation_with_missing_preimage_never_becomes_initialized():
    from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
    factory, repository, result = _initialized_route()
    with factory() as session, session.begin():
        stream = session.get(ReferenceStream, result["stream_id"])
        revision = session.get(ReferenceRevision, (stream.stream_id, result["revision_id"]))
        seal = session.get(ReferenceBatch, revision.checkpoint_batch_id)
        seal.kind, seal.seq, seal.expected_seq = "calculation", 2, 1
        revision.last_seq, stream.latest_seq = 2, 2
    with pytest.raises(RuntimeError, match="REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE"):
        worker_entry._warmup_saved_capture(repository, result["stream_id"], _never_evaluate_initialization())


def test_saved_warmup_keeps_two_batch_replay_and_exact_capture_linkage():
    from datetime import timedelta
    from types import SimpleNamespace
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
    from tests.reference_trading.test_subing_activation import NOW
    factory, repository, result = _initialized_route()
    capture = ForwardCapture(result["stream_id"], result["revision_id"], 1, "original-weekly",
        NOW + timedelta(minutes=3), NOW + timedelta(minutes=4), "canonical_completed", {}, {}, "first_seen")
    identifier = repository.capture_forward(capture)
    with factory() as session, session.begin():
        stream = session.get(ReferenceStream, result["stream_id"])
        revision = session.get(ReferenceRevision, (stream.stream_id, result["revision_id"]))
        seed = session.get(ReferenceBatch, revision.checkpoint_batch_id)
        fields = {column.name: getattr(seed, column.name) for column in seed.__table__.columns}
        fields.update(batch_id="real-calculation", batch_key="calculation-fixture", kind="calculation", seq=2,
            expected_seq=1, source_evidence={"forward_capture_v1": {
                "capture_id": identifier, "hash": capture.capture_hash, "generation": 1}})
        session.add(ReferenceBatch(**fields))
        stored = session.get(ReferenceBatch, identifier)
        stored.consumed_by_batch_id, stored.outcome = "real-calculation", "consumed"
        revision.last_seq, revision.checkpoint_batch_id, stream.latest_seq = 2, "real-calculation", 2
    evaluated = []
    service = SimpleNamespace(_evaluator=lambda token, checkpoint, evidence: evaluated.append((token, checkpoint, evidence)))
    assert worker_entry._warmup_saved_capture(repository, result["stream_id"], service) == "calculated"
    assert len(evaluated) == 1
    assert evaluated[0][0].seq == 1
    assert evaluated[0][2] == {**capture.evidence(), "capture_id": identifier}


@pytest.mark.parametrize("intake_error,proof_present,expected", [(None, True, "ready"),
    ("OBSERVATION_CURSOR_EXPIRED", True, "not_ready"), (None, False, "not_ready")])
def test_receiving_error_or_missing_readback_prevents_owner_ready_without_rewriting_calculation(monkeypatch, intake_error, proof_present, expected):
    from contextlib import contextmanager
    from types import SimpleNamespace
    calls = []
    owner = SimpleNamespace(mark_ready=lambda proof: calls.append(("ready", proof)),
        mark_not_ready=lambda proof: calls.append(("not_ready", proof)))
    @contextmanager
    def components(**kwargs):
        kwargs["report_health"]({"stage": "receiving_cycle", "ready": True, "blocked_count": 0,
            "receiving": {"protocol_version": 2, "intake_error": intake_error,
                "waiting_history_proof": {"schema_version": 1, "kind": "reference_receiving_operational_v1",
                    "waiting_count": 0, "pending_count": 0, "blocked_pairs_sha256": "a" * 64,
                    "heads_sha256": "b" * 64} if proof_present else None}})
        yield (None, None, None)
    monkeypatch.setattr(worker_entry, "_open_forward_worker", components)
    with worker_entry.open_forward_worker(ownership=owner):
        pass
    assert calls[-1][0] == expected
    assert calls[-1][1]["reference_runtime"]["ready"] is True
    assert calls[-1][1]["reference_runtime"]["blocked_count"] == 0
    assert "receiving" not in calls[-1][1]["reference_runtime"]
    assert calls[-1][1]["receiving"]["intake_error"] == intake_error


@pytest.mark.parametrize("receiving", [None, {"protocol_version": 2, "intake_error": None,
    "waiting_history_proof": {"schema_version": 1, "kind": "reference_receiving_operational_v1"}}])
def test_explicit_null_or_incomplete_receiving_is_not_legacy_readiness(monkeypatch, receiving):
    from contextlib import contextmanager
    from types import SimpleNamespace
    calls = []
    owner = SimpleNamespace(mark_ready=lambda proof: calls.append(("ready", proof)),
        mark_not_ready=lambda proof: calls.append(("not_ready", proof)))
    @contextmanager
    def components(**kwargs):
        kwargs["report_health"]({"stage": "cycle", "ready": True, "blocked_count": 0,
                                "receiving": receiving})
        yield (None, None, None)
    monkeypatch.setattr(worker_entry, "_open_forward_worker", components)
    with worker_entry.open_forward_worker(ownership=owner):
        pass
    assert calls[-1][0] == "not_ready"
    assert calls[-1][1]["reference_runtime"]["ready"] is True
