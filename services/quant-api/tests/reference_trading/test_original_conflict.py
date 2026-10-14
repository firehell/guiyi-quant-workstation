from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, func, select

from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.health import ForwardReferenceHealth
from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation, ReferenceRevision
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
from app.reference_trading.original_conflict import (
    CONFLICT, TERMINAL, VERSION, OriginalObservationTransfer, OriginalObservationRevisionRecovery,
    numeric_diff, original_conflict_evidence,
)
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_newow_bootstrap import setup_source, plan_for, NOW, START


def setup_group(engine=None):
    engine = engine or create_engine('sqlite+pysqlite:///:memory:')
    sources, targets = [], []
    for strategy in ('trend', 'oscillation', 'main_rise'):
        factory, repo, identity, _, checkpoint = setup_source(engine, strategy=strategy, frequency='60m')
        sources.append(identity.stream_id)
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity, FusionReferenceReplayState
    from guiyi_quant.reference_trading import ReferenceState
    from app.market_data.newow.product_release import candidate_input_quality_policy
    fusion = build_fusion_stream_identity('rb', '60m', input_quality_policy=candidate_input_quality_policy('rb', '60m', candidate_weekly=False))
    row = repo.ensure_stream(fusion)
    manifest = {'source': 'fusion-fixture'}
    revision = repo.create_revision(fusion.stream_id, row.row_version, manifest_sha256(manifest))
    fusion_checkpoint = replace(checkpoint, stream=fusion, strategy_state=FusionReferenceReplayState(), reference_state=ReferenceState.flat(fusion))
    repo.stage_seed_chunk(revision, SeedChunk('seed', 0, 1, sha256(b'seed').hexdigest(), 'seed'))
    repo.seal_seed(revision, manifest, fusion_checkpoint, 'newow_dual_fusion_reference_v1')
    repo.publish_revision(fusion.stream_id, revision, row.row_version, manifest_sha256(manifest))
    sources.append(fusion.stream_id)
    bootstrap = NewowForwardBootstrap(factory)
    for source in sources:
        with factory() as session:
            identity = bootstrap._source(session, source)[0]
        plan = plan_for(bootstrap, identity)
        targets.append(bootstrap.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)['target_stream_id'])
    end = START + timedelta(minutes=1)
    raw = {'bar_end': end.isoformat(), 'trading_day': end.date().isoformat(), 'contract': 'RB2610',
        'open': '1', 'high': '2', 'low': '1', 'close': '1', 'volume': '10', 'turnover': '100', 'open_interest': '3'}
    observation = ObservationEnvelope('original', end.date(), end, 'live:bar:rb:60m', raw, True, '1-0', end, end + timedelta(seconds=2))
    return factory, repo, tuple(sources), tuple(targets), observation


def proof(observation):
    original = {k: v for k, v in observation.data.items() if k != 'contract'}
    canonical = {**original, 'volume': '11' if observation.stream_id == '1-0' else original['volume']}
    source = {'partitions': [{'content_sha256': 'a' * 64, 'quality_sha256': 'b' * 64}]}
    differences = numeric_diff(original, canonical)
    return {'kind': CONFLICT if differences else 'ORIGINAL_OBSERVATION_CANONICAL_MATCH',
        'product': 'rb', 'frequency': '60m', 'contract': 'RB2610', 'owner_segment_id': 'owner',
        'calculation_segment_id': 'calc', 'bar_end': original['bar_end'], 'original_bar': original,
        'canonical_bar': canonical, 'differences': differences, 'canonical_source': source,
        'source_manifest_sha256': manifest_sha256(source), 'source_revision': 'canonical:' + manifest_sha256(source),
        'canonical_bar_sha256': manifest_sha256(canonical)}


