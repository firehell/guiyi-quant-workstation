from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.bounded_recovery import BoundedForwardRecovery, _receipt_hash
from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.forward_inputs import capture_newow_envelope, ForwardInputUnavailable
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch
from app.reference_trading.repository import RepositoryConflict
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_newow_worker_recovery import _setup, forward_postgresql  # noqa: F401


def _envelope(identity, start, *, end=None):
    end = end or start + timedelta(seconds=4)
    confirmed = end + timedelta(seconds=5)
    received = end + timedelta(seconds=1)
    raw = dict(bar_end=end.isoformat(), trading_day=end.date().isoformat(), contract='RB2610',
               open='3500', high='3510', low='3490', close='3501', volume='1',
               turnover=None, open_interest='1')
    return ObservationEnvelope('original', end.date(), received,
        f'live:bar:{identity.product}:{identity.frequency}', raw, True, '1-0', received, confirmed)


def test_frozen_envelope_does_not_read_live_snapshot_or_refresh_time():
    _, _, identity, revision, start, _, _ = _setup(frequency='60m')
    item = _envelope(identity, start)
    capture = capture_newow_envelope(item, identity, revision_id=revision, generation=1,
        after=start, now=item.confirmed_at, owner_segments=lambda *_: ('owner', 'calc'),
        expected_endpoints=lambda *_: (item.confirmed_at-timedelta(seconds=5),),
        capability_ready=lambda _: True)
    assert capture.observed_at == item.confirmed_at
    assert capture.source_proof['raw_received_at'] == item.raw_received_at.isoformat()
    assert capture.input_payload['bar']['close'] == '3501'
    assert capture.source_proof['journal_stream_id'] == '1-0'
    with pytest.raises(ForwardInputUnavailable, match='LIVE_EVENT_IDENTITY_CONFLICT'):
        capture_newow_envelope(item, identity, revision_id=revision, generation=1,
            after=start, now=item.confirmed_at+timedelta(days=1), owner_segments=lambda *_: ('owner', 'calc'),
            expected_endpoints=lambda *_: (), capability_ready=lambda _: True)


def _exercise(engine=None, *, preactivation=False):
    factory, repo, identity, revision, start, observed, _ = _setup(frequency='60m', engine=engine)
    endpoints = ((start-timedelta(days=1),) if preactivation else
                 (start + timedelta(seconds=1), start + timedelta(seconds=2)))
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_: endpoints)
    plan = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed+timedelta(minutes=5),
        journal_proof={'cursor': '0-0', 'envelope_sha256': 'a'*64})
    with factory() as session:
        old_hash = _receipt_hash(session.get(ReferenceActivationReceipt, plan.receipt_id))
        old_batch = session.get(ReferenceBatch, plan.checkpoint_batch_id).checkpoint_text
    receipt, capture = service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed)
    assert service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed+timedelta(days=1)) == (receipt, capture)
    with factory() as session:
        assert _receipt_hash(session.get(ReferenceActivationReceipt, plan.receipt_id)) == old_hash
        assert session.get(ReferenceBatch, plan.checkpoint_batch_id).checkpoint_text == old_batch
        assert len(session.scalars(select(ReferenceActivationReceipt)).all()) == 2
    assert repo.forward_source_context(identity.stream_id)[5] == 'block'
    assert service.consumed_calculation(plan) is None
    worker = build_forward_reference_worker(repository=repo, market_read=None, newow_reader=None,
        owner_segments=lambda *_: ('owner', 'calc'), expected_endpoints=lambda *args: (args[-1],),
        newow_capability_ready=lambda _: True, now=lambda: observed, enabled=True)
    worker.wake(identity.stream_id)
    worker.run_round()
    assert not worker.health().blocked
    assert service.consumed_calculation(plan) is not None
    _, checkpoint = repo.load_checkpoint(identity.stream_id, revision)
    assert checkpoint.computed_through == endpoints[-1]
    from guiyi_quant.newow.product_adapters import seed_replay_state
    assert checkpoint.strategy_state == seed_replay_state()
    with factory() as session:
        assert session.get(ReferenceBatch, capture).consumed_by_batch_id is not None
        assert _receipt_hash(session.get(ReferenceActivationReceipt, plan.receipt_id)) == old_hash
        from app.reference_trading.query import HistoricalReferenceQuery
        coverage = HistoricalReferenceQuery._coverage(session,
            SimpleNamespace(stream_id=identity.stream_id, revision_id=revision, seq=100))
        assert coverage['computed_through'] is None
        assert coverage['observation_boundary_at'] == endpoints[-1].isoformat()
    # The first surviving observation stays a real observation after the interruption.
    envelope = _envelope(identity, start)
    from app.reference_trading.journal_recovery import replay_expired_originals, _digest
    rows = [[envelope.stream_id, envelope.to_json()]]
    replay_expired_originals(worker, (identity.stream_id,),
        {'replay_envelopes':rows, 'replay_sha256':_digest(rows)},
        now=envelope.confirmed_at+timedelta(days=1))
    assert worker.source_envelope is None and worker.source_observed_at is None
    _, checkpoint = repo.load_checkpoint(identity.stream_id, revision)
    assert checkpoint.computed_through == envelope.confirmed_at-timedelta(seconds=5)
    with factory() as session:
        batches = session.scalars(select(ReferenceBatch).where(ReferenceBatch.kind=='capture')).all()
        real = [batch for batch in batches if batch.source_evidence['forward_capture_v1']['source_kind']=='completed_live']
        assert len(real) == 1
        assert real[0].source_evidence['forward_capture_v1']['observed_at'] == envelope.confirmed_at.isoformat()
    return service, plan, factory, repo


