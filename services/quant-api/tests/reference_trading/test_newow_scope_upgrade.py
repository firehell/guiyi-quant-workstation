from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.notifications.newow import NewowNotificationPolicy, NewowNotificationDelivery
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceActivationReceipt, ReferenceBatch, ReferenceActionRow, ReferenceTradeRow
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap, _hash
from app.reference_trading import newow_scope_upgrade as upgrade
from app.reference_trading.repository import RepositoryConflict
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from tests.reference_trading.test_newow_bootstrap import setup_source, NOW, START, plan_for


def fixture(monkeypatch, engine=None, *, frequency="1d", add_policy=True, freeze=True):
    factory, repo, identity, revision, checkpoint = setup_source(engine, frequency=frequency)
    with factory() as session:
        engine = session.get_bind()
    Base.metadata.create_all(engine, tables=[NewowNotificationPolicy.__table__, NewowNotificationDelivery.__table__])
    old = replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION,
                  observation_policy_version='completed_observation_v1', profile_id='old-profile')
    stored = repo.ensure_stream(old)
    manifest = {'old': 'preserve'}
    oldrevision = repo.create_revision(old.stream_id, stored.row_version, manifest_sha256(manifest))
    from guiyi_quant.reference_trading import ReferenceTrade
    trade = ReferenceTrade('old-open', old, 'LONG', 'RB2610', 'owner', 'calc',
        'old-build', START, START.date(), Decimal('3500'))
    seed = replace(checkpoint, stream=old, reference_state=ReferenceState.flat(old, recording_start=START))
    repo.stage_seed_chunk(oldrevision, SeedChunk('old-seed', 0, 1, sha256(b'old').hexdigest(), 'old'))
    repo.seal_seed(oldrevision, manifest, seed, 'newow_product_replay_v1')
    activation = ForwardActivation(factory)
    plan = activation.plan(old.stream_id, oldrevision, host='isolated-host', environment='isolated',
        recording_start=START, expires_at=START, budget={'max_pending_keys': 360, 'max_units_per_round': 32})
    activation.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
    with factory.begin() as session:
        # Persist an already activated old OPEN checkpoint as the upgrade preimage.
        old_revision = session.get(ReferenceRevision, (old.stream_id, oldrevision))
        batch = session.get(ReferenceBatch, old_revision.checkpoint_batch_id)
        batch.checkpoint_text = adapter_checkpoint_to_json(replace(seed,
            reference_state=ReferenceState(old, recording_start=START, open_trade=trade)),
            strategy_schema='newow_product_replay_v1')
        batch.post_state_hash = sha256(batch.checkpoint_text.encode()).hexdigest()
        action_pk = sha256(old.stream_id.encode()).hexdigest()
        session.add(ReferenceActionRow(action_pk=action_pk, stream_id=old.stream_id,
            origin_revision_id=oldrevision, batch_revision_id=oldrevision,
            source_action_id='old-build', recording_mode='forward_observation', kind='OPEN_LONG',
            sequence=0, physical_contract='RB2610', owner_segment_id='owner', calculation_segment_id='calc',
            bar_end=START, trading_day=START.date(), observed_at=START, reference_price=Decimal('3500'),
            reference_price_type='close', batch_id=batch.batch_id, batch_seq=batch.seq))
        session.flush()
        session.add(ReferenceTradeRow(stream_id=old.stream_id, revision_id=oldrevision,
            trade_id='old-open', valid_from_seq=batch.seq, entry_action_pk=action_pk,
            side='LONG', status='OPEN', physical_contract='RB2610', owner_segment_id='owner',
            calculation_segment_id='calc', entry_bar_end=START, entry_trading_day=START.date(),
            entry_reference_price=Decimal('3500'), holding_bars=0, effective_bar_end=START, observed_at=START))
        if add_policy:
            session.add(NewowNotificationDelivery(delivery_id='old-delivery', stream_id=old.stream_id,
                signal_id='old-build', batch_id=batch.batch_id, topic_hash='t' * 64,
                status='ATTEMPTED_UNKNOWN', attempted_at=NOW, finished_at=None))
            session.add(NewowNotificationPolicy(policy_id='newow_actions_v1', enabled=True,
            enabled_at=NOW, topic_hash='t' * 64, products=['rb'], cursor_at=NOW, cursor_batch_id='prior'))
    # Fixtures intentionally reduce cardinality; public production configuration stays 60x12.
    monkeypatch.setattr(upgrade, 'SCOPE_COUNT', 1)
    monkeypatch.setattr(upgrade, 'PRODUCT_COUNT', 1)
    monkeypatch.setattr(upgrade, 'FREQUENCIES', (frequency,))
    monkeypatch.setattr(upgrade, 'STRATEGIES', ('trend',))
    monkeypatch.setattr(upgrade, 'validate_product_scope', lambda a, b: tuple(a))
    newplan = plan_for(NewowForwardBootstrap(factory), identity)
    scope = {'expected_count': 1, 'frequencies': [frequency], 'products': ['rb'], 'plan_hash': 'scope',
             'items': [{'product': 'rb', 'strategy': 'trend', 'frequency': frequency, 'status': 'ready', 'plan': newplan}]}
    service = upgrade.NewowForwardScopeUpgrade(factory)
    if not freeze:
        return factory, repo, service, scope, old, newplan
    with factory() as session:
        plan = service._freeze(session, scope)
    return factory, repo, service, plan, old, newplan


