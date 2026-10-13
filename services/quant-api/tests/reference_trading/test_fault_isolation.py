from datetime import UTC

import pytest

from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_live_wake import _durable_wake_with_backlog


def test_domain_conflict_reason_survives_worker_diagnostics():
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    worker._read_input = lambda *_: (_ for _ in ()).throw(RepositoryConflict('FORWARD_COMMIT_OUTCOME_UNKNOWN'))
    wake.poll()
    assert worker.health().blocked[-1] == ('rb-60m', 'FORWARD_COMMIT_OUTCOME_UNKNOWN')
    assert worker.diagnostic_health(stage='test', ready=False)['blocked_counts'] == {'FORWARD_COMMIT_OUTCOME_UNKNOWN': 1}
    assert not acknowledgements


def test_known_conflict_transfers_original_before_ack_and_other_product_progresses():
    from copy import deepcopy
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    original = wake._stream.read()[0]
    second = deepcopy(original)
    second.stream_id = '2-0'
    second.channel = 'live:bar:cu:60m'
    wake._validated_routes = lambda channel, _: (original.confirmed_at, ('rb-60m',) if ':rb:' in channel else ('cu-60m',))
    wake._stream.read = lambda *_, **__: (original, second)
    calls = []
    worker._repository.quarantine_forward_observation = lambda routes, envelope, **_kw: calls.append(('transfer', envelope.stream_id)) or True
    worker._read_input = lambda route, *_: (_ for _ in ()).throw(RepositoryConflict('REFERENCE_CANONICAL_MISMATCH')) if route == 'rb-60m' else None
    wake.poll()
    assert calls == [('transfer', '1-0')]
    assert len(acknowledgements) == 2


def test_unknown_commit_never_transfers_or_acknowledges():
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    transfers = []
    worker._repository.quarantine_forward_observation = lambda *_, **_kw: transfers.append(True) or True
    worker._read_input = lambda *_: (_ for _ in ()).throw(RepositoryConflict('FORWARD_COMMIT_OUTCOME_UNKNOWN'))
    wake.poll()
    assert not transfers and not acknowledgements


def test_quarantine_transfer_failure_keeps_cursor_and_unknown_is_not_retried():
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    worker._read_input = lambda *_: (_ for _ in ()).throw(RepositoryConflict('REFERENCE_CANONICAL_MISMATCH'))
    def unknown(*_, **_kw):
        raise RepositoryConflict('QUARANTINE_COMMIT_OUTCOME_UNKNOWN')
    worker._repository.quarantine_forward_observation = unknown
    with pytest.raises(RepositoryConflict, match='QUARANTINE_COMMIT_OUTCOME_UNKNOWN'):
        wake.poll()
    assert not acknowledgements


def _quarantine_group(tmp_path, engine=None):
    from dataclasses import replace
    from datetime import timedelta
    from hashlib import sha256
    from sqlalchemy import create_engine
    from test_forward_capture import _active, _capture
    from test_activation import NOW
    from app.reference_trading.activation import ForwardActivation
    from app.reference_trading.contracts import SeedChunk
    from app.reference_trading.repository import ReferenceRepository, _digest
    from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
    from app.market_data.observation_stream import ObservationEnvelope

    engine = engine or create_engine(f'sqlite+pysqlite:///{tmp_path / "quarantine.db"}')
    factory, identity, revision, _ = _active(engine)
    repo = ReferenceRepository(factory)
    routes = [identity.stream_id]
    _, checkpoint = repo.load_checkpoint(identity.stream_id)
    for code in ('newow_oscillation', 'newow_main_rise', 'newow_dual_fusion'):
        other = replace(identity, strategy_code=code)
        row = repo.ensure_stream(other)
        manifest = {'source': 'fixture'}
        rev = repo.create_revision(other.stream_id, row.row_version, _digest(manifest))
        repo.stage_seed_chunk(rev, SeedChunk('seed', 0, 1, sha256(b'seed').hexdigest(), 'seed'))
        from guiyi_quant.reference_trading import ReferenceState
        repo.seal_seed(rev, manifest, replace(checkpoint, stream=other,
            reference_state=ReferenceState.flat(other, recording_start=NOW + timedelta(seconds=1))),
            'newow_product_replay_v1')
        activation = ForwardActivation(factory)
        plan = activation.plan(other.stream_id, rev, host='test-host', environment='isolated',
            recording_start=NOW + timedelta(seconds=1), expires_at=NOW + timedelta(minutes=1),
            budget={'max_pending': 32})
        activation.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
        routes.append(other.stream_id)
    capture = replace(_capture(identity, revision),
                      source_proof={'source_sha256': sha256(b'old').hexdigest()})
    capture_id = repo.capture_forward(capture)
    ForwardReconciler(factory, lambda _: CanonicalEvidence('canonical-v2', sha256(b'new').hexdigest())).reconcile(
        capture_id, now=NOW + timedelta(hours=1))
    end = NOW + timedelta(seconds=1)
    observation = ObservationEnvelope('original', end.date(), end,
        f'live:bar:{identity.product.lower()}:{identity.frequency}',
        {'bar_end': end.isoformat(), 'trading_day': end.date().isoformat(), 'contract': 'RB2610'},
        True, '1-0', end, end + timedelta(seconds=1))
    return factory, tuple(routes), observation