def test_exact_recovery_preserves_old_receipt_and_surviving_observation():
    _exercise()


def test_postgresql_exact_recovery_preserves_old_receipt_and_surviving_observation(forward_postgresql):  # noqa: F811
    _exercise(forward_postgresql)


def test_postgresql_preactivation_gap_retains_flat_account_and_explicit_boundary(forward_postgresql):  # noqa: F811
    _exercise(forward_postgresql, preactivation=True)


def test_preimage_or_authority_drift_rolls_back_without_activation_change():
    factory, repo, identity, _, start, observed, _ = _setup(frequency='60m')
    endpoints = (start+timedelta(seconds=1),)
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_: endpoints)
    plan = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed+timedelta(minutes=5), journal_proof={'cursor':'0-0'})
    service._verify_gap = lambda *_: ()
    with pytest.raises(RepositoryConflict, match='RECOVERY_SOURCE_DRIFT'):
        service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed)
    assert repo.forward_source_context(identity.stream_id)[2] == 1
    assert repo.read_pending_capture(identity.stream_id) is None


def test_entire_journal_keeps_already_acked_original_and_only_absence_is_gap():
    from app.reference_trading.journal_recovery import JournalRecoveryAuthority
    _, _, identity, _, start, _, _ = _setup(frequency='60m')
    earliest = _envelope(identity, start)
    following = _envelope(identity, start, end=start+timedelta(seconds=8))
    following = replace(following, stream_id='3-0', observation_id='following')
    missing_end = start+timedelta(seconds=2)
    rows = [('1-0', {'envelope':earliest.to_json()}), ('3-0', {'envelope':following.to_json()})]
    calls = []
    redis = SimpleNamespace(xrange=lambda key, **kwargs: calls.append(kwargs) or rows)
    journal = SimpleNamespace(kind='completed', cursor=lambda *_:'2-0', tail=lambda _:'3-0',
                              key=lambda _:'journal', redis=redis)
    def expected(_identity, _contract, _day, after, cutoff):
        return tuple(end for end in (missing_end, start+timedelta(seconds=4), start+timedelta(seconds=8))
                     if end > after and end <= cutoff)
    authority = SimpleNamespace(owner_segments=lambda *_:('owner','calc'), expected_endpoints=expected)
    planner = JournalRecoveryAuthority(journal, authority)
    proof, missing = planner.freeze(identity, start, day=start.date(), expected_cursor='2-0')
    assert missing == (missing_end,)
    assert calls[0]['min'] == '-'
    assert [item.stream_id for item in planner.replay_envelopes(proof)] == ['1-0', '3-0']
    assert planner.verify_gap(identity, start, proof) == missing
    rows[0][1]['envelope'] = replace(earliest, observation_id='changed').to_json()
    with pytest.raises(RepositoryConflict, match='RECOVERY_SOURCE_DRIFT'):
        planner.verify_gap(identity, start, proof)


