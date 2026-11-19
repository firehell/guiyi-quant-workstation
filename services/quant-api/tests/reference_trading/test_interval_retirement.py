"""Full-size retirement is an operator boundary, not historical calculation."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json

import pytest
from sqlalchemy import select, func

from app.reference_trading import interval_retirement as module
from app.reference_trading.inbox import ReferenceInboxRepository, InboxConflict
from app.reference_trading.inbox_recovery import verified_resolution_ids
from app.reference_trading.models import (
    ReferenceStream, ReferenceRevision, ReferenceBatch, ReferenceInboxDelivery,
    ReferenceInboxInput, ReferenceTradeRow,
)
from app.reference_trading.repository import _aware
from app.reference_trading.recording_scope import H1_INTERVAL_POLICY
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict, _identity_from_row
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
from tests.reference_trading import test_formula_transition as source_fixtures
from tests.reference_trading.test_inbox import event

source_fixture = source_fixtures.fixture
transition_engine = source_fixtures.transition_engine

NOW = datetime.now(UTC).replace(microsecond=0)
CUT = NOW + timedelta(hours=1)
PRODUCTS = ('a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jm l lc lh m ma ni oi p '
            'pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sm sn sr ss ta ur v y zn').split()


def scenario(engine, monkeypatch):
    ids, expected_open = [], 0
    for index, product in enumerate(PRODUCTS):
        opened = set()
        if index >= 46:
            offset = index - 46
            opened = {code for code, count in [('trend', 9), ('main_rise', 8),
                      ('oscillation', 7), ('dual_fusion', 11)] if offset < count}
        factory, pairs = source_fixture(engine, current=True, product=product, opened_codes=opened)
        ids.extend(p[0] for p in pairs)
        expected_open += len(opened)
        if index < 46:
            with factory.begin() as db:
                for sid, _ in pairs:
                    row = db.get(ReferenceStream, sid)
                    rev = db.get(ReferenceRevision, (sid, row.active_revision_id))
                    batch = db.get(ReferenceBatch, rev.checkpoint_batch_id)
                    identity = _identity_from_row(row)
                    cp = AdapterCheckpoint(module._empty(identity), stream=identity,
                        reference_state=ReferenceState.flat(identity, recording_start=_aware(row.recording_start)))
                    raw = adapter_checkpoint_to_json(cp, strategy_schema=batch.strategy_schema)
                    batch.checkpoint_text = raw
                    batch.post_state_hash = sha256(raw.encode()).hexdigest()
                    batch.computed_through = None
                    batch.kind = 'seed_seal'
    assert len(ids) == 236 and expected_open == 35
    inbox = ReferenceInboxRepository(factory)
    for index, product in enumerate(PRODUCTS):
        original = event(f'{index+100}-0', end=NOW - timedelta(minutes=5))
        original = replace(original, channel=f'live:bar:{product}:60m',
                           data={**original.data, 'contract': product.upper()+'2701'})
        receipt = inbox.ingest(original, ingested_at=NOW - timedelta(minutes=4))
        assert len(receipt.delivery_ids) == 4
        for identifier in receipt.delivery_ids:
            inbox.mark_blocked(identifier, 'OBSERVATION_GAP', at=NOW - timedelta(minutes=3))
    inventory = dict(kind='READ_ONLY_INVENTORY_NOT_EXECUTION_PLAN', affected_scope=[])
    with factory() as db:
        for sid in ids:
            row = db.get(ReferenceStream, sid)
            rev = db.get(ReferenceRevision, (sid, row.active_revision_id))
            batch = db.get(ReferenceBatch, rev.checkpoint_batch_id)
            inventory['affected_scope'].append(dict(stream_id=sid, product=row.product,
                frequency='60m', revision=rev.revision_id, generation=row.activation_generation,
                row_version=row.row_version, checkpoint_id=batch.batch_id,
                checkpoint_sha256=sha256(batch.checkpoint_text.encode()).hexdigest()))
    raw = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    monkeypatch.setattr(module, 'INVENTORY_SHA256', sha256(raw).hexdigest())

    def first(db, product, cut):
        return dict(product=product, bar_end=(cut + timedelta(hours=len(product) % 2)).isoformat(),
                    trading_day=str(cut.date()), metadata_sha256='c'*64)

    service = module.NewowIntervalRetirement(factory, inventory=inventory,
        first_endpoint=first, assert_fenced=lambda: None, clock=lambda: NOW)
    return factory, service, ids


def plan_for(service, ids):
    return service.plan(ids, recording_start=CUT, expires_at=NOW+timedelta(minutes=30), now=NOW)


def test_full_atomic_retirement_preserves_originals_and_real_market_progress(transition_engine, monkeypatch):
    factory, service, ids = scenario(transition_engine, monkeypatch)
    repo = ReferenceRepository(factory)
    with factory() as db:
        before = {q.delivery_id: module._row(q) for q in db.scalars(select(ReferenceInboxDelivery))}
        originals = {q.input_id: module._row(q) for q in db.scalars(select(ReferenceInboxInput))}
    plan = plan_for(service, ids)
    assert len({i['bootstrap']['expected_first_bar_end'] for i in plan['items']}) == 2
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    assert result['status'] == 'COMMITTED' and len(result['retired']) == 236
    assert service.status(plan) == result
    assert service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW) == result
    with factory() as db:
        assert {q.delivery_id: module._row(q) for q in db.scalars(select(ReferenceInboxDelivery))} == before
        assert {q.input_id: module._row(q) for q in db.scalars(select(ReferenceInboxInput))} == originals
        retired = verified_resolution_ids(db)
        assert set(retired) == set(before)
        appended = db.scalars(select(ReferenceTradeRow).where(
            ReferenceTradeRow.status == 'OBSERVATION_INTERRUPTED')).all()
        assert len(appended) == 35
        assert all(q.entry_reference_price == 100 and q.exit_reference_price is None
                   and q.reference_return is None and q.exit_action_pk is None for q in appended)
        terminals = db.scalars(select(ReferenceBatch).where(
            ReferenceBatch.batch_key.like(module.PREFIX+'%'))).all()
        assert len(terminals) == 236
        assert all(q.computed_through is None and q.observed_at is None for q in terminals)
        assert db.scalar(select(func.count()).select_from(ReferenceStream).where(
            ReferenceStream.enabled.is_(True))) == 236
    for item in plan['items'][:4]:
        target = item['bootstrap']['target_stream_id']
        cp = repo.load_checkpoint(target)[1]
        assert cp.computed_through is None and cp.last_fingerprint is None
        assert cp.physical_contract is None and cp.reference_state.open_trade is None
        assert cp.stream.observation_policy_version == H1_INTERVAL_POLICY
    assert ReferenceInboxRepository(factory).next_heads() == ()
    health = ReferenceInboxRepository(factory).health()
    assert health['unfinished_current_generation_deliveries'] == 0
    assert health['unfinished_deliveries'] == 0
    assert health['recovered_calculation_count'] == 0
    assert health['retired_interval_delivery_count'] == 236


@pytest.mark.parametrize('missing_first', [False, True])
def test_new_policy_consumes_only_exact_first_original_and_naturally_warms(
        transition_engine, monkeypatch, missing_first):
    from app.reference_trading.composition import build_forward_reference_worker
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources
    factory, service, ids = scenario(transition_engine, monkeypatch)
    plan = plan_for(service, ids)
    service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    repo = ReferenceRepository(factory)
    inbox = ReferenceInboxRepository(factory)
    targets = [i['bootstrap']['target_stream_id'] for i in plan['items']
               if i['old']['stream']['product'] == 'rb']
    with factory() as db:
        targets.sort(key=lambda sid: db.get(ReferenceStream, sid).strategy_code == 'newow_dual_fusion')

    def expected(_, contract, day, after, cutoff):
        return tuple(e for e in (CUT, CUT+timedelta(hours=1)) if after < e <= cutoff)

    worker = build_forward_reference_worker(repository=repo, market_read=None, newow_reader=None,
        owner_segments=lambda *args: ('owner', 'calc'), expected_endpoints=expected,
        newow_capability_ready=lambda _: True, fusion_sources=SavedForwardFusionSources(factory),
        enabled=True, now=lambda: CUT+timedelta(hours=2))
    for index, end in enumerate(([CUT+timedelta(hours=1)] if missing_first else
                                [CUT, CUT+timedelta(hours=1)]), start=1000):
        original = replace(event(f'{index}-0', end=end), channel='live:bar:rb:60m',
                           data={**event(f'{index}-0', end=end).data, 'contract':'RB2701'})
        ingested = original.confirmed_at+timedelta(seconds=1)
        assert len(inbox.ingest(original, ingested_at=ingested).delivery_ids) == 4
        worker.source_envelope = original
        worker.source_observed_at = original.confirmed_at
        worker.raw_received_at = original.raw_received_at
        worker.inbox_ingested_at = ingested
        for sid in targets:
            head = inbox.pending_head(sid)
            if missing_first:
                from app.reference_trading.forward_inputs import ForwardInputUnavailable
                with pytest.raises(ForwardInputUnavailable, match='OBSERVATION_GAP'):
                    worker.process_inbox_delivery(sid, end, delivery_id=head.delivery_id)
                assert repo.load_checkpoint(sid)[1].computed_through is None
                with factory() as db:
                    assert db.get(ReferenceInboxDelivery, head.delivery_id).status == 'PENDING'
                continue
            worker.process_inbox_delivery(sid, end, delivery_id=head.delivery_id)
            cp = repo.load_checkpoint(sid)[1]
            assert cp.reference_state.open_trade is None
            assert cp.computed_through == end
            assert inbox.pending_head(sid) is None


def test_mid_transaction_failure_rolls_back_all_236(transition_engine, monkeypatch):
    factory, service, ids = scenario(transition_engine, monkeypatch)
    plan = plan_for(service, ids)
    original = service._activate_target
    calls = []

    def fail(factory, bootstrap, at):
        calls.append(bootstrap)
        if len(calls) == 121:
            raise RepositoryConflict('TEST_MID_TRANSACTION_FAILURE')
        return original(factory, bootstrap, at)

    monkeypatch.setattr(service, '_activate_target', fail)
    with pytest.raises(RepositoryConflict, match='TEST_MID_TRANSACTION_FAILURE'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    assert service.status(plan) is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ReferenceStream).where(
            ReferenceStream.observation_policy_version == H1_INTERVAL_POLICY)) == 0
        assert all(db.get(ReferenceStream, sid).enabled for sid in ids)
        assert db.scalar(select(func.count()).select_from(ReferenceTradeRow).where(
            ReferenceTradeRow.status == 'OPEN', ReferenceTradeRow.valid_to_seq.is_(None))) == 35


@pytest.mark.parametrize('change', ['unknown', 'input', 'metadata'])
def test_changed_source_or_unknown_blocks_before_mutation(transition_engine, monkeypatch, change):
    factory, service, ids = scenario(transition_engine, monkeypatch)
    plan = plan_for(service, ids)
    if change == 'metadata':
        first = service.first_endpoint
        monkeypatch.setattr(service, 'first_endpoint', lambda *a: {**first(*a), 'metadata_sha256':'d'*64})
    else:
        with factory.begin() as db:
            if change == 'unknown':
                row = db.scalar(select(ReferenceInboxDelivery))
                row.status, row.unknown_at = 'UNKNOWN', NOW
            else:
                row = db.scalar(select(ReferenceInboxInput))
                row.canonical_envelope += ' '
    with pytest.raises((RepositoryConflict, InboxConflict, ValueError), match='INTERVAL|INBOX|PREIMAGE'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    assert service.status(plan) is None


@pytest.mark.parametrize('change', ['original', 'trade', 'seed'])
def test_retirement_reader_rejects_corrupt_evidence(transition_engine, monkeypatch, change):
    factory, service, ids = scenario(transition_engine, monkeypatch)
    plan = plan_for(service, ids)
    service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    with factory.begin() as db:
        if change == 'original':
            db.scalar(select(ReferenceInboxInput)).canonical_envelope += ' '
        elif change == 'trade':
            db.scalar(select(ReferenceTradeRow).where(ReferenceTradeRow.status=='OPEN')).entry_reference_price = 999
        else:
            seed = db.scalar(select(ReferenceBatch).join(ReferenceStream,
                ReferenceStream.stream_id==ReferenceBatch.stream_id).where(
                ReferenceStream.observation_policy_version==H1_INTERVAL_POLICY,
                ReferenceBatch.kind=='seed_seal'))
            seed.checkpoint_text += ' '
    with factory() as db, pytest.raises((RepositoryConflict, InboxConflict, ValueError)):
        verified_resolution_ids(db)


def test_wall_clock_expiry_after_work_rolls_back(monkeypatch):
    from sqlalchemy import create_engine
    engine = create_engine('sqlite+pysqlite:///:memory:')
    try:
        factory, service, ids = scenario(engine, monkeypatch)
        plan = plan_for(service, ids)
        monkeypatch.setattr(service, 'clock', lambda: CUT+timedelta(seconds=1))
        with pytest.raises(RepositoryConflict, match='EXPIRED_DURING_COMMIT'):
            service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
        assert service.status(plan) is None
    finally:
        engine.dispose()


def test_maintenance_lease_requires_its_real_backend_lock(transition_engine, tmp_path):
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.market_data.catalog import MarketCatalog, _MAINTENANCE_LOCK_KEY
    with Session(transition_engine) as db:
        lease = MarketCatalog(db, tmp_path).acquire_maintenance_lock(caller='interval-retirement-test')
        assert lease is not None
        try:
            lease.assert_held()
            if transition_engine.dialect.name == 'postgresql':
                assert lease._connection.scalar(text('SELECT pg_advisory_unlock(:key)'),
                    {'key':_MAINTENANCE_LOCK_KEY}) is True
                with pytest.raises(RuntimeError, match='MAINTENANCE_LEASE_LOST'):
                    lease.assert_held()
                with pytest.raises(RuntimeError, match='MAINTENANCE_LEASE_RELEASE_UNVERIFIED'):
                    lease.release()
            else:
                lease.release()
        finally:
            lease.release()
