from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceActivationReceipt
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from guiyi_quant.newow.product_adapters import build_product_identity, seed_replay_state, replay_step
from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
from guiyi_quant.reference_trading import StreamIdentity, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap

NOW = datetime(2026, 10, 8, 8, tzinfo=UTC)
START = NOW + timedelta(minutes=10)


def setup_source(engine=None, *, strategy="trend", frequency="1d"):
    engine = engine or create_engine('sqlite+pysqlite:///:memory:')
    from app.reference_trading.models import REFERENCE_TABLES, FORWARD_REFERENCE_TABLES
    tables = [Base.metadata.tables[name] for name in REFERENCE_TABLES | FORWARD_REFERENCE_TABLES]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    from app.market_data.newow.product_release import candidate_input_quality_policy
    policy = candidate_input_quality_policy('rb', frequency, candidate_weekly=False)
    product = build_product_identity('rb', strategy, frequency, input_quality_policy=policy)
    identity = StreamIdentity(strategy_code='newow_' + strategy, formula_versions=product.formula_versions,
        profile_id=product.profile_id, reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version(frequency, policy), product='rb', frequency=frequency,
        series_kind='actual_dominant', recording_mode='historical_replay', observation_policy_version=None)
    stored = repo.ensure_stream(identity)
    manifest = {'source': 'verified-historical-fixture'}
    if frequency == '1d':
        from app.reference_trading.inputs import NEWOW_D1_REFERENCE_BOUNDARY_POLICY
        manifest['reference_boundary_policy_version'] = NEWOW_D1_REFERENCE_BOUNDARY_POLICY
    revision = repo.create_revision(identity.stream_id, stored.row_version, manifest_sha256(manifest))
    from guiyi_quant.newow.models import NewowDailyBar
    from guiyi_quant.newow.product_contracts import ProductBar
    bar = NewowDailyBar('rb', 'RB2610', 'owner', (NOW - timedelta(days=1)).date(),
        NOW - timedelta(days=1), Decimal('3500'), Decimal('3510'), Decimal('3490'),
        Decimal('3505'), 100, None, 'verified-fixture', True, True)
    state, _, _ = replay_step(product, seed_replay_state(), ProductBar(bar, frequency, calculation_segment_id='calc', source_bar_sha256='b' * 64))
    checkpoint = AdapterCheckpoint(state, NOW - timedelta(days=1), 'a' * 64,
        'RB2610', 'owner', 'calc', identity, ReferenceState.flat(identity))
    repo.stage_seed_chunk(revision, SeedChunk('seed', 0, 1, sha256(b'seed').hexdigest(), 'seed'))
    repo.seal_seed(revision, manifest, checkpoint, 'newow_product_replay_v1')
    repo.publish_revision(identity.stream_id, revision, stored.row_version, manifest_sha256(manifest))
    return factory, repo, identity, revision, checkpoint


def plan_for(service, identity):
    return service.plan(identity.stream_id, recording_start=START, expires_at=START,
        host='isolated-host', environment='isolated', now=NOW)


def test_bootstrap_plan_is_readonly_apply_preserves_warm_strategy_and_resets_reference():
    factory, repo, identity, revision, source = setup_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceStream)) == 1
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    _, checkpoint = repo.load_checkpoint(result['target_stream_id'])
    assert checkpoint.strategy_state == source.strategy_state
    assert checkpoint.computed_through == source.computed_through
    assert checkpoint.stream.recording_mode.value == 'forward_observation'
    assert checkpoint.stream.observation_policy_version == 'completed_observation_v1'
    assert checkpoint.reference_state == ReferenceState.flat(checkpoint.stream, recording_start=START)
    assert service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(days=1)) == result
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceActivationReceipt)) == 1


def test_source_drift_blocks_before_creating_forward_stream():
    factory, _, identity, revision, _ = setup_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    with factory.begin() as session:
        session.get(ReferenceRevision, (identity.stream_id, revision)).last_seq += 1
    with pytest.raises(RepositoryConflict, match='BOOTSTRAP_SOURCE_DRIFT'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceStream)) == 1


def test_bootstrap_rejects_plan_tamper_and_past_start():
    factory, _, identity, _, _ = setup_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    changed = {**plan, 'host': 'another-host'}
    with pytest.raises(RepositoryConflict, match='PLAN_HASH_CONFLICT'):
        service.apply(changed, expected_plan_hash=plan['plan_hash'], now=NOW)
    with pytest.raises(RepositoryConflict, match='PLAN_EXPIRED_OR_START_IN_PAST'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=START + timedelta(seconds=1))