def test_internal_gap_cannot_skip_a_surviving_original():
    from app.reference_trading.journal_recovery import JournalRecoveryAuthority
    _, _, identity, _, start, _, _ = _setup(frequency='60m')
    earliest = _envelope(identity, start)
    last = replace(_envelope(identity, start, end=start+timedelta(seconds=8)),
                   stream_id='2-0', observation_id='last')
    journal = SimpleNamespace(kind='completed', cursor=lambda *_:'0-0', tail=lambda _:'2-0', key=lambda _:'journal',
        redis=SimpleNamespace(xrange=lambda *args, **kwargs:[('1-0',{'envelope':earliest.to_json()}),
                                                          ('2-0',{'envelope':last.to_json()})]))
    authority = SimpleNamespace(owner_segments=lambda *_:('owner','calc'),
        expected_endpoints=lambda *_:tuple(start+timedelta(seconds=n) for n in (4,6,8)))
    with pytest.raises(RepositoryConflict, match='RECOVERY_PREFIX_GAP_REQUIRED'):
        JournalRecoveryAuthority(journal, authority).freeze(identity, start,
            day=start.date(), expected_cursor='0-0')


def test_missing_warmup_before_activation_does_not_invent_reference_completed_bar():
    from app.reference_trading.recovery import capture_observation_gap, evaluate_observation_gap
    _, repo, identity, revision, start, observed, _ = _setup(frequency='60m')
    token, checkpoint = repo.load_checkpoint(identity.stream_id, revision)
    boundary = start-timedelta(days=1)
    capture = capture_observation_gap(identity, revision_id=revision, generation=2,
        previous_watermark=None, observed_at=observed, reason='OBSERVATION_GAP',
        trading_day=start.date(), endpoints=(boundary,), interruption_end=boundary)
    prepared = evaluate_observation_gap(token, checkpoint,
        {**capture.evidence(), 'capture_id':'exact-interruption'}, dependency_manifest={})
    assert prepared.checkpoint.computed_through == boundary
    assert prepared.checkpoint.reference_state.computed_through is None
    assert prepared.checkpoint.reference_state.recording_start == start
    assert not prepared.transitions[0].changed_trades
    assert prepared.source_evidence['observation_gap_v1']['interruption_end'] == boundary.isoformat()


def test_recovered_frozen_raw_time_produces_expired_receipt_without_transport():
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    from app.db.base import Base
    from app.notifications.newow import NewowNotificationDispatcher, NewowNotificationDelivery
    from tests.test_newow_notifications import enabled, insert_batch, NOW, Transport
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    enabled(factory)
    insert_batch(factory, frequency='60m')
    _, _, identity, revision, _, _, _ = _setup(frequency='60m')
    original = _envelope(identity, NOW+timedelta(minutes=5)-timedelta(seconds=4))
    capture = capture_newow_envelope(original, identity, revision_id=revision, generation=2,
        after=None, now=original.confirmed_at, owner_segments=lambda *_:('owner','calc'),
        expected_endpoints=lambda *_:(original.confirmed_at-timedelta(seconds=5),),
        capability_ready=lambda _:True)
    recovered_at = original.confirmed_at+timedelta(days=1)
    with factory() as session:
        batch = session.get(ReferenceBatch, 'b')
        batch.observed_at, batch.processed_at = original.confirmed_at, recovered_at
        point = batch.source_evidence['presentation_v1']['points'][0]
        evidence = {'presentation_v1': {'version':'presentation_v1', 'points':[{**point,
            'value':{**point['value'], 'bar_end':capture.bar_end.isoformat(),
                     'observed_at':capture.observed_at.isoformat()}}]},
            'observation_timing_v1': {key:capture.source_proof[key]
                for key in ('raw_received_at','confirmed_at')}}
        batch.source_evidence = evidence
        session.commit()
    transport = Transport()
    dispatcher = NewowNotificationDispatcher(factory, transport=transport,
        topic_hash='hash', clock=lambda:recovered_at)
    assert dispatcher.tick()['attempted'] == 0
    assert dispatcher.tick()['attempted'] == 0
    assert transport.deliveries == []
    with factory() as session:
        expired = session.scalar(select(NewowNotificationDelivery).where(
            NewowNotificationDelivery.status == 'EXPIRED_NO_SEND'))
        assert expired is not None and expired.attempted_at is None


