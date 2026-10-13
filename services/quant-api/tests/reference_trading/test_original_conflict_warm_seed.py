from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.inputs import HistoricalInputBar, HistoricalInputSnapshot
from app.reference_trading.original_conflict_warm_seed import (
    BASE_SCHEMA, VERSION, WarmBaseline, WarmInput, WarmInterval, _hash, _input_facts,
    materialize_warm_seed, materialize_fusion_warm_seed,
)
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.service import NewowHistoricalPayload
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity, replay_step, seed_replay_state
from guiyi_quant.newow.product_contracts import ProductBar
from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
from guiyi_quant.reference_trading import ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json

AT = datetime(2026, 10, 13, 7, tzinfo=UTC)
START = datetime(2026, 10, 14, 1, tzinfo=UTC)


def fixture(strategy='trend', prices=None):
    product_identity = build_product_identity('rb', strategy, '60m')
    identity = StreamIdentity('newow_' + strategy, product_identity.formula_versions,
        product_identity.profile_id, REFERENCE_MODEL_VERSION,
        futures_adaptation_version('60m', product_identity.input_quality_policy),
        'rb', '60m', 'actual_dominant', 'historical_replay', None)
    def bar(index, end, *, contract='RB2701', owner='owner', calculation='calc'):
        price = Decimal(prices[index] if prices and index < len(prices) else 3500 + index % 9)
        raw = NewowDailyBar('rb', contract, owner, end.date(), end,
            price, price + 10, price - 10, price + 2, 100, None,
            'canonical-or-verified-live', True, True)
        return ProductBar(raw, '60m', calculation_segment_id=calculation,
            source_bar_sha256=_hash({'index': index, 'contract': contract, 'end': end.isoformat()}))
    state, old_bars = seed_replay_state(), []
    for index in range(65):
        item = bar(index, AT - timedelta(hours=66-index))
        state, _, _ = replay_step(product_identity, state, item)
        old_bars.append(HistoricalInputBar(item.bar.bar_end, item.bar.trading_day,
            item.bar.physical_contract, item.bar.segment_id, item.calculation_segment_id,
            item.bar.close, _hash({'old': index}), NewowHistoricalPayload(product_identity, item, False)))
    end = old_bars[-1].bar_end
    checkpoint = AdapterCheckpoint(state, end, 'a'*64, 'RB2701', 'owner', 'calc', identity,
        ReferenceState.flat(identity))
    saved = {'reader': 'newow_product_reader_intraday_v3', 'query_since': old_bars[0].trading_day.isoformat(),
        'query_through': end.date().isoformat(), 'query_as_of': end.isoformat(),
        'source_evidence_sha256': 'a'*64, 'input_sha256': _hash(old_bars), 'input_count': len(old_bars),
        'quality_policy': product_identity.input_quality_policy.value,
        'formula_versions': list(identity.formula_versions), 'reference_model_version': identity.reference_model_version,
        'lifecycle_owners': [['RB2701', 'owner']]}
    fresh = {**saved, 'source_evidence_sha256': 'b'*64}
    snapshot = HistoricalInputSnapshot(identity, old_bars[0].trading_day, end,
        tuple(old_bars), fresh, manifest_sha256(fresh), 12345)
    binding = {'stream_id': identity.stream_id, 'revision_id': 'historical-fixture-revision', 'seq': 1,
        'checkpoint_hash': sha256(adapter_checkpoint_to_json(checkpoint, strategy_schema=BASE_SCHEMA).encode()).hexdigest(),
        'dependency_digest': manifest_sha256(saved), 'computed_through': end.isoformat()}
    baseline = WarmBaseline(identity, checkpoint, BASE_SCHEMA, saved, binding)
    def proof(item):
        if isinstance(item, WarmInterval):
            endpoints = [end + timedelta(hours=i) for i in (1, 2)
                if end + timedelta(hours=i) <= item.cutoff]
            return {'kind': 'completed_warm_interval' if endpoints else 'completed_empty_interval',
                'stream_id': item.identity.stream_id, 'previous_watermark': item.previous_watermark.isoformat(),
                'cutoff': item.cutoff.isoformat(), 'recording_start': item.recording_start.isoformat(),
                'knowledge_at': item.knowledge_at.isoformat(), 'stage': item.stage,
                'remaining_endpoints_before_start': [(end + timedelta(hours=i)).isoformat() for i in (1,2)
                    if item.cutoff < end + timedelta(hours=i) < item.recording_start],
                'physical_contract': item.physical_contract, 'owner_segment_id': item.owner_segment_id,
                'calculation_segment_id': item.calculation_segment_id,
                'expected_endpoints': [e.isoformat() for e in endpoints],
                'computed_through': (endpoints[-1] if endpoints else item.previous_watermark).isoformat(),
                'session_sha256': 'a'*64, 'owner_sha256': 'b'*64, 'quality_sha256': 'c'*64}
        if isinstance(item, HistoricalInputSnapshot):
            return {'kind': 'canonical_baseline', 'stream_id': item.stream.stream_id,
                'input_sha256': item.dependency_manifest['input_sha256'], 'input_count': len(item.bars),
                'source_evidence_sha256': item.dependency_manifest['source_evidence_sha256'],
                'computed_through': item.completed_through.isoformat(), 'range_sha256': _hash(item.bars),
                'physical_sha256': 'c'*64, 'session_sha256': 'd'*64, 'quality_sha256': 'e'*64}
        return deepcopy(item.source_proof)
    inputs = []
    for index in range(2):
        product = bar(65+index, end + timedelta(hours=index+1))
        kind = 'canonical_completed' if index == 0 else 'completed_live'
        item = WarmInput(product, kind, product.bar.bar_end, {})
        source = {**_input_facts(item), 'expected_endpoint': product.bar.bar_end.isoformat(),
            'previous_watermark': (product.bar.bar_end-timedelta(hours=1)).isoformat(),
            'expected_endpoints': [product.bar.bar_end.isoformat()], 'source_manifest_sha256': 'f'*64,
            'owner_sha256': '1'*64, 'session_sha256': '2'*64, 'quality_sha256': '3'*64, 'rollover': False}
        if kind == 'completed_live':
            source.update(recovery_plan_sha256='4'*64, recovery_readback_sha256='5'*64)
        inputs.append(replace(item, source_proof=source))
    def run(inputs=tuple(inputs), *, baseline=baseline, snapshot=snapshot, verify=proof):
        return materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=inputs,
            expected_endpoints=tuple(i.product_bar.bar.bar_end for i in inputs),
            recording_start=START, cutoff=inputs[-1].product_bar.bar.bar_end if inputs else end,
            stage='provisional_canonical' if inputs and inputs[-1].source_kind == 'canonical_completed' else 'final_observation',
            verify_authority=verify)
    return baseline, snapshot, tuple(inputs), proof, run, product_identity, bar


