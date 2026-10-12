from dataclasses import asdict
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from app.reference_trading.bounded_recovery import BoundedForwardRecovery
from app.reference_trading.recovery_campaign import (
    AttemptProgress, RecoveryCampaignError, apply_campaign, canonical, digest,
    validate_campaign, write_once,
)
from tests.reference_trading.test_newow_worker_recovery import _setup


def frozen_one():
    factory, repo, identity, _, start, observed, _ = _setup(frequency='60m')
    endpoints = (start+timedelta(seconds=1),)
    recovery = BoundedForwardRecovery(factory, verify_gap=lambda *_:endpoints)
    plan = recovery.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed+timedelta(minutes=5), journal_proof={'cursor':'0-0'})
    content = json.loads(canonical({'schema_version':1,'identity':{'code':'exact'},'day':start.date().isoformat(),
        'reference_cursor':'0-0','tail_id':'1-0','groups':[{'product':identity.product,
        'routes':[identity.stream_id], 'proof':{'replay_envelopes':[],'replay_sha256':digest([])},
        'plans':[asdict(plan)]}]}))
    content['plan_hash'] = digest(content)
    return content, repo, recovery, plan, observed


def test_frozen_plan_and_attempt_are_exclusive_and_tamper_evident(tmp_path):
    frozen, _, _, _, _ = frozen_one()
    path = tmp_path/'fresh-plan.json'
    write_once(path, frozen)
    with pytest.raises(FileExistsError):
        write_once(path, frozen)
    assert len(validate_campaign(json.loads(path.read_text()), expected_hash=frozen['plan_hash'])) == 1
    altered = json.loads(path.read_text())
    altered['tail_id'] = '2-0'
    with pytest.raises(RecoveryCampaignError, match='RECOVERY_CAMPAIGN_HASH_CONFLICT'):
        validate_campaign(altered, expected_hash=frozen['plan_hash'])
    progress = AttemptProgress(tmp_path/'attempt-001', plan_hash=frozen['plan_hash'])
    progress.close()
    with pytest.raises(FileExistsError):
        AttemptProgress(tmp_path/'attempt-001', plan_hash=frozen['plan_hash'])


def test_commit_unknown_records_terminal_stop_and_does_not_process_gap_or_ack(tmp_path):
    frozen, repo, recovery, _, observed = frozen_one()
    from app.reference_trading.repository import RepositoryConflict
    calls = []
    def unknown(*args, **kwargs):
        calls.append('mutation')
        raise RepositoryConflict('RECOVERY_COMMIT_OUTCOME_UNKNOWN')
    recovery.apply = unknown
    worker = SimpleNamespace(_service_for=lambda _:calls.append('gap'), _repository=repo)
    wake = SimpleNamespace(poll=lambda:calls.append('ack'))
    progress = AttemptProgress(tmp_path/'attempt-001', plan_hash=frozen['plan_hash'])
    try:
        with pytest.raises(RepositoryConflict, match='RECOVERY_COMMIT_OUTCOME_UNKNOWN'):
            apply_campaign(frozen, recovery=recovery, worker=worker, wake=wake, progress=progress,
                now=lambda:observed, assert_guard=lambda:None)
    finally:
        progress.close()
    assert calls == ['mutation']
    events = [json.loads(line) for line in (progress.path/'progress.jsonl').read_text().splitlines()]
    assert [item['stage'] for item in events] == ['started','activation_started','stopped_no_retry']
    assert repo.forward_source_context(frozen['groups'][0]['routes'][0])[2] == 1


