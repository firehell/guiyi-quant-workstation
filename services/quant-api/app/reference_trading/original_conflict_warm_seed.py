"""Read-only H1 conflict warm-up using actual kernels and separately bound proof.

This path does not relax SourceVerifier. A fresh read of the *original* range
must reproduce every saved manifest field except the publication evidence hash.
Only strategy state advances; reference state always starts flat at a future
recording boundary. No batch, capture, reconciliation, trade or notice is emitted.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Callable

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.inputs import HistoricalInputSnapshot
from app.reference_trading.newow_bootstrap import _aware
from app.reference_trading.repository import RepositoryConflict, _wire
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState, build_fusion_stream_identity
from guiyi_quant.newow.product_adapters import ProductReplayState, build_product_identity, replay_step, seed_replay_state
from guiyi_quant.newow.product_contracts import ProductBar
from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
from guiyi_quant.reference_trading import ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint, strategy_input_fingerprint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json

VERSION = 'original_conflict_warm_seed_v1'
BASE_SCHEMA = 'newow_product_replay_v1'
FUSION_SCHEMA = 'newow_dual_fusion_reference_v1'


def require(condition, code='WARM_SEED_PROOF_INVALID'):
    if not condition:
        raise RepositoryConflict(code)


def _hash(value):
    return manifest_sha256(_wire(value))


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True)
class WarmBaseline:
    identity: StreamIdentity
    checkpoint: AdapterCheckpoint
    schema: str
    saved_manifest: dict
    binding: dict


@dataclass(frozen=True)
class WarmInput:
    product_bar: ProductBar
    source_kind: str
    confirmed_at: datetime
    source_proof: dict
    first_seen: bool = False


@dataclass(frozen=True)
class WarmInterval:
    identity: StreamIdentity
    previous_watermark: datetime
    cutoff: datetime
    recording_start: datetime
    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    knowledge_at: datetime
    stage: str


@dataclass(frozen=True)
class MaterializedWarmSeed:
    identity: StreamIdentity
    checkpoint: AdapterCheckpoint
    schema: str
    manifest: dict
    binding: dict
    proof: dict
    seed_hash: str


def _authority(verify: Callable, item):
    try:
        value = verify(item)
    except Exception as error:
        raise RepositoryConflict('WARM_SEED_AUTHORITY_UNAVAILABLE') from error
    require(isinstance(value, dict) and value, 'WARM_SEED_AUTHORITY_UNAVAILABLE')
    return deepcopy(value)


def _input_facts(item):
    product = item.product_bar
    bar = product.bar
    return {'product': bar.product, 'frequency': product.frequency.value,
        'physical_contract': bar.physical_contract, 'owner_segment_id': bar.segment_id,
        'calculation_segment_id': product.calculation_segment_id,
        'bar_end': bar.bar_end.isoformat(), 'trading_day': bar.trading_day.isoformat(),
        'bar_sha256': product.source_bar_sha256, 'bar_input_sha256': _hash(product),
        'source_identity': bar.source_identity,
        'source_kind': item.source_kind, 'confirmed_at': item.confirmed_at.isoformat(),
        'first_seen': False, 'owner_observation_eligible': bar.observation_eligible}


def _baseline(baseline, fresh_snapshot, verify):
    identity, checkpoint = baseline.identity, baseline.checkpoint
    require(identity.frequency == '60m' and identity.series_kind == 'actual_dominant'
        and identity.recording_mode.value == 'historical_replay'
        and identity.strategy_code in ('newow_trend', 'newow_oscillation', 'newow_main_rise')
        and baseline.schema == BASE_SCHEMA and isinstance(checkpoint.strategy_state, ProductReplayState)
        and checkpoint.stream == identity and checkpoint.computed_through is not None,
        'NEEDS_HISTORICAL_REBUILD')
    require(isinstance(fresh_snapshot, HistoricalInputSnapshot)
        and fresh_snapshot.stream == identity and fresh_snapshot.completed_through == checkpoint.computed_through,
        'NEEDS_HISTORICAL_REBUILD')
    saved, fresh = baseline.saved_manifest, fresh_snapshot.dependency_manifest
    require(saved.get('reader') == fresh.get('reader') == 'newow_product_reader_intraday_v3'
        and _sha(saved.get('input_sha256')) and _sha(fresh.get('source_evidence_sha256'))
        and _sha(saved.get('source_evidence_sha256'))
        and type(saved.get('input_count')) is int and saved['input_count'] > 0
        and saved['input_count'] == len(fresh_snapshot.bars)
        and {k: v for k, v in saved.items() if k != 'source_evidence_sha256'}
            == {k: v for k, v in fresh.items() if k != 'source_evidence_sha256'}
        and fresh_snapshot.source_token == manifest_sha256(fresh), 'NEEDS_HISTORICAL_REBUILD')
    content = adapter_checkpoint_to_json(checkpoint, strategy_schema=baseline.schema)
    binding = baseline.binding
    require(binding.get('stream_id') == identity.stream_id
        and binding.get('checkpoint_hash') == sha256(content.encode()).hexdigest()
        and binding.get('dependency_digest') == manifest_sha256(saved)
        and binding.get('computed_through') == checkpoint.computed_through.isoformat()
        and binding.get('revision_id') and type(binding.get('seq')) is int and binding['seq'] > 0,
        'NEEDS_HISTORICAL_REBUILD')
    authority = _authority(verify, fresh_snapshot)
    expected = {'kind': 'canonical_baseline', 'stream_id': identity.stream_id,
        'input_sha256': fresh['input_sha256'], 'input_count': fresh['input_count'],
        'source_evidence_sha256': fresh['source_evidence_sha256'],
        'computed_through': checkpoint.computed_through.isoformat(),
        'range_sha256': _hash(fresh_snapshot.bars)}
    require(all(authority.get(k) == v for k, v in expected.items())
        and all(_sha(authority.get(k)) for k in ('physical_sha256', 'session_sha256', 'quality_sha256')),
        'WARM_SEED_BASELINE_AUTHORITY_INVALID')
    return authority


def materialize_warm_seed(baseline: WarmBaseline, *, fresh_snapshot: HistoricalInputSnapshot,
        inputs: tuple[WarmInput, ...], expected_endpoints: tuple[datetime, ...],
        recording_start: datetime, cutoff: datetime, verify_authority: Callable,
        stage: str = 'final_observation', knowledge_at: datetime | None = None) -> MaterializedWarmSeed:
    start, at = map(_aware, (recording_start, cutoff))
    known = _aware(knowledge_at) if knowledge_at is not None else at
    require(at <= known < start, 'WARM_SEED_FUTURE_BOUNDARY_INVALID')
    require(stage in ('provisional_canonical', 'final_observation'), 'WARM_SEED_STAGE_INVALID')
    require(type(inputs) is tuple and 0 <= len(inputs) <= 256 and all(isinstance(i, WarmInput) for i in inputs)
        and type(expected_endpoints) is tuple and len(inputs) == len(expected_endpoints), 'WARM_SEED_INPUT_INVALID')
    authority = _baseline(baseline, fresh_snapshot, verify_authority)
    identity = baseline.identity
    product_identity = build_product_identity(identity.product, identity.strategy_code.removeprefix('newow_'),
        identity.frequency, input_quality_policy=baseline.saved_manifest['quality_policy'])
    expected_identity = StreamIdentity(identity.strategy_code, product_identity.formula_versions,
        product_identity.profile_id, REFERENCE_MODEL_VERSION,
        futures_adaptation_version(identity.frequency, product_identity.input_quality_policy),
        identity.product, identity.frequency, 'actual_dominant', 'historical_replay', None)
    require(identity == expected_identity, 'WARM_SEED_FORMULA_CONFLICT')
    checkpoint = deepcopy(baseline.checkpoint)
    previous = _aware(checkpoint.computed_through)
    require(previous <= at, 'WARM_SEED_ENDPOINT_INVALID')
    interval = WarmInterval(identity, previous, at, start, checkpoint.physical_contract,
        checkpoint.owner_segment_id, checkpoint.calculation_segment_id, known, stage)
    interval_authority = _authority(verify_authority, interval)
    expected = {'kind': 'completed_warm_interval' if inputs else 'completed_empty_interval',
        'stream_id': identity.stream_id, 'previous_watermark': previous.isoformat(),
        'cutoff': at.isoformat(), 'recording_start': start.isoformat(),
        'knowledge_at': known.isoformat(), 'stage': stage,
        'physical_contract': checkpoint.physical_contract, 'owner_segment_id': checkpoint.owner_segment_id,
        'calculation_segment_id': checkpoint.calculation_segment_id,
        'expected_endpoints': [end.isoformat() for end in expected_endpoints],
        'computed_through': expected_endpoints[-1].isoformat() if expected_endpoints else previous.isoformat()}
    require(all(interval_authority.get(k) == v for k, v in expected.items())
        and all(_sha(interval_authority.get(k)) for k in ('session_sha256', 'owner_sha256', 'quality_sha256')),
        'WARM_SEED_INTERVAL_UNVERIFIED' if inputs else 'WARM_SEED_EMPTY_INTERVAL_UNVERIFIED')
    if stage == 'final_observation':
        require(interval_authority.get('remaining_endpoints_before_start') == [],
            'WARM_SEED_FINAL_FRONTIER_INCOMPLETE')
    zero_step_authority = interval_authority if not inputs else None
    if not inputs:
        checkpoint = replace(checkpoint, reference_state=ReferenceState.flat(identity, recording_start=start))
    require(tuple(sorted(set(expected_endpoints))) == expected_endpoints
        and all(_aware(end) > previous and _aware(end) <= at for end in expected_endpoints), 'WARM_SEED_ENDPOINT_INVALID')
    records, rollovers = [], []
    live_started = False
    for item, expected_end in zip(inputs, expected_endpoints, strict=True):
        product, bar = item.product_bar, item.product_bar.bar
        confirmed = _aware(item.confirmed_at)
        require(bar.product == identity.product and product.frequency.value == identity.frequency
            and product.series_kind == identity.series_kind and bar.completed is True
            and item.first_seen is False and bar.bar_end == expected_end
            and previous < _aware(bar.bar_end) <= at
            and _aware(bar.bar_end) <= confirmed <= known
            and item.source_kind in ('canonical_completed', 'completed_live')
            and _sha(product.source_bar_sha256), 'WARM_SEED_INPUT_INVALID')
        require(not live_started or item.source_kind == 'completed_live', 'WARM_SEED_SOURCE_ORDER_INVALID')
        live_started = live_started or item.source_kind == 'completed_live'
        require(stage != 'provisional_canonical' or item.source_kind == 'canonical_completed',
            'WARM_SEED_PROVISIONAL_SOURCE_INVALID')
        fresh = _authority(verify_authority, item)
        facts = _input_facts(item)
        require(all(fresh.get(k) == v for k, v in facts.items())
            and fresh.get('expected_endpoint') == bar.bar_end.isoformat()
            and all(_sha(fresh.get(k)) for k in ('source_manifest_sha256', 'owner_sha256', 'session_sha256', 'quality_sha256'))
            and fresh == item.source_proof, 'WARM_SEED_INPUT_AUTHORITY_INVALID')
        if item.source_kind == 'completed_live':
            require(_sha(fresh.get('recovery_plan_sha256')) and _sha(fresh.get('recovery_readback_sha256')),
                'WARM_SEED_LIVE_RECOVERY_UNVERIFIED')
        old_owner = (checkpoint.physical_contract, checkpoint.owner_segment_id, checkpoint.calculation_segment_id)
        new_owner = (bar.physical_contract, bar.segment_id, product.calculation_segment_id)
        rollover = old_owner != new_owner
        require(type(fresh.get('rollover')) is bool and fresh['rollover'] == rollover, 'WARM_SEED_ROLLOVER_UNVERIFIED')
        # Authoritative Session expected endpoint must explicitly bind the preceding
        # frontier. One row's coverage cannot stand in for a no-gap range proof.
        require(fresh.get('previous_watermark') == previous.isoformat()
            and fresh.get('expected_endpoints') == [bar.bar_end.isoformat()], 'WARM_SEED_OBSERVATION_GAP')
        if rollover:
            rollovers.append({'previous': list(old_owner), 'next': list(new_owner), 'at': bar.bar_end.isoformat()})
        state, frame, _ = replay_step(product_identity,
            seed_replay_state() if rollover else checkpoint.strategy_state, product)
        require(frame is not None, 'WARM_SEED_DUPLICATE_INPUT')
        fingerprint = strategy_input_fingerprint({'source_bar_sha256': product.source_bar_sha256,
            'bar': _wire(bar), 'physical_contract': bar.physical_contract, 'owner_segment_id': bar.segment_id,
            'calculation_segment_id': product.calculation_segment_id, 'source_kind': item.source_kind})
        checkpoint = AdapterCheckpoint(state, bar.bar_end, fingerprint, *new_owner, identity,
            ReferenceState.flat(identity, recording_start=start))
        previous = _aware(bar.bar_end)
        records.append({'facts': facts, 'authority': fresh})
    proof = {'version': VERSION, 'original_source_binding': deepcopy(baseline.binding),
        'original_manifest': deepcopy(baseline.saved_manifest),
        'fresh_original_range_manifest': deepcopy(fresh_snapshot.dependency_manifest),
        'baseline_authority': authority, 'inputs': records, 'rollovers': rollovers,
        'warm_step_count': len(inputs), 'zero_step_authority': zero_step_authority,
        'interval_authority': interval_authority,
        'cutoff': at.isoformat(), 'recording_start': start.isoformat(),
        'knowledge_at': known.isoformat(), 'stage': stage,
        'status': 'PENDING_WARMUP' if stage == 'provisional_canonical' else 'WARM_SEED_VERIFIED',
        'reference_reset': 'FLAT', 'natural_capture': False, 'first_seen': False,
        'input_chain_sha256': _hash(records)}
    return _result(identity, checkpoint, baseline.schema, proof, baseline.binding)


def _result(identity, checkpoint, schema, proof, original_binding):
    manifest = {'reader': VERSION, 'warm_seed_version': VERSION, 'proof': deepcopy(proof),
        'formula_versions': list(identity.formula_versions), 'reference_model_version': identity.reference_model_version}
    content = adapter_checkpoint_to_json(checkpoint, strategy_schema=schema)
    checkpoint_hash = sha256(content.encode()).hexdigest()
    seed_hash = _hash({'checkpoint_hash': checkpoint_hash, 'manifest': manifest})
    binding = {'kind': VERSION, 'stream_id': identity.stream_id,
        'revision_id': original_binding['revision_id'], 'seq': original_binding['seq'],
        'checkpoint_hash': checkpoint_hash, 'dependency_digest': manifest_sha256(manifest),
        'computed_through': checkpoint.computed_through.isoformat(), 'seed_hash': seed_hash,
        'original_source_binding': deepcopy(original_binding)}
    return MaterializedWarmSeed(identity, checkpoint, schema, manifest, binding, deepcopy(proof), seed_hash)


def materialize_fusion_warm_seed(identity: StreamIdentity, bases: tuple[MaterializedWarmSeed, ...],
        *, original_binding: dict, recording_start: datetime) -> MaterializedWarmSeed:
    require(len(bases) == 3 and {b.identity.strategy_code for b in bases}
        == {'newow_trend', 'newow_oscillation', 'newow_main_rise'}, 'WARM_SEED_FUSION_BASES_INVALID')
    require(all(b.schema == BASE_SCHEMA and b.proof.get('version') == VERSION for b in bases)
        and len({(b.identity.product, b.identity.frequency, b.proof['input_chain_sha256'],
            b.proof['cutoff'], b.proof['recording_start'], b.proof['stage'],
            b.proof['knowledge_at'], b.checkpoint.computed_through,
            b.checkpoint.physical_contract, b.checkpoint.owner_segment_id, b.checkpoint.calculation_segment_id)
            for b in bases}) == 1, 'WARM_SEED_FUSION_INPUT_CONFLICT')
    for base in bases:
        reconstructed = _result(base.identity, base.checkpoint, base.schema, base.proof,
            base.binding['original_source_binding'])
        require(reconstructed == base, 'WARM_SEED_FUSION_BASE_HASH_CONFLICT')
    first = bases[0]
    require(original_binding.get('stream_id') == identity.stream_id
        and original_binding.get('revision_id') and type(original_binding.get('seq')) is int
        and original_binding['seq'] > 0
        and _sha(original_binding.get('checkpoint_hash'))
        and _sha(original_binding.get('dependency_digest'))
        and isinstance(original_binding.get('computed_through'), str),
        'WARM_SEED_FUSION_LINEAGE_INVALID')
    expected = build_fusion_stream_identity(first.identity.product, first.identity.frequency,
        input_quality_policy=first.proof['original_manifest']['quality_policy'])
    require(identity == expected and _aware(recording_start).isoformat() == first.proof['recording_start'],
        'WARM_SEED_FUSION_IDENTITY_CONFLICT')
    checkpoint = replace(first.checkpoint, strategy_state=FusionReferenceReplayState(), stream=identity,
        reference_state=ReferenceState.flat(identity, recording_start=_aware(recording_start)))
    proof = {'version': VERSION, 'input_chain_sha256': first.proof['input_chain_sha256'],
        'cutoff': first.proof['cutoff'], 'recording_start': first.proof['recording_start'],
        'stage': first.proof['stage'], 'knowledge_at': first.proof['knowledge_at'],
        'status': first.proof['status'],
        'base_seeds': [b.binding for b in sorted(bases, key=lambda s: s.identity.strategy_code)],
        'base_proofs': [deepcopy(b.proof) for b in sorted(bases, key=lambda s: s.identity.strategy_code)],
        'reference_reset': 'FLAT', 'natural_capture': False, 'first_seen': False}
    return _result(identity, checkpoint, FUSION_SCHEMA, proof, original_binding)


def load_verified_warm_source(source_loader, session, source_id, *, lock, new_health):
    """Validate one freshly materialized source; conflict evidence stays caller-owned."""
    WARM_VERSION = VERSION
    seed = source_loader(session, source_id, lock=lock)
    require(isinstance(seed, MaterializedWarmSeed), "ORIGINAL_CONFLICT_WARM_SEED_UNVERIFIED")
    require(seed.identity.stream_id == source_id and seed.proof.get('version') == WARM_VERSION
            and seed.binding.get('kind') == WARM_VERSION
            and isinstance(seed.binding.get('original_source_binding'), dict), "ORIGINAL_CONFLICT_WARM_SEED_UNVERIFIED")
    reconstructed = _result(seed.identity, seed.checkpoint, seed.schema, seed.proof, seed.binding['original_source_binding'])
    require(seed == reconstructed, "ORIGINAL_CONFLICT_WARM_SEED_UNVERIFIED")
    stage, status = ('final_observation', 'WARM_SEED_VERIFIED') if new_health == 'READY' else ('provisional_canonical', 'PENDING_WARMUP')
    proofs = seed.proof.get('base_proofs') if seed.schema == 'newow_dual_fusion_reference_v1' else [seed.proof]
    require(seed.proof.get('stage') == stage and seed.proof.get('status') == status
            and isinstance(proofs, list) and len(proofs) == (3 if seed.schema == 'newow_dual_fusion_reference_v1' else 1),
            "ORIGINAL_CONFLICT_WARM_SEED_STAGE_INVALID")
    for proof in proofs:
        require(proof.get('version') == WARM_VERSION and proof.get('stage') == stage and proof.get('status') == status,
                "ORIGINAL_CONFLICT_WARM_SEED_STAGE_INVALID")
        if new_health == 'READY':
            require(proof.get('interval_authority', {}).get('remaining_endpoints_before_start') == [],
                    "ORIGINAL_CONFLICT_WARM_SEED_FRONTIER_INCOMPLETE")
    return seed.identity, seed.checkpoint, seed.schema, seed.manifest, seed.binding