def test_actual_kernel_prefix_and_batched_parity_new_flat_no_baseline_mutation():
    baseline, _, inputs, _, run, identity, _ = fixture()
    original = adapter_checkpoint_to_json(baseline.checkpoint, strategy_schema=BASE_SCHEMA)
    state = baseline.checkpoint.strategy_state
    for index, item in enumerate(inputs, 1):
        state, _, _ = replay_step(identity, state, item.product_bar)
        result = run(inputs[:index])
        assert result.checkpoint.strategy_state == state
        assert result.checkpoint.computed_through == item.product_bar.bar.bar_end
        assert result.checkpoint.reference_state == ReferenceState.flat(baseline.identity, recording_start=START)
    assert result.proof['inputs'][1]['facts']['source_kind'] == 'completed_live'
    assert result.proof['first_seen'] is False and result.proof['natural_capture'] is False
    assert result.proof['inputs'][0]['facts']['owner_observation_eligible'] is True
    assert result.binding['kind'] == VERSION
    assert result.binding['original_source_binding'] == baseline.binding
    assert result.binding['checkpoint_hash'] != baseline.binding['checkpoint_hash']
    assert adapter_checkpoint_to_json(baseline.checkpoint, strategy_schema=BASE_SCHEMA) == original
    assert run().seed_hash == run().seed_hash