def test_atomic_activation_failure_rolls_back_target_seed(monkeypatch):
    from app.reference_trading.activation import ForwardActivation
    factory, _, identity, _, _ = setup_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    def fail(*args, **kwargs):
        raise RepositoryConflict('injected_before_activation')
    monkeypatch.setattr(ForwardActivation, 'apply', fail)
    with pytest.raises(RepositoryConflict, match='injected_before_activation'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    with factory() as session:
        assert session.get(ReferenceStream, plan['target_stream_id']) is None
        assert session.scalar(select(func.count()).select_from(ReferenceRevision)) == 1


def test_scope_matrix_requires_exact_sixty_and_reports_missing_history_without_writing():
    from app.reference_trading.newow_bootstrap import validate_product_scope
    factory, _, _, _, _ = setup_source()
    service = NewowForwardBootstrap(factory)
    products = tuple(f'p{chr(97 + index // 26)}{chr(97 + index % 26)}' for index in range(60))
    assert validate_product_scope(products, products) == tuple(sorted(products))
    with pytest.raises(ValueError, match='BOOTSTRAP_PRODUCT_SCOPE_INVALID'):
        validate_product_scope(products, products[:-1])
    result = service.plan_scope(products, products, recording_start=START, expires_at=START,
        host='isolated-host', environment='isolated', now=NOW)
    assert result['expected_count'] == 720
    assert len(result['items']) == 720
    assert all(item['reason'] == 'BOOTSTRAP_HISTORY_MISSING' for item in result['items'])
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceStream)) == 1


def test_script_scope_preflight_blocks_incomplete_product_before_apply():
    from scripts.newow_recording_bootstrap import apply_product
    from app.reference_trading.newow_bootstrap import _hash
    payload = {'version': 'newow_forward_bootstrap_scope_v1', 'products': ['rb'],
               'items': [{'product': 'rb', 'strategy': 'trend', 'frequency': '1d', 'status': 'ready', 'plan': {}}]}
    payload['plan_hash'] = _hash(payload)
    class NoWrites:
        def apply(self, *args, **kwargs):
            raise AssertionError('must not mutate an incomplete product')
    with pytest.raises(RepositoryConflict, match='BOOTSTRAP_PRODUCT_NOT_READY'):
        apply_product(NoWrites(), payload, product='RB', expected_plan_hash=payload['plan_hash'], now=lambda: NOW)


def test_script_existing_output_blocks_before_loading_any_database(tmp_path, monkeypatch):
    from scripts import newow_recording_bootstrap as script
    output = tmp_path / 'receipt.json'
    output.write_text('prior-evidence')
    calls = []
    def reject(*args):
        calls.append(args)
        raise AssertionError('must not load database for an occupied output')
    monkeypatch.setattr(script, 'load_private_readonly_settings', reject)
    assert script.main(['--project-env', '/unused', '--output', str(output), '--recording-start', START.isoformat(), '--expires-at', START.isoformat()]) == 1
    assert output.read_text() == 'prior-evidence'
    assert calls == []


def test_existing_partial_candidate_is_recovered_without_another_revision():
    from dataclasses import replace
    from app.reference_trading.newow_bootstrap import POLICY
    from guiyi_quant.reference_trading import RecordingMode
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
    factory, repo, identity, _, source = setup_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    target = replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION, observation_policy_version=POLICY)
    stored = repo.ensure_stream(target)
    manifest = {**repo.read_state(identity.stream_id).dependency_manifest, 'forward_bootstrap_v1': {
        'plan_hash': plan['plan_hash'], 'source': plan['source'],
        'recording_start': plan['recording_start'], 'policy': POLICY}}
    candidate = repo.create_revision(target.stream_id, stored.row_version, manifest_sha256(manifest))
    checkpoint = replace(source, stream=target, reference_state=ReferenceState.flat(target, recording_start=START))
    payload = adapter_checkpoint_to_json(checkpoint, strategy_schema='newow_product_replay_v1')
    repo.stage_seed_chunk(candidate, SeedChunk('bootstrap:' + plan['plan_hash'], 0, 1,
        sha256(payload.encode()).hexdigest(), payload))
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    assert result['revision_id'] == candidate
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceRevision)) == 2