def test_atomic_switch_preserves_old_facts_policy_and_new_flat(monkeypatch):
    factory, repo, service, plan, old, newplan = fixture(monkeypatch)
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW, clock=lambda: NOW)
    assert result['disabled_count'] == result['activated_count'] == 1
    with factory() as session:
        assert not session.get(ReferenceStream, old.stream_id).enabled
        assert session.get(ReferenceStream, newplan['target_stream_id']).enabled
        assert upgrade._facts(session, [old.stream_id]) == plan['protected_facts']
    _, oldstate = repo.load_checkpoint(old.stream_id)
    assert oldstate.reference_state.open_trade.reference_trade_id == 'old-open'
    _, state = repo.load_checkpoint(newplan['target_stream_id'])
    assert state.reference_state == ReferenceState.flat(state.stream, recording_start=START)
    with pytest.raises(RepositoryConflict, match='UPGRADE_OLD_SCOPE_DRIFT'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW, clock=lambda: NOW)


def test_mid_switch_failure_rolls_back_old_disable_and_new_seed(monkeypatch):
    factory, _, service, plan, old, newplan = fixture(monkeypatch)
    def fail(*args, **kwargs):
        raise RepositoryConflict('injected_after_old_disabled')
    monkeypatch.setattr(NewowForwardBootstrap, 'apply', fail)
    with pytest.raises(RepositoryConflict, match='injected_after_old_disabled'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW, clock=lambda: NOW)
    with factory() as session:
        assert session.get(ReferenceStream, old.stream_id).enabled
        assert session.get(ReferenceStream, old.stream_id).activation_generation == 1
        assert session.get(ReferenceStream, newplan['target_stream_id']) is None
        receipt = session.scalar(select(ReferenceActivationReceipt).where(ReferenceActivationReceipt.stream_id == old.stream_id))
        assert receipt.disabled_at is None