@pytest.mark.parametrize('field', ['input_sha256', 'input_count', 'formula_versions', 'query_through', 'lifecycle_owners'])
def test_changed_true_baseline_inputs_require_historical_rebuild(field):
    baseline, snapshot, _, _, run, _, _ = fixture()
    fresh = dict(snapshot.dependency_manifest)
    fresh[field] = 'different'
    with pytest.raises(RepositoryConflict, match='NEEDS_HISTORICAL_REBUILD'):
        run(snapshot=replace(snapshot, dependency_manifest=fresh, source_token=manifest_sha256(fresh)))


def test_unverified_baseline_quality_or_not_ready_fails_closed():
    baseline, _, _, proof, run, _, _ = fixture()
    with pytest.raises(RepositoryConflict, match='NEEDS_HISTORICAL_REBUILD'):
        run(baseline=replace(baseline, schema='NOT_READY'))
    def unknown(item):
        raise OSError('untrusted SQL or secret text')
    with pytest.raises(RepositoryConflict, match='^WARM_SEED_AUTHORITY_UNAVAILABLE$'):
        run(verify=unknown)
    def bad_quality(item):
        value = proof(item)
        value['quality_sha256'] = None
        return value
    with pytest.raises(RepositoryConflict, match='BASELINE_AUTHORITY_INVALID'):
        run(verify=bad_quality)


def test_live_recovery_must_be_independently_bound_and_first_seen_false():
    _, _, inputs, _, run, _, _ = fixture()
    second = replace(inputs[1], source_proof={k:v for k,v in inputs[1].source_proof.items() if k != 'recovery_readback_sha256'})
    with pytest.raises(RepositoryConflict, match='LIVE_RECOVERY_UNVERIFIED'):
        run((inputs[0], second))
    with pytest.raises(RepositoryConflict, match='INPUT_INVALID'):
        run((replace(inputs[0], first_seen=True),))


def test_gap_and_unconfirmed_and_future_input_rejected():
    _, _, inputs, _, run, _, _ = fixture()
    second = replace(inputs[1], source_proof={**inputs[1].source_proof, 'previous_watermark': inputs[0].source_proof['previous_watermark']})
    with pytest.raises(RepositoryConflict, match='OBSERVATION_GAP'):
        run((inputs[0], second))
    with pytest.raises(ValueError, match='NEWOW_BAR_NOT_COMPLETED'):
        replace(inputs[0].product_bar.bar, completed=False)
    with pytest.raises(RepositoryConflict, match='FUTURE_BOUNDARY_INVALID'):
        future = replace(inputs[0], product_bar=replace(inputs[0].product_bar,
            bar=replace(inputs[0].product_bar.bar, bar_end=START)))
        run((future,))


def test_explicit_roll_resets_real_kernel_without_cross_chain_carry():
    baseline, _, inputs, _, run, identity, bar = fixture()
    product = bar(80, inputs[0].product_bar.bar.bar_end, contract='RB2705', owner='owner2', calculation='calc2')
    item = replace(inputs[0], product_bar=product)
    item = replace(item, source_proof={**item.source_proof, **_input_facts(item), 'rollover': True})
    result = run((item,))
    expected, _, _ = replay_step(identity, seed_replay_state(), product)
    assert result.checkpoint.strategy_state == expected
    assert result.checkpoint.reference_state.open_trade is None
    assert result.proof['rollovers'][0]['next'] == ['RB2705', 'owner2', 'calc2']
    with pytest.raises(RepositoryConflict, match='ROLLOVER_UNVERIFIED'):
        run((replace(item, source_proof={**item.source_proof, 'rollover': False}),))