def test_four_route_terminal_is_atomic_non_natural_and_health_conflicted(engine=None):
    factory, repo, sources, targets, original = setup_group(engine)
    matched = replace(original, stream_id='2-0')
    service = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    plan = service.plan(targets, (original, matched))
    ids = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))
    assert len(ids) == 8
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceCaptureReconciliation)) == 0
        assert session.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind == 'capture')) == 0
        evidence = original_conflict_evidence(session, targets)
        assert {r['evidence']['kind'] for r in evidence} == {CONFLICT, TERMINAL}
        assert all(session.get(ReferenceBatch, i).observed_at is None for i in ids)
    health = ForwardReferenceHealth(factory).read()['streams']
    assert len(health) == 4 and all(r['status'] == 'DATA_CONFLICT' and r['latest_state'] is None for r in health)
    with pytest.raises(RepositoryConflict, match='ATTEMPT_ALREADY_EXISTS'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=4))
    recovery = OriginalObservationRevisionRecovery(factory, verify_source=lambda *_: {'full': 'verified'},
        assert_fenced=lambda: None, verify_observation=proof)
    repair = recovery.plan(sources, recording_start=START + timedelta(minutes=10), expires_at=START + timedelta(minutes=9), now=START + timedelta(minutes=3))
    old = {route: repo.load_checkpoint(route)[0].revision_id for route in targets}
    result = recovery.apply(repair, expected_plan_hash=repair['plan_hash'], now=START + timedelta(minutes=4))
    assert set(result) == set(targets)
    for route in targets:
        token, checkpoint = repo.load_checkpoint(route)
        assert token.revision_id != old[route]
        assert checkpoint.reference_state.open_trade is None
        assert checkpoint.reference_state.recording_start == START + timedelta(minutes=10)
    assert all(r['status'] != 'DATA_CONFLICT' for r in ForwardReferenceHealth(factory).read()['streams'])
    with factory() as session:
        assert all(session.get(ReferenceBatch, i) is not None for i in ids)
        assert all(session.get(ReferenceRevision, (route, old[route])).invalid_reason == 'DATA_CONFLICT' for route in targets)


def test_fence_loss_rolls_back_every_typed_receipt(engine=None):
    factory, _, _, targets, original = setup_group(engine)
    service = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    plan = service.plan(targets, (original,))
    calls = []
    def fence():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('FENCE_LOST')
    service.assert_fenced = fence
    with pytest.raises(RuntimeError, match='FENCE_LOST'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))
    with factory() as session:
        assert not original_conflict_evidence(session, targets)


def test_unknown_commit_stops_with_durable_receipts(engine=None):
    from sqlalchemy.exc import OperationalError
    factory, _, _, targets, original = setup_group(engine)
    service = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    plan = service.plan(targets, (original,))
    # A failure after the real transaction commit is an unknown outcome.
    class CommitThenLost:
        def __init__(self): self.session = factory()
        def __enter__(self): return self
        def __exit__(self, *args): self.session.close()
        def __getattr__(self, key): return getattr(self.session, key)
        def begin(self):
            from contextlib import contextmanager
            @contextmanager
            def transaction():
                with self.session.begin():
                    yield
                raise OperationalError('isolated', {}, Exception('lost'))
            return transaction()
    service.factory = CommitThenLost
    with pytest.raises(RepositoryConflict, match='COMMIT_OUTCOME_UNKNOWN'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))
    with factory() as session:
        assert len(original_conflict_evidence(session, targets)) == 1


def test_partial_group_no_diff_and_drift_are_rejected():
    factory, _, _, targets, original = setup_group()
    service = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    with pytest.raises(RepositoryConflict, match='SCOPE_INVALID'):
        service.plan(targets[:3], (original,))
    with pytest.raises(RepositoryConflict, match='NUMERIC_MISMATCH_REQUIRED'):
        service.plan(targets, (replace(original, stream_id='2-0'),))
    plan = service.plan(targets, (original,))
    service.verify_observation = lambda o: {**proof(o), 'owner_segment_id': 'drift'}
    with pytest.raises(RepositoryConflict, match='PREIMAGE_DRIFT'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))


def test_decimal_scale_is_not_conflict_unknown_and_nan_rejected():
    raw = dict(bar_end='same', trading_day='same', open='1', high='2', low='1', close='1', volume='1', turnover=None, open_interest=None)
    assert numeric_diff(raw, {**raw, 'volume': '1.000'}) == {}
    for value in ('NaN', 'Infinity', None):
        with pytest.raises(RepositoryConflict):
            numeric_diff(raw, {**raw, 'volume': value})


def test_missing_whole_observation_receipts_and_corrupt_original_fail_closed():
    from sqlalchemy import delete
    factory, _, _, targets, original = setup_group()
    service = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    plan = service.plan(targets, (original, replace(original, stream_id='2-0')))
    service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))
    with factory() as session:
        records = original_conflict_evidence(session, targets)
        matched = next(r for r in records if r['evidence']['kind'] == TERMINAL)
        ids = matched['receipt_ids']
    with factory.begin() as session:
        session.execute(delete(ReferenceBatch).where(ReferenceBatch.batch_id.in_(ids)))
    with factory() as session, pytest.raises(RepositoryConflict, match='PARTIAL_TERMINAL_PROOF'):
        original_conflict_evidence(session, targets)


