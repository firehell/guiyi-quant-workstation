"""Exact per-route activation over the existing reference transaction protocol."""
from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from sqlalchemy import select, text, func

from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceStream
from app.reference_trading.newow_bootstrap import _BorrowedSession
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
from guiyi_quant.reference_trading.subing_forward import seed_subing_forward
from guiyi_quant.subing_reference import _stream_identity, FORMULA_VERSIONS

POLICY = 'subing_physical_prefix_forward_v2'


def subing_identity(product, frequency, *, forward=False):
    if frequency not in FORMULA_VERSIONS:
        raise ValueError('SUBING_FREQUENCY_INVALID')
    identity = _stream_identity(product, frequency, frequency == '1d')
    return replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION,
        observation_policy_version=POLICY) if forward else identity


def plan_subing_activation(product, frequency, *, operational, start, expiry, now, host, environment):
    if product.lower() not in operational or not host or not environment:
        raise ValueError('SUBING_ACTIVATION_SCOPE_INVALID')
    if any(value.tzinfo is None for value in (start, expiry, now)) or not now < expiry <= start:
        raise ValueError('SUBING_ACTIVATION_TIME_INVALID')
    identity = subing_identity(product, frequency, forward=True)
    payload = dict(version=POLICY, product=identity.product, frequency=frequency,
        stream_id=identity.stream_id, recording_start=start.isoformat(), expires_at=expiry.isoformat(),
        host=host, environment=environment)
    return {**payload, 'plan_hash': manifest_sha256(payload)}


def apply_subing_activation(factory, plan, *, expected_plan_hash, operational, now):
    start = datetime.fromisoformat(plan['recording_start'])
    expiry = datetime.fromisoformat(plan['expires_at'])
    frozen = {key: value for key, value in plan.items() if key != 'plan_hash'}
    if expected_plan_hash != plan['plan_hash'] or manifest_sha256(frozen) != expected_plan_hash:
        raise RepositoryConflict('PLAN_HASH_CONFLICT')
    if plan['version'] != POLICY or plan['product'].lower() not in operational:
        raise RepositoryConflict('SUBING_ACTIVATION_SCOPE_INVALID')
    identity = subing_identity(plan['product'], plan['frequency'], forward=True)
    if identity.stream_id != plan['stream_id']:
        raise RepositoryConflict('SUBING_ACTIVATION_IDENTITY_INVALID')
    # One route is atomic, including its seed, activation and receipt. Scope
    # callers stop on unknown results and read back rather than blind retry.
    with factory() as session, session.begin():
        if session.get_bind().dialect.name == 'sqlite':
            session.execute(text('BEGIN IMMEDIATE'))
        if session.get_bind().dialect.name == 'postgresql':
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            key = int.from_bytes(sha256(identity.stream_id.encode()).digest()[:8], 'big', signed=True)
            session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
        existing = session.scalar(select(ReferenceStream).where(ReferenceStream.stream_id == identity.stream_id).with_for_update())
        if existing is not None:
            raise RepositoryConflict('SUBING_ACTIVATION_ALREADY_EXISTS_READBACK_REQUIRED')
        conflict = session.scalar(select(ReferenceStream.stream_id).where(
            func.lower(ReferenceStream.product) == identity.product.lower(),
            ReferenceStream.frequency == identity.frequency,
            func.replace(ReferenceStream.strategy_code, '-', '_') == 'subing_reference',
            ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value,
            ReferenceStream.enabled.is_(True)).limit(1))
        if conflict is not None:
            raise RepositoryConflict('SUBING_ACTIVATION_ROUTE_ALREADY_ENABLED')
        if now >= start or now > expiry:
            raise RepositoryConflict('PLAN_EXPIRED')
        def borrowed():
            return _BorrowedSession(session)
        repository = ReferenceRepository(borrowed)
        stored = repository.ensure_stream(identity)
        manifest = {'subing_activation_v2': frozen, 'plan_hash': expected_plan_hash}
        revision = repository.create_revision(identity.stream_id, stored.row_version, manifest_sha256(manifest))
        checkpoint = AdapterCheckpoint(seed_subing_forward(), stream=identity,
            reference_state=ReferenceState.flat(identity, recording_start=start))
        encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema='subing_forward_v1')
        repository.stage_seed_chunk(revision, SeedChunk('seed:'+expected_plan_hash, 0, 1,
            sha256(encoded.encode()).hexdigest(), encoded))
        repository.seal_seed(revision, manifest, checkpoint, 'subing_forward_v1')
        activation = ForwardActivation(borrowed)
        ready = activation.plan(identity.stream_id, revision, host=plan['host'], environment=plan['environment'],
            recording_start=start, expires_at=expiry, budget={'max_pending_keys': 360, 'max_units_per_round': 32},
            recovery_policy='interrupt_and_restart')
        receipt = activation.apply(ready, expected_plan_hash=ready.plan_hash, now=now)
        return {'stream_id': identity.stream_id, 'revision_id': revision, 'receipt_id': receipt,
            'activation_plan_hash': ready.plan_hash, 'plan_hash': expected_plan_hash}