def test_fusion_binds_all_three_actual_same_inputs_versions_and_new_flat():
    bases = tuple(fixture(s)[4]() for s in ('trend', 'oscillation', 'main_rise'))
    identity = build_fusion_stream_identity('rb', '60m')
    binding = {'stream_id': identity.stream_id, 'revision_id': 'old-fusion', 'seq': 1,
        'checkpoint_hash': 'a'*64, 'dependency_digest': 'b'*64,
        'computed_through': bases[0].binding['original_source_binding']['computed_through']}
    result = materialize_fusion_warm_seed(identity, bases, original_binding=binding, recording_start=START)
    assert result.checkpoint.computed_through == bases[0].checkpoint.computed_through
    assert result.checkpoint.reference_state.open_trade is None
    assert len(result.proof['base_seeds']) == 3
    with pytest.raises(RepositoryConflict, match='FUSION_INPUT_CONFLICT'):
        changed = replace(bases[2], proof={**bases[2].proof, 'input_chain_sha256': 'a'*64})
        materialize_fusion_warm_seed(identity, (*bases[:2],changed), original_binding=binding, recording_start=START)


def test_authority_binds_actual_ohlcv_not_only_claimed_source_hash():
    _, _, inputs, _, run, _, _ = fixture()
    changed = replace(inputs[0], product_bar=replace(inputs[0].product_bar,
        bar=replace(inputs[0].product_bar.bar, close=inputs[0].product_bar.bar.close+Decimal(1))))
    with pytest.raises(RepositoryConflict, match='INPUT_AUTHORITY_INVALID'):
        run((changed,))


def test_zero_step_requires_actual_empty_session_proof_preserves_strategy_frontier():
    baseline, snapshot, _, authority, _, _, _ = fixture()
    cutoff = baseline.checkpoint.computed_through
    def verify(item):
        if not isinstance(item, WarmInterval):
            return authority(item)
        return {'kind': 'completed_empty_interval', 'stream_id': item.identity.stream_id,
            'previous_watermark': item.previous_watermark.isoformat(), 'cutoff': item.cutoff.isoformat(),
            'knowledge_at': item.knowledge_at.isoformat(), 'stage': item.stage,
            'remaining_endpoints_before_start': [], 'recording_start': item.recording_start.isoformat(), 'physical_contract': item.physical_contract,
            'owner_segment_id': item.owner_segment_id, 'calculation_segment_id': item.calculation_segment_id,
            'expected_endpoints': [], 'computed_through': item.previous_watermark.isoformat(), 'session_sha256': 'a'*64, 'owner_sha256': 'b'*64, 'quality_sha256': 'c'*64}
    def run(verify=verify):
        return materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=(), expected_endpoints=(),
            recording_start=START, cutoff=cutoff, verify_authority=verify)
    seed = run()
    assert seed.checkpoint.strategy_state == baseline.checkpoint.strategy_state
    assert seed.checkpoint.computed_through == cutoff
    assert seed.checkpoint.last_fingerprint == baseline.checkpoint.last_fingerprint
    assert seed.checkpoint.reference_state == ReferenceState.flat(baseline.identity, recording_start=START)
    assert seed.proof['warm_step_count'] == 0 and seed.proof['zero_step_authority']['expected_endpoints'] == []
    def missed_endpoint(item):
        value = verify(item)
        if isinstance(item, WarmInterval):
            value['expected_endpoints'] = [(cutoff + timedelta(hours=1)).isoformat()]
        return value
    with pytest.raises(RepositoryConflict, match='EMPTY_INTERVAL_UNVERIFIED'):
        run(missed_endpoint)
    def missing_proof(item):
        return authority(item) if not isinstance(item, WarmInterval) else {'kind': 'completed_empty_interval'}
    with pytest.raises(RepositoryConflict, match='EMPTY_INTERVAL_UNVERIFIED'):
        run(missing_proof)


def test_cutoff_range_cannot_truncate_tail_even_if_rows_and_declared_endpoints_agree():
    baseline, snapshot, inputs, authority, _, _, _ = fixture()
    with pytest.raises(RepositoryConflict, match='INTERVAL_UNVERIFIED'):
        materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=inputs[:1],
            expected_endpoints=(inputs[0].product_bar.bar.bar_end,), recording_start=START,
            cutoff=AT, verify_authority=authority)