def test_current_worker_guard_rejects_typed_conflict_without_reconciliation_rows():
    from app.reference_trading.scheduled_reconciliation import ScheduledCanonicalReconciliation
    factory, _, _, targets, original = setup_group()
    transfer = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    plan = transfer.plan(targets, (original,))
    transfer.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))
    guard = object.__new__(ScheduledCanonicalReconciliation)
    guard._factory = factory
    with factory.begin() as session, pytest.raises(RepositoryConflict, match=CONFLICT):
        guard.commit_guard(session, targets[0])


def test_fresh_mds_verifier_checks_real_reader_endpoint_owner_quality_and_seal():
    from types import SimpleNamespace
    from app.market_data.domain import CanonicalBar
    from app.reference_trading.original_conflict import CanonicalObservationVerifier
    from decimal import Decimal
    _, _, _, _, original = setup_group()
    calls = []
    source = {'partitions': [{'content_sha256': 'a' * 64, 'quality_sha256': 'b' * 64,
        'coverage_end': original.data['bar_end']}]}
    bar = CanonicalBar(bar_end=original.source_observed_at, trading_day=original.trading_day,
        open=Decimal(1), high=Decimal(2), low=Decimal(1), close=Decimal(1), volume=Decimal(11),
        turnover=Decimal(100), open_interest=Decimal(3))
    class Market:
        def contract_source_evidence(self, **kwargs):
            calls.append(kwargs)
            return source
        def query_page_inclusive(self, request):
            assert request.contract == 'RB2610' and request.limit == 1
            return SimpleNamespace(bars=(bar,))
    verifier = CanonicalObservationVerifier(Market(), lambda *_: ('owner', 'calc'), assert_sealed=lambda o: calls.append(o.stream_id))
    actual = verifier(original)
    assert actual['kind'] == CONFLICT and actual['differences'] == {'volume': {'original': '10', 'canonical': '11'}}
    assert calls[0] == calls[-1] == '1-0'
    source['partitions'][0]['quality_sha256'] = None
    assert verifier(original)['kind'] == CONFLICT  # None is the valid no-exception quality metadata.
    source['partitions'][0]['content_sha256'] = None
    with pytest.raises(RepositoryConflict):
        verifier(original)


def test_typed_rows_keep_exact_original_and_never_become_capture_mismatch():
    from app.reference_trading.quarantine import mismatch_evidence
    factory, _, _, targets, original = setup_group()
    service = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    plan = service.plan(targets, (original,))
    ids = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(minutes=3))
    with factory() as session:
        assert mismatch_evidence(session, targets) == []
        row = session.get(ReferenceBatch, ids[0])
        assert row.source_evidence[VERSION]['item']['raw'] == original.to_json()


def materialized_group_loader(factory, *, stage='final_observation'):
    from tests.reference_trading.test_original_conflict_warm_seed import fixture, START as WARM_START
    from app.reference_trading.original_conflict_warm_seed import materialize_warm_seed, materialize_fusion_warm_seed
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
    seeds = []
    for strategy in ('trend', 'oscillation', 'main_rise'):
        baseline, snapshot, inputs, authority, _, _, _ = fixture(strategy)
        if stage == 'provisional_canonical':
            inputs = inputs[:1]
        seeds.append(materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=inputs,
            expected_endpoints=tuple(i.product_bar.bar.bar_end for i in inputs), recording_start=WARM_START,
            cutoff=inputs[-1].product_bar.bar.bar_end, verify_authority=authority, stage=stage))
    fusion = build_fusion_stream_identity('rb', '60m')
    with factory() as session:
        original = NewowForwardBootstrap(factory)._source(session, fusion.stream_id)[4]
    seeds.append(materialize_fusion_warm_seed(fusion, tuple(seeds), original_binding=original, recording_start=WARM_START))
    mapping = {s.identity.stream_id: s for s in seeds}
    return lambda session, source_id, **kwargs: mapping[source_id]