def test_bootstrap_never_inherits_historical_open_reference_trade():
    from dataclasses import replace
    from guiyi_quant.reference_trading import ReferenceAction, ActionKind, reduce_reference
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
    from app.reference_trading.models import ReferenceBatch
    factory, repo, identity, revision, source = setup_source()
    action = ReferenceAction(identity, 'historical-build', 'RB2610', 'owner', 'calc',
        source.computed_through, source.computed_through.date(), 0, ActionKind.OPEN_LONG, Decimal('3500'))
    historical = reduce_reference(ReferenceState.flat(identity), actions=(action,)).state
    assert historical.open_trade is not None
    changed = replace(source, reference_state=historical)
    payload = adapter_checkpoint_to_json(changed, strategy_schema='newow_product_replay_v1')
    with factory.begin() as session:
        rev = session.get(ReferenceRevision, (identity.stream_id, revision))
        batch = session.get(ReferenceBatch, rev.checkpoint_batch_id)
        batch.checkpoint_text = payload
        batch.post_state_hash = sha256(payload.encode()).hexdigest()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    _, forward = repo.load_checkpoint(result['target_stream_id'])
    assert forward.strategy_state == source.strategy_state
    assert forward.reference_state.open_trade is None
    assert forward.reference_state.computed_through is None
    assert forward.reference_state.recording_start == START


from tests.alembic.conftest import isolated_postgres_engine  # noqa: E402,F401


@pytest.fixture
def bootstrap_postgresql(isolated_postgres_engine):  # noqa: F811
    from uuid import uuid4
    schema = "newow_bootstrap_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    try:
        yield scoped
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.mark.isolated_postgresql
def test_postgresql_concurrent_bootstraps_commit_one_exact_receipt(bootstrap_postgresql):
    from concurrent.futures import ThreadPoolExecutor
    factory, _, identity, _, _ = setup_source(bootstrap_postgresql)
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    def apply():
        return service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(), range(2)))
    assert results[0] == results[1]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceActivationReceipt)) == 1
        assert session.scalar(select(func.count()).select_from(ReferenceRevision)) == 2


@pytest.mark.isolated_postgresql
def test_postgresql_activation_failure_rolls_back_all_seed_mutations(bootstrap_postgresql, monkeypatch):
    from app.reference_trading.activation import ForwardActivation
    factory, _, identity, _, _ = setup_source(bootstrap_postgresql)
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    def fail(*args, **kwargs):
        raise RepositoryConflict('injected_before_activation')
    monkeypatch.setattr(ForwardActivation, 'apply', fail)
    with pytest.raises(RepositoryConflict, match='injected_before_activation'):
        service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    with factory() as session:
        assert session.get(ReferenceStream, plan['target_stream_id']) is None
        assert session.scalar(select(func.count()).select_from(ReferenceRevision)) == 1


@pytest.mark.parametrize("frequency", ["1d", "1w", "60m"])
def test_short_main_rise_warming_checkpoint_is_not_rejected(frequency):
    factory, _, identity, _, source = setup_source(strategy="main_rise", frequency=frequency)
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    _, checkpoint = ReferenceRepository(factory).load_checkpoint(result['target_stream_id'])
    assert checkpoint.strategy_state == source.strategy_state
    assert checkpoint.reference_state.open_trade is None


def setup_fusion_source():
    from app.market_data.newow.product_release import candidate_input_quality_policy
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity, FusionReferenceReplayState
    factory, repo, _, _, _ = setup_source()
    identity = build_fusion_stream_identity('rb', '1d',
        input_quality_policy=candidate_input_quality_policy('rb', '1d', candidate_weekly=False))
    stored = repo.ensure_stream(identity)
    from app.reference_trading.inputs import NEWOW_D1_REFERENCE_BOUNDARY_POLICY
    manifest = {'source': 'verified-fusion-fixture',
                'reference_boundary_policy_version': NEWOW_D1_REFERENCE_BOUNDARY_POLICY}
    revision = repo.create_revision(identity.stream_id, stored.row_version, manifest_sha256(manifest))
    source = AdapterCheckpoint(FusionReferenceReplayState(), NOW - timedelta(days=1),
        'f' * 64, 'RB2610', 'owner', 'calc', identity, ReferenceState.flat(identity))
    repo.stage_seed_chunk(revision, SeedChunk('seed', 0, 1, sha256(b'seed').hexdigest(), 'seed'))
    repo.seal_seed(revision, manifest, source, 'newow_dual_fusion_reference_v1')
    repo.publish_revision(identity.stream_id, revision, stored.row_version, manifest_sha256(manifest))
    return factory, repo, identity, revision, source


def test_dual_fusion_uses_its_own_schema_and_flat_reference_state():
    factory, repo, identity, revision, source = setup_fusion_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    assert plan['strategy_schema'] == 'newow_dual_fusion_reference_v1'
    result = service.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    _, checkpoint = repo.load_checkpoint(result['target_stream_id'])
    assert checkpoint.strategy_state == source.strategy_state
    assert checkpoint.reference_state == ReferenceState.flat(checkpoint.stream, recording_start=START)