def test_old_fusion_watermark_is_true_lineage_not_new_base_watermark_gate():
    bases = tuple(fixture(s)[4]() for s in ('trend', 'oscillation', 'main_rise'))
    identity = build_fusion_stream_identity('rb', '60m')
    binding = {'stream_id': identity.stream_id, 'revision_id': 'true-old-fusion', 'seq': 1,
        'checkpoint_hash': 'a'*64, 'dependency_digest': 'b'*64,
        'computed_through': (AT - timedelta(days=4)).isoformat()}
    result = materialize_fusion_warm_seed(identity, bases, original_binding=binding, recording_start=START)
    assert result.binding['original_source_binding'] == binding
    assert result.checkpoint.computed_through == bases[0].checkpoint.computed_through


def test_provisional_canonical_never_claims_final_frontier_and_final_requires_rest_empty():
    baseline, snapshot, inputs, authority, _, _, _ = fixture()
    cutoff = inputs[0].product_bar.bar.bar_end
    def verify(item):
        value = authority(item)
        if isinstance(item, WarmInterval):
            value['remaining_endpoints_before_start'] = [inputs[1].product_bar.bar.bar_end.isoformat()]
        return value
    seed = materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=inputs[:1],
        expected_endpoints=(cutoff,), recording_start=START, cutoff=cutoff,
        knowledge_at=AT, stage='provisional_canonical', verify_authority=verify)
    assert seed.proof['status'] == 'PENDING_WARMUP'
    assert seed.proof['knowledge_at'] == AT.isoformat()
    assert seed.checkpoint.computed_through == cutoff
    with pytest.raises(RepositoryConflict, match='FINAL_FRONTIER_INCOMPLETE'):
        materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=inputs[:1],
            expected_endpoints=(cutoff,), recording_start=START, cutoff=cutoff,
            knowledge_at=AT, stage='final_observation', verify_authority=verify)


def test_late_non_first_seen_confirmation_binds_actual_knowledge_time_not_prefix_cutoff():
    baseline, snapshot, inputs, authority, _, _, _ = fixture()
    item = replace(inputs[0], confirmed_at=AT)
    item = replace(item, source_proof={**item.source_proof, **_input_facts(item)})
    cutoff = item.product_bar.bar.bar_end
    seed = materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=(item,),
        expected_endpoints=(cutoff,), recording_start=START, cutoff=cutoff,
        knowledge_at=AT, stage='provisional_canonical', verify_authority=authority)
    assert seed.proof['inputs'][0]['facts']['confirmed_at'] == AT.isoformat()
    assert seed.proof['cutoff'] == cutoff.isoformat() and seed.proof['knowledge_at'] == AT.isoformat()
    future = replace(item, confirmed_at=AT + timedelta(seconds=1))
    future = replace(future, source_proof={**future.source_proof, **_input_facts(future)})
    with pytest.raises(RepositoryConflict, match='INPUT_INVALID'):
        materialize_warm_seed(baseline, fresh_snapshot=snapshot, inputs=(future,),
            expected_endpoints=(cutoff,), recording_start=START, cutoff=cutoff,
            knowledge_at=AT, stage='provisional_canonical', verify_authority=authority)


def test_authoritative_owner_eligibility_preserves_baseline_build_clear_pairing_during_warmup():
    baseline, _, _, _, run, _, _ = fixture(prices=[3500]*60+[3000,3000,3600,3600,3600,2500,2500])
    assert baseline.checkpoint.strategy_state.pairing.eligible_build is not None
    result = run()
    assert result.checkpoint.strategy_state.pairing.eligible_build is None
    assert result.checkpoint.reference_state.open_trade is None
    assert all(i['facts']['first_seen'] is False for i in result.proof['inputs'])
    assert all(i['facts']['owner_observation_eligible'] is True for i in result.proof['inputs'])