@pytest.mark.parametrize('drift', ['row', 'source', 'policy', 'route', 'expired', 'tamper'])
def test_drift_fails_closed_and_preserves_old(monkeypatch, drift):
    factory, _, service, plan, old, newplan = fixture(monkeypatch)
    now = NOW
    if drift in {'row', 'source', 'policy'}:
        with factory.begin() as session:
            if drift == 'row':
                session.get(ReferenceStream, old.stream_id).row_version += 1
            elif drift == 'source':
                session.get(ReferenceRevision, (newplan['source']['stream_id'], newplan['source']['revision_id'])).last_seq += 1
            else:
                session.get(NewowNotificationPolicy, 'newow_actions_v1').cursor_batch_id = 'drift'
    elif drift == 'route':
        plan['mapping'][0]['new']['frequency'] = '60m'
        plan['plan_hash'] = _hash({k: v for k, v in plan.items() if k != 'plan_hash'})
    elif drift == 'expired':
        now = START + timedelta(seconds=1)
    else:
        plan['expected_count'] += 1
    with pytest.raises(RepositoryConflict):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=now, clock=lambda: now)
    with factory() as session:
        assert session.get(ReferenceStream, old.stream_id).enabled
        assert session.get(ReferenceStream, newplan['target_stream_id']) is None


def multi_fixture(monkeypatch, engine=None):
    first = fixture(monkeypatch, engine, freeze=False)
    factory, repo, service, scope1, old1, new1 = first
    with factory() as session:
        engine = session.get_bind()
    second = fixture(monkeypatch, engine, frequency='60m', add_policy=False, freeze=False)
    _, _, _, scope2, old2, new2 = second
    monkeypatch.setattr(upgrade, 'SCOPE_COUNT', 2)
    monkeypatch.setattr(upgrade, 'FREQUENCIES', ('1d', '60m'))
    scope = {**scope1, 'expected_count': 2, 'frequencies': ['1d', '60m'],
             'items': scope1['items'] + scope2['items']}
    with factory() as session:
        plan = service._freeze(session, scope)
    return factory, repo, service, plan, (old1, old2), (new1, new2)


def assert_second_failure_rolls_back(monkeypatch, engine=None):
    factory, _, service, plan, old, new = multi_fixture(monkeypatch, engine)
    original = NewowForwardBootstrap.apply
    calls = []
    def fail_second(self, *args, **kwargs):
        calls.append(args[0]['target_stream_id'])
        if len(calls) == 2:
            raise RepositoryConflict('second_after_first_seed_committed_savepoint')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(NewowForwardBootstrap, 'apply', fail_second)
    with pytest.raises(RepositoryConflict, match='second_after_first'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW, clock=lambda: NOW)
    assert len(calls) == 2
    with factory() as session:
        for identity in old:
            assert session.get(ReferenceStream, identity.stream_id).enabled
            assert session.get(ReferenceStream, identity.stream_id).activation_generation == 1
            receipt = session.scalar(select(ReferenceActivationReceipt).where(ReferenceActivationReceipt.stream_id == identity.stream_id))
            assert receipt.disabled_at is None
        for newplan in new:
            assert session.get(ReferenceStream, newplan['target_stream_id']) is None
            assert not session.scalars(select(ReferenceRevision).where(ReferenceRevision.stream_id == newplan['target_stream_id'])).all()
            assert not session.scalars(select(ReferenceBatch).where(ReferenceBatch.stream_id == newplan['target_stream_id'])).all()
            assert not session.scalars(select(ReferenceActivationReceipt).where(ReferenceActivationReceipt.stream_id == newplan['target_stream_id'])).all()
        assert upgrade._facts(session, [x.stream_id for x in old]) == plan['protected_facts']


def test_second_route_failure_rolls_back_first_committed_savepoint(monkeypatch):
    assert_second_failure_rolls_back(monkeypatch)


def test_clock_crossing_deadline_rolls_back_completed_new_seed(monkeypatch):
    factory, _, service, plan, old, newplan = fixture(monkeypatch)
    observations = iter((NOW, START))
    with pytest.raises(RepositoryConflict, match='PLAN_EXPIRED_OR_START_IN_PAST'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW, clock=lambda: next(observations))
    with factory() as session:
        assert session.get(ReferenceStream, old.stream_id).enabled
        assert session.get(ReferenceStream, newplan['target_stream_id']) is None