def test_unknown_recovery_commit_reads_once_and_never_retries_mutation():
    from sqlalchemy.exc import OperationalError
    factory, _, identity, _, start, observed, _ = _setup(frequency='60m')
    endpoints = (start+timedelta(seconds=1),)
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_:endpoints)
    plan = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed+timedelta(minutes=5), journal_proof={'cursor':'0-0'})
    calls = []
    def unknown(*args, **kwargs):
        calls.append('apply')
        raise OperationalError('not-displayed', None, RuntimeError('connection lost'))
    service._apply = unknown
    with pytest.raises(RepositoryConflict, match='RECOVERY_COMMIT_OUTCOME_UNKNOWN'):
        service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed)
    assert calls == ['apply']
    assert service.readback(plan) is None


def test_dependency_digest_drift_invalidates_frozen_recovery_plan():
    from app.reference_trading.models import ReferenceRevision
    factory, repo, identity, revision, start, observed, _ = _setup(frequency='60m')
    endpoints = (start+timedelta(seconds=1),)
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_:endpoints)
    plan = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed+timedelta(minutes=5), journal_proof={'cursor':'0-0'})
    with factory() as session:
        session.get(ReferenceRevision, (identity.stream_id, revision)).dependency_digest = '0'*64
        session.commit()
    with pytest.raises(RepositoryConflict, match='RECOVERY_PREIMAGE_DRIFT'):
        service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed)
    assert repo.forward_source_context(identity.stream_id)[2] == 1
    assert repo.read_pending_capture(identity.stream_id) is None


def _consecutive_explicit_interruptions(engine=None):
    factory, repo, identity, revision, start, observed, _ = _setup(frequency='60m', engine=engine)
    endpoints = (start + timedelta(seconds=1),)
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_: endpoints)
    worker = build_forward_reference_worker(repository=repo, market_read=None, newow_reader=None,
        owner_segments=lambda *_: ('owner', 'calc'), expected_endpoints=lambda *args: (args[-1],),
        newow_capability_ready=lambda _: True, now=lambda: observed, enabled=True)
    first = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed, expires_at=observed+timedelta(minutes=5), journal_proof={'first': True})
    service.apply(first, expected_plan_hash=first.plan_hash, now=observed)
    endpoints = (start + timedelta(seconds=2),)
    with pytest.raises(RepositoryConflict, match='RECOVERY_PREIMAGE_INVALID'):
        service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
            observed_at=observed+timedelta(seconds=1), expires_at=observed+timedelta(minutes=5), journal_proof={'second': True, 'kind': 'SERVICE_OUTAGE'})
    worker.wake(identity.stream_id)
    worker.run_round()
    assert service.consumed_calculation(first)
    with factory() as session:
        receipt = session.get(ReferenceActivationReceipt, service.readback(first)[0])
        first_receipt_hash = _receipt_hash(receipt)
    second = service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
        observed_at=observed+timedelta(seconds=1), expires_at=observed+timedelta(minutes=5), journal_proof={'second': True, 'kind': 'SERVICE_OUTAGE'})
    assert second.capture.input_payload['reason'] == 'SERVICE_OUTAGE'
    assert second.capture.generation == first.capture.generation + 1
    assert second.plan_hash != first.plan_hash
    service.apply(second, expected_plan_hash=second.plan_hash, now=observed+timedelta(seconds=1))
    worker.wake(identity.stream_id)
    worker.run_round()
    assert service.consumed_calculation(second)
    assert repo.forward_source_context(identity.stream_id)[5] == 'block'
    with factory() as session:
        assert _receipt_hash(session.get(ReferenceActivationReceipt, second.receipt_id)) == first_receipt_hash
        receipt = session.get(ReferenceActivationReceipt, service.readback(second)[0])
        receipt.budget = {**receipt.budget, 'bounded_recovery_capture_sha256': 'f'*64}
        session.commit()
    endpoints = (start + timedelta(seconds=3),)
    with pytest.raises(RepositoryConflict, match='RECOVERY_PREIMAGE_INVALID'):
        service.plan(identity.stream_id, endpoints=endpoints, trading_day=start.date(),
            observed_at=observed+timedelta(seconds=2), expires_at=observed+timedelta(minutes=5), journal_proof={'third': True})