def test_product_apply_rejects_nested_other_product_before_any_mutation():
    from scripts.newow_recording_bootstrap import apply_product
    from app.reference_trading.newow_bootstrap import _hash
    items = []
    for frequency in ('1w', '1d', '60m'):
        for strategy in ('trend', 'oscillation', 'main_rise', 'dual_fusion'):
            nested = {'product': 'rb', 'strategy': strategy, 'frequency': frequency}
            nested['plan_hash'] = _hash(nested)
            items.append({'product': 'rb', 'strategy': strategy, 'frequency': frequency,
                          'status': 'ready', 'plan': nested})
    items[-1]['plan'] = {**items[-1]['plan'], 'product': 'cu'}
    payload = {'version': 'newow_forward_bootstrap_scope_v1', 'items': items}
    payload['plan_hash'] = _hash(payload)
    class NoWrites:
        def apply(self, *args, **kwargs):
            raise AssertionError('nested product scope mismatch must block before mutation')
    with pytest.raises(RepositoryConflict, match='BOOTSTRAP_PRODUCT_PLAN_IDENTITY_CONFLICT'):
        apply_product(NoWrites(), payload, product='rb', expected_plan_hash=payload['plan_hash'], now=lambda: NOW)


def test_bootstrap_apply_binds_declared_product_to_locked_source_identity():
    from app.reference_trading.newow_bootstrap import _hash
    factory, _, identity, _, _ = setup_source()
    service = NewowForwardBootstrap(factory)
    plan = plan_for(service, identity)
    wrong = {**plan, 'product': 'cu'}
    wrong['plan_hash'] = _hash({key: value for key, value in wrong.items() if key != 'plan_hash'})
    with pytest.raises(RepositoryConflict, match='BOOTSTRAP_PLAN_IDENTITY_CONFLICT'):
        service.apply(wrong, expected_plan_hash=wrong['plan_hash'], now=NOW)
    with factory() as session:
        assert session.get(ReferenceStream, plan['target_stream_id']) is None


@pytest.mark.parametrize('strategy', ['trend', 'oscillation', 'main_rise', 'dual_fusion'])
@pytest.mark.parametrize('old_policy', [None, 'legacy_boundary_v0'])
def test_daily_old_hash_bound_boundary_policy_rejected_without_target_mutation(strategy, old_policy):
    from app.reference_trading.models import ReferenceBatch
    factory, repo, identity, revision, source = (setup_fusion_source() if strategy == 'dual_fusion'
                                               else setup_source(strategy=strategy))
    with factory.begin() as session:
        rev = session.get(ReferenceRevision, (identity.stream_id, revision))
        batch = session.get(ReferenceBatch, rev.checkpoint_batch_id)
        manifest = dict(batch.dependency_manifest)
        if old_policy is None:
            manifest.pop('reference_boundary_policy_version', None)
        else:
            manifest['reference_boundary_policy_version'] = old_policy
        batch.dependency_manifest = manifest
        rev.dependency_digest = manifest_sha256(manifest)
    with pytest.raises(RepositoryConflict, match='BOOTSTRAP_HISTORY_BOUNDARY_POLICY_CONFLICT'):
        plan_for(NewowForwardBootstrap(factory), identity)
    with factory() as session:
        expected_count = 2 if strategy == 'dual_fusion' else 1
        assert session.scalar(select(func.count()).select_from(ReferenceStream)) == expected_count
        assert session.scalar(select(func.count()).select_from(ReferenceRevision)) == expected_count


def test_apply_rechecks_daily_policy_under_source_lock_before_target_creation():
    from app.reference_trading.models import ReferenceBatch
    factory, repo, identity, revision, source = setup_source()
    bootstrap = NewowForwardBootstrap(factory)
    plan = plan_for(bootstrap, identity)
    with factory.begin() as session:
        rev = session.get(ReferenceRevision, (identity.stream_id, revision))
        batch = session.get(ReferenceBatch, rev.checkpoint_batch_id)
        manifest = dict(batch.dependency_manifest)
        manifest.pop('reference_boundary_policy_version', None)
        batch.dependency_manifest = manifest
        rev.dependency_digest = manifest_sha256(manifest)
    with pytest.raises(RepositoryConflict, match='BOOTSTRAP_HISTORY_BOUNDARY_POLICY_CONFLICT'):
        bootstrap.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceStream)) == 1
