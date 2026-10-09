"""1260 persisted observation routes through real kernels in an isolated schema."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.forward_service import ForwardReferenceService
from app.reference_trading.models import ReferenceBatch
from app.reference_trading.newow_forward import evaluate_newow_capture
from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources, evaluate_fusion_capture
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.runtime import ForwardReferenceWorker
from app.market_data.newow.product_release import candidate_input_quality_policy
from guiyi_quant.newow.product_adapters import build_product_identity, seed_replay_state
from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState, build_fusion_stream_identity
from guiyi_quant.reference_trading import RecordingMode, ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from test_newow_forward import _capture


@pytest.mark.isolated_postgresql
def test_1260_current_routes_are_fair_persisted_and_restart_idempotent(isolated_postgres_engine):  # noqa: F811
    from newow.product_fixtures import ProductCases

    schema = 'newow_720_' + uuid4().hex
    with isolated_postgres_engine.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = isolated_postgres_engine.execution_options(schema_translate_map={None:schema})
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        repo = ReferenceRepository(factory)
        loader = SavedForwardFusionSources(factory)
        root = Path(__file__).resolve().parents[4]
        products = (root/'data/universe/operational_products.txt').read_text().split()
        assert len(products) == 60
        captures = {}
        manifests = {}
        contexts = {}
        all_now = []
        for product in products:
            product = product.lower()
            from app.reference_trading.recording_scope import FREQUENCIES, LIVE_FREQUENCIES, strategies_for
            for frequency in FREQUENCIES:
                case = ProductCases().closed(frequency=frequency)
                bar = case.bars[0]
                start = bar.bar.bar_end
                now = start + timedelta(minutes=1)
                all_now.append(now)
                policy = candidate_input_quality_policy(product, frequency, candidate_weekly=False)
                for strategy in strategies_for(frequency):
                    if strategy == 'dual_fusion':
                        identity = build_fusion_stream_identity(product,frequency,
                            recording_mode='forward_observation',observation_policy_version='completed_observation_v1',
                            input_quality_policy=policy)
                        state, state_schema = FusionReferenceReplayState(), 'newow_dual_fusion_reference_v1'
                    else:
                        p = build_product_identity(product,strategy,frequency,input_quality_policy=policy)
                        identity = StreamIdentity(f'newow_{strategy}',p.formula_versions,p.profile_id,
                            REFERENCE_MODEL_VERSION,futures_adaptation_version(frequency,policy),product,
                            frequency,'actual_dominant',RecordingMode.FORWARD_OBSERVATION,'completed_observation_v1')
                        state, state_schema = seed_replay_state(), 'newow_product_replay_v1'
                    stored = repo.ensure_stream(identity)
                    manifest = {'isolated_fixture':identity.stream_id}
                    manifests[identity.stream_id] = manifest
                    revision = repo.create_revision(identity.stream_id,stored.row_version,manifest_sha256(manifest))
                    repo.stage_seed_chunk(revision,SeedChunk('seed',0,1,sha256(b'seed').hexdigest(),'seed'))
                    repo.seal_seed(revision,manifest,AdapterCheckpoint(state,stream=identity,
                        reference_state=ReferenceState.flat(identity,recording_start=start)),state_schema)
                    activation = ForwardActivation(factory)
                    plan = activation.plan(identity.stream_id,revision,host='isolated',environment='isolated',
                        recording_start=start,expires_at=now,budget={'max_pending':32})
                    activation.apply(plan,expected_plan_hash=plan.plan_hash,now=start-timedelta(seconds=1))
                    contexts[identity.stream_id]=(identity,revision,start,now)
                    if strategy != 'dual_fusion':
                        capture = _capture(identity,bar)
                        captures[identity.stream_id]=replace(capture,revision_id=revision,
                            source_kind='completed_live' if frequency in LIVE_FREQUENCIES else 'canonical_completed',
                            input_payload={**capture.input_payload,'input_quality_policy':policy.value})
        def read(stream_id,_kind,_end):
            identity,revision,start,now=contexts[stream_id]
            if identity.strategy_code == 'newow_dual_fusion':
                context=repo.forward_source_context(stream_id)
                return loader(identity,revision_id=revision,generation=1,after=context[4],now=now)
            context=repo.forward_source_context(stream_id)
            return captures[stream_id] if context[4] is None else None
        def service(stream_id):
            evaluator = evaluate_fusion_capture if contexts[stream_id][0].strategy_code == 'newow_dual_fusion' else evaluate_newow_capture
            return ForwardReferenceService(repo,lambda token,cp,evidence:evaluator(token,cp,evidence,
                dependency_manifest=manifests[stream_id]))
        worker=ForwardReferenceWorker(repo,service,read,enabled=True)
        worker.scan()
        assert worker.health().pending_keys == 360
        completed=0
        for _ in range(80):
            if worker.health().pending_keys == 0:
                break
            completed += worker.run_round()
        assert completed == 1260, worker.health().blocked
        assert not worker.health().blocked and worker.health().pending_keys == 0
        with factory() as c:
            count=c.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind=='calculation'))
            pending=c.scalar(select(func.count()).select_from(ReferenceBatch).where(
                ReferenceBatch.kind=='capture',ReferenceBatch.consumed_by_batch_id.is_(None)))
        assert count == 1260 and pending == 0
        restarted=ForwardReferenceWorker(repo,service,read,enabled=True)
        restarted.scan()
        while restarted.health().pending_keys:
            assert restarted.run_round() == 0
        with factory() as c:
            assert c.scalar(select(func.count()).select_from(ReferenceBatch).where(ReferenceBatch.kind=='calculation')) == count
    finally:
        with isolated_postgres_engine.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