def test_two_stage_pending_boundary_requires_pristine_current_revision(engine=None):
    import json
    from app.reference_trading.original_conflict import PendingOriginalObservationRecovery, FinalizeOriginalObservationWarmup
    from tests.reference_trading.test_original_conflict_warm_seed import START as WARM_START, AT
    factory, repo, sources, targets, original = setup_group(engine)
    transfer = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    p = transfer.plan(targets, (original,))
    transfer.apply(p, expected_plan_hash=p['plan_hash'], now=START + timedelta(minutes=2))
    args = dict(verify_source=lambda *_: {'full': 'verified'}, assert_fenced=lambda: None, verify_observation=proof)
    pending = PendingOriginalObservationRecovery(factory, **args,
        source_loader=materialized_group_loader(factory, stage='provisional_canonical'))
    p = pending.plan(sources, recording_start=WARM_START, expires_at=WARM_START, now=AT + timedelta(minutes=3))
    initial = pending.apply(json.loads(json.dumps(p)), expected_plan_hash=p['plan_hash'], now=AT + timedelta(minutes=4))
    assert all(r['status'] == 'PENDING_WARMUP' and r['latest_state'] is None for r in ForwardReferenceHealth(factory).read()['streams'])
    with factory() as session:
        assert original_conflict_evidence(session, targets) == []
    final = FinalizeOriginalObservationWarmup(factory, **args, source_loader=materialized_group_loader(factory))
    with pytest.raises(RepositoryConflict, match='WARM_SEED_START_MISMATCH'):
        final.plan(sources, recording_start=WARM_START + timedelta(hours=1), expires_at=WARM_START,
            now=AT + timedelta(minutes=5))
    p = final.plan(sources, recording_start=WARM_START, expires_at=WARM_START, now=AT + timedelta(minutes=5))
    result = final.apply(json.loads(json.dumps(p)), expected_plan_hash=p['plan_hash'], now=AT + timedelta(minutes=6))
    assert all(result[r] != initial[r] for r in targets)
    assert all(r['status'] != 'PENDING_WARMUP' for r in ForwardReferenceHealth(factory).read()['streams'])
    with factory() as session:
        assert all(session.get(ReferenceRevision, (r, initial[r])).invalid_reason == 'WARMUP_COMPLETED' for r in targets)
    for route in targets:
        assert repo.load_checkpoint(route)[1].reference_state.open_trade is None
    with pytest.raises(RepositoryConflict, match='PENDING_WARMUP_REQUIRED'):
        final.plan(sources, recording_start=WARM_START, expires_at=WARM_START, now=AT + timedelta(minutes=7))


def test_final_loader_required_and_provisional_cannot_be_ready():
    from app.reference_trading.original_conflict import FinalizeOriginalObservationWarmup
    factory, _, sources, _, _ = setup_group()
    args = dict(verify_source=lambda *_: {'full': 'verified'}, assert_fenced=lambda: None, verify_observation=proof)
    with factory() as session:
        with pytest.raises(RepositoryConflict, match='FINAL_WARM_LOADER_REQUIRED'):
            FinalizeOriginalObservationWarmup(factory, **args)._source(session, sources[0], lock=False)
        for cls in (FinalizeOriginalObservationWarmup, OriginalObservationRevisionRecovery):
            service = cls(factory, **args, source_loader=materialized_group_loader(factory, stage='provisional_canonical'))
            for source in sources:
                with pytest.raises(RepositoryConflict, match='WARM_SEED_STAGE_INVALID'):
                    service._source(session, source, lock=False)


def test_pending_finalization_rejects_any_new_capture():
    from app.reference_trading.original_conflict import PendingOriginalObservationRecovery, FinalizeOriginalObservationWarmup
    from app.reference_trading.capture import ForwardCapture
    factory, repo, sources, targets, original = setup_group()
    transfer = OriginalObservationTransfer(factory, verify_observation=proof, assert_fenced=lambda: None)
    p = transfer.plan(targets, (original,))
    transfer.apply(p, expected_plan_hash=p['plan_hash'], now=START + timedelta(minutes=2))
    args = dict(verify_source=lambda *_: {'full': 'verified'}, assert_fenced=lambda: None, verify_observation=proof)
    pending = PendingOriginalObservationRecovery(factory, **args)
    start = START + timedelta(minutes=20)
    p = pending.plan(sources, recording_start=start, expires_at=start, now=START + timedelta(minutes=3))
    revisions = pending.apply(p, expected_plan_hash=p['plan_hash'], now=START + timedelta(minutes=4))
    from app.reference_trading.models import ReferenceStream
    with factory() as session:
        stream = session.get(ReferenceStream, targets[0])
        generation = stream.activation_generation
    repo.capture_forward(ForwardCapture(targets[0], revisions[targets[0]], generation, 'unexpected', start,
        start + timedelta(seconds=1), 'completed_live', {'close': '1'}, {'source_sha256': 'a' * 64}, 'first_seen'))
    with pytest.raises(RepositoryConflict, match='PENDING_WARMUP_HAS_OBSERVATIONS'):
        with factory() as session:
            FinalizeOriginalObservationWarmup(factory, **args)._conflicts(session, targets)