def test_consecutive_explicit_interruptions_require_exact_consumed_prior_bound():
    _consecutive_explicit_interruptions()


def test_postgresql_consecutive_explicit_interruptions_preserve_prior_receipts(forward_postgresql):  # noqa: F811
    _consecutive_explicit_interruptions(forward_postgresql)


def test_fenced_outage_checks_real_absence_past_endpoints_and_fence_drift():
    from datetime import UTC, date, datetime
    from app.reference_trading.fenced_outage_recovery import FencedOutageAuthority
    _, _, identity, _, start, _, _ = _setup(frequency='60m')
    cutoff = datetime.now(UTC) - timedelta(seconds=3)
    endpoints = (cutoff-timedelta(hours=2), cutoff-timedelta(hours=1))
    rows, keys = [], {}
    redis = SimpleNamespace(get=lambda key: keys.get(key), exists=lambda key: key in keys,
                            xrange=lambda *args, **kwargs: rows)
    journal = SimpleNamespace(kind='completed', redis=redis, key=lambda day:'journal13',
        identity_key=lambda day:'identity13',
        cursor_key=lambda consumer,day:'cursor13', registered_day=lambda consumer:date(2026,10,12),
        tail=lambda day:'0-0' if not rows else rows[-1][0])
    fence = {'feed_absent':True,'generation':17,'actual_old_source_tail':'123-0'}
    authority = SimpleNamespace(expected_endpoints=lambda *args:endpoints, owner_segments=lambda *args:('owner','calc'))
    planner = FencedOutageAuthority(journal, authority, cutoff=cutoff,
        verify_fence=lambda:dict(fence), contract_for_day=lambda *args:'RB2610')
    proof, missing = planner.freeze(identity, None, day=date(2026,10,13), expected_cursor=None)
    assert missing == endpoints and proof['reference_cursor'] is None
    assert proof['journal_count'] == 0 and proof['replay_envelopes'] == []
    assert planner.verify_gap(identity, None, proof) == endpoints
    assert keys == {}  # No NEW_DAY/initialize or cursor write.
    fence['actual_old_source_tail'] = '124-0'
    with pytest.raises(RepositoryConflict, match='RECOVERY_SOURCE_DRIFT'):
        planner.verify_gap(identity, None, proof)
    fence['actual_old_source_tail'] = '123-0'
    keys['identity13'] = True
    with pytest.raises(RepositoryConflict, match='CURSOR_ABSENCE_UNPROVEN'):
        planner.freeze(identity, None, day=date(2026,10,13), expected_cursor=None)
    del keys['identity13']
    keys['journal13'] = True
    with pytest.raises(RepositoryConflict, match='CURSOR_ABSENCE_UNPROVEN'):
        planner.freeze(identity, None, day=date(2026,10,13), expected_cursor=None)
    keys['cursor13'] = '0-0'
    original = _envelope(identity, start)
    original = replace(original, trading_day=date(2026,10,13),
                       data={**original.data, 'trading_day':'2026-10-13'})
    rows.append(('1-0', {'envelope':original.to_json()}))
    with pytest.raises(RepositoryConflict, match='SAVED_ORIGINAL_FIRST'):
        planner.freeze(identity, None, day=date(2026,10,13), expected_cursor='0-0')
    rows.clear()
    authority.expected_endpoints = lambda *args:(cutoff+timedelta(seconds=1),)
    with pytest.raises(RepositoryConflict, match='FUTURE_ENDPOINT_FORBIDDEN'):
        planner.freeze(identity, None, day=date(2026,10,13), expected_cursor='0-0')