def test_campaign_retains_known_activation_prefix_before_later_failure(tmp_path):
    frozen, repo, recovery, plan, observed = frozen_one()
    # A failed gap stops after the real atomic activation commit; exact IDs stay readable.
    class Service:
        def process_pending(self, route):
            raise RuntimeError('gap verification failed')
    worker = SimpleNamespace(_service_for=lambda _:Service(), _repository=repo)
    progress = AttemptProgress(tmp_path/'attempt-001', plan_hash=frozen['plan_hash'])
    try:
        with pytest.raises(RuntimeError, match='gap verification failed'):
            apply_campaign(frozen, recovery=recovery, worker=worker,
                wake=SimpleNamespace(poll=lambda:pytest.fail('ack after failure')),
                progress=progress, now=lambda:observed, assert_guard=lambda:None)
    finally:
        progress.close()
    events = [json.loads(line) for line in (progress.path/'progress.jsonl').read_text().splitlines()]
    committed = [item for item in events if item['stage']=='activation_committed']
    assert len(committed) == 1
    assert recovery.readback(plan) == (committed[0]['receipt_id'], committed[0]['capture_id'])
    assert events[-1]['stage'] == 'stopped_no_retry'


def test_parked_owner_guard_holds_real_os_lock_without_rewriting_owner(tmp_path, monkeypatch):
    from scripts.reference_observation_recovery import parked_reference_guard
    import app.runtime_bindings as bindings
    from app.runtime_handover import owner_lock_available
    expected = {'generation':16}
    monkeypatch.setattr(bindings,'resolve_service_binding',lambda _service:SimpleNamespace(generation=16))
    monkeypatch.setattr(bindings,'bindings_sha256',lambda:'a'*64)
    import scripts.reference_observation_recovery as entry
    monkeypatch.setattr(entry, 'asdict', lambda _:expected)
    directory = tmp_path.resolve()
    owner = directory/'reference-worker.owner.json'
    owner.write_text(json.dumps({'schema_version':1,'service':'reference-worker','generation':16,'phase':'parked','ready':False}))
    handover = directory/'reference-worker.handover.json'
    handover.write_text(json.dumps({'generation':16,'phase':'drain'}))
    lock = directory/'reference-worker.owner.lock'
    lock.touch(mode=0o600)
    owner.chmod(0o600)
    handover.chmod(0o600)
    before = owner.read_bytes()
    with parked_reference_guard(directory=directory, expected_binding=expected) as (guard, _hash):
        assert not owner_lock_available('reference-worker',runtime_dir=directory)
        guard()
    assert owner_lock_available('reference-worker',runtime_dir=directory)
    assert owner.read_bytes() == before


from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401, E402
from tests.reference_trading.test_newow_worker_recovery import forward_postgresql  # noqa: F401, E402


def test_cli_components_compose_real_pg_guards_without_starting_threads(forward_postgresql, tmp_path, monkeypatch):  # noqa: F811
    from sqlalchemy.orm import sessionmaker
    import app.db.session as database
    import app.market_data.composition as composition
    import app.redis_connections as connections
    from scripts.reference_observation_recovery import components
    factory = sessionmaker(forward_postgresql, expire_on_commit=False)
    monkeypatch.setattr(database, 'SessionLocal', factory)
    monkeypatch.setattr(composition, 'build_market_data_service', lambda _:SimpleNamespace())
    monkeypatch.setattr(composition, 'canonical_root', lambda:tmp_path)
    pubsub = SimpleNamespace(close=lambda:None)
    redis = SimpleNamespace(pubsub=lambda **kwargs:pubsub, close=lambda:None)
    monkeypatch.setattr(connections, 'get_redis_connection', lambda:redis)
    with components(lambda:None) as (_repository, _recovery, _authority, worker, wake):
        assert worker.scan_live is False
        assert wake._stream.kind == 'completed'
        assert worker.source_envelope is None


def test_attempt_directory_entries_are_durable_before_return(tmp_path, monkeypatch):
    import os
    import stat
    import app.reference_trading.recovery_campaign as campaign
    original = os.fsync
    kinds = []
    def fsync(fd):
        kinds.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
        original(fd)
    monkeypatch.setattr(campaign.os, 'fsync', fsync)
    progress = AttemptProgress(tmp_path/'attempt', plan_hash='a'*64)
    try:
        assert kinds == ['directory', 'file', 'directory']
        progress.record('mutation_intent')
        assert kinds[-1] == 'file'
    finally:
        progress.close()