def test_real_sqlite_quarantine_is_atomic_durable_idempotent_and_preserves_time(tmp_path):
    from datetime import timedelta
    from sqlalchemy import select
    from app.reference_trading.quarantine import quarantine_observation
    from app.reference_trading.models import ReferenceBatch, ReferenceStream
    factory, routes, observation = _quarantine_group(tmp_path)
    now = observation.confirmed_at + timedelta(hours=3)
    fences = []
    assert quarantine_observation(factory, routes, observation, assert_owned=lambda: fences.append(True), now=lambda: now)
    with factory() as session:
        rows = session.scalars(select(ReferenceBatch).where(ReferenceBatch.kind == 'diagnostic')).all()
        assert len(rows) == 4
        originals = [(r.batch_id, r.payload_hash, r.source_evidence, r.processed_at) for r in rows]
        for row in rows:
            assert row.processed_at.replace(tzinfo=UTC) == now
            assert row.observed_at.replace(tzinfo=UTC) == observation.confirmed_at
            assert row.source_evidence['quarantine_v1']['envelope'] == __import__('json').loads(observation.to_json())
        assert all(session.get(ReferenceStream, route).latest_seq == 1 for route in routes)
    # A fresh session/repository after restart finds the exact same originals.
    assert quarantine_observation(factory, routes, observation, assert_owned=lambda: fences.append(True), now=lambda: now + timedelta(hours=1))
    with factory() as session:
        rows = session.scalars(select(ReferenceBatch).where(ReferenceBatch.kind == 'diagnostic')).all()
        assert originals == [(r.batch_id, r.payload_hash, r.source_evidence, r.processed_at) for r in rows]
    assert len(fences) == 2


def test_quarantine_partial_fusion_group_and_altered_original_fail_closed(tmp_path):
    from dataclasses import replace
    from app.reference_trading.quarantine import quarantine_observation
    factory, routes, observation = _quarantine_group(tmp_path)
    with pytest.raises(RepositoryConflict, match='QUARANTINE_SCOPE_CONFLICT'):
        quarantine_observation(factory, routes[:3], observation, assert_owned=lambda: None)
    assert quarantine_observation(factory, routes, observation, assert_owned=lambda: None)
    with pytest.raises(RepositoryConflict, match='QUARANTINE_RECEIPT_CONFLICT'):
        quarantine_observation(factory, routes, replace(observation, data={**observation.data, 'close': '9999'}), assert_owned=lambda: None)


def test_ownership_loss_rolls_back_all_four_receipts(tmp_path):
    from sqlalchemy import select, func
    from app.reference_trading.quarantine import quarantine_observation
    from app.reference_trading.models import ReferenceBatch
    factory, routes, observation = _quarantine_group(tmp_path)
    def lost():
        raise RuntimeError('OWNERSHIP_LOST')
    with pytest.raises(RuntimeError, match='OWNERSHIP_LOST'):
        quarantine_observation(factory, routes, observation, assert_owned=lost)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind == 'diagnostic')) == 0


def test_mixed_unknown_route_cannot_quarantine_group():
    wake, worker, _, acknowledgements = _durable_wake_with_backlog()
    worker._work_routes = lambda _: ('rb-60m', 'unknown-route')
    worker._read_input = lambda route, *_: (_ for _ in ()).throw(RepositoryConflict(
        'REFERENCE_CANONICAL_MISMATCH' if route == 'rb-60m' else 'FORWARD_COMMIT_OUTCOME_UNKNOWN'))
    transfers = []
    worker._repository.quarantine_forward_observation = lambda *_, **__: transfers.append(True) or True
    wake.poll()
    assert not transfers and not acknowledgements


def test_health_and_matrix_never_report_old_ready_for_conflict_group(tmp_path):
    from app.reference_trading.health import ForwardReferenceHealth
    from app.reference_trading.recording_matrix import newow_recording_matrix
    from app.reference_trading.quarantine import quarantine_observation
    factory, routes, observation = _quarantine_group(tmp_path)
    quarantine_observation(factory, routes, observation, assert_owned=lambda: None)
    result = ForwardReferenceHealth(factory).read()
    assert len(result['streams']) == 4
    for row in result['streams']:
        assert row['status'] == 'DATA_CONFLICT'
        assert row['latest_state'] is None
        assert row['quarantined_observation_count'] == 1
        assert row['unavailable_reason'] == 'REFERENCE_CANONICAL_MISMATCH'
    matrix = newow_recording_matrix((result['streams'][0]['product'],), result)
    assert all(row['status'] == 'DATA_CONFLICT' for row in matrix['items'] if row['stream_id'] in routes)


def test_sqlite_unknown_commit_keeps_persisted_receipts_for_restart_readback(tmp_path):
    from sqlalchemy import event, select, func
    from sqlalchemy.exc import OperationalError
    from app.reference_trading.quarantine import quarantine_observation
    from app.reference_trading.models import ReferenceBatch
    factory, routes, observation = _quarantine_group(tmp_path)
    def failed_reply(_session):
        raise OperationalError('commit response lost', {}, None)
    event.listen(factory.class_, 'after_commit', failed_reply)
    try:
        with pytest.raises(RepositoryConflict, match='QUARANTINE_COMMIT_OUTCOME_UNKNOWN'):
            quarantine_observation(factory, routes, observation, assert_owned=lambda: None)
    finally:
        event.remove(factory.class_, 'after_commit', failed_reply)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind == 'diagnostic')) == 4
    assert quarantine_observation(factory, routes, observation, assert_owned=lambda: None)