@pytest.mark.parametrize('drift', ['budget', 'capture_generation', 'calculation_link', 'calculation_outcome'])
def test_consumed_bound_corruption_never_grants_next_activation(drift):
    service, first, factory, repo = _exercise()
    from app.reference_trading.models import ReferenceStream
    with factory() as session:
        receipt = session.get(ReferenceActivationReceipt, service.readback(first)[0])
        capture = session.get(ReferenceBatch, service.readback(first)[1])
        calculation = session.get(ReferenceBatch, capture.consumed_by_batch_id)
        if drift == 'budget':
            receipt.budget = {**receipt.budget, 'operator_changed_budget': 1}
        elif drift == 'capture_generation':
            capture.source_evidence = {'forward_capture_v1': {**capture.source_evidence['forward_capture_v1'], 'generation': 999}}
        elif drift == 'calculation_link':
            calculation.source_evidence = {**calculation.source_evidence, 'forward_capture_v1': {**calculation.source_evidence['forward_capture_v1'], 'capture_id': 'wrong'}}
        else:
            calculation.outcome = 'unknown'
        stream = session.get(ReferenceStream, first.capture.stream_id)
        generation = stream.activation_generation
        session.commit()
    endpoint = first.capture.observed_at + timedelta(seconds=20)
    service._verify_gap = lambda *_:(endpoint,)
    with pytest.raises(RepositoryConflict, match='RECOVERY_PREIMAGE_INVALID'):
        service.plan(first.capture.stream_id, endpoints=(endpoint,), trading_day=endpoint.date(),
            observed_at=endpoint+timedelta(seconds=1), expires_at=endpoint+timedelta(minutes=5), journal_proof={'next': True})
    with factory() as session:
        assert session.get(ReferenceStream, first.capture.stream_id).activation_generation == generation


def test_isolated_redis_pre_new_day_outage_preserves_absent_cursor():
    import os
    from datetime import UTC, date, datetime
    from urllib.parse import urlparse
    from uuid import uuid4
    from redis import Redis
    from app.market_data.observation_stream import ObservationStream
    from app.reference_trading.fenced_outage_recovery import FencedOutageAuthority
    url = os.getenv('GUIYI_ISOLATED_REDIS_URL')
    if not url:
        pytest.skip('GUIYI_ISOLATED_REDIS_URL is required')
    parsed = urlparse(url)
    assert parsed.scheme == 'redis' and parsed.hostname == '127.0.0.1' and parsed.port == 16389 and parsed.path == '/11' and not parsed.username and not parsed.password
    namespace = 'test:reference-outage:' + uuid4().hex + ':'
    class IsolatedStream(ObservationStream):
        def key(self, day):
            return namespace + super().key(day)
        def cursor_key(self, consumer, day):
            return namespace + super().cursor_key(consumer, day)
        def registration_key(self, consumer):
            return namespace + super().registration_key(consumer)
    client = Redis.from_url(url)
    journal = IsolatedStream(client, kind='completed')
    day, old = date(2026,10,13), date(2026,10,12)
    try:
        assert client.ping()
        journal.initialize('reference', old, cursor='0-0')
        _, _, identity, _, _, _, _ = _setup(frequency='60m')
        cutoff = datetime.now(UTC)-timedelta(seconds=5)
        endpoint = cutoff-timedelta(hours=1)
        planner = FencedOutageAuthority(journal,
            SimpleNamespace(expected_endpoints=lambda *args:(endpoint,), owner_segments=lambda *args:('owner','calc')),
            cutoff=cutoff, verify_fence=lambda:{'exact_test_fence':'parked'}, contract_for_day=lambda *args:'RB2610')
        before = set(client.scan_iter(match=namespace+'*'))
        proof, missing = planner.freeze(identity, None, day=day, expected_cursor=None)
        assert planner.verify_gap(identity, None, proof) == missing
        assert journal.registered_day('reference') == old
        assert not client.exists(journal.key(day)) and not client.exists(journal.cursor_key('reference',day))
        assert set(client.scan_iter(match=namespace+'*')) == before
    finally:
        keys = list(client.scan_iter(match=namespace+'*'))
        if keys:
            client.delete(*keys)
        client.close()
