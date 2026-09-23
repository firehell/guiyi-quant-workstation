from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

from app.db.base import Base
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceStream
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict


NOW = datetime(2026, 9, 23, 8, tzinfo=UTC)


def _setup(engine=None):
    from test_repository import _stream, _digest

    engine = engine or create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    identity = replace(
        _stream(), recording_mode=RecordingMode.FORWARD_OBSERVATION,
        observation_policy_version="completed-v1",
    )
    stored = repository.ensure_stream(identity)
    manifest = {"source": "fixture"}
    revision = repository.create_revision(identity.stream_id, stored.row_version, _digest(manifest))
    seed = AdapterCheckpoint(
        seed_replay_state(), stream=identity,
        reference_state=ReferenceState.flat(identity, recording_start=NOW + timedelta(seconds=1)),
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    repository.seal_seed(revision, manifest, seed, "newow_product_replay_v1")
    return factory, identity, revision


def test_plan_apply_and_disable_are_explicit_and_durable():
    factory, identity, revision = _setup()
    service = ForwardActivation(factory)
    plan = service.plan(
        identity.stream_id, revision, host="test-host", environment="isolated",
        recording_start=NOW + timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1), budget={"max_pending": 32},
    )
    with factory() as session:
        assert session.get(ReferenceStream, identity.stream_id).enabled is False
    receipt_id = service.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
    assert service.apply(
        plan, expected_plan_hash=plan.plan_hash, now=NOW + timedelta(minutes=2),
    ) == receipt_id
    with factory() as session:
        stream = session.get(ReferenceStream, identity.stream_id)
        assert stream.enabled and stream.activation_generation == 1
        assert session.get(ReferenceActivationReceipt, receipt_id).plan_hash == plan.plan_hash
    service.disable(identity.stream_id, expected_generation=1, now=NOW + timedelta(seconds=2))
    with factory() as session:
        stream = session.get(ReferenceStream, identity.stream_id)
        assert not stream.enabled and stream.activation_generation == 2
    with pytest.raises(RepositoryConflict, match="ACTIVATION_GENERATION_CONFLICT"):
        service.disable(identity.stream_id, expected_generation=1, now=NOW)


def test_expired_or_stale_plan_cannot_enable():
    factory, identity, revision = _setup()
    service = ForwardActivation(factory)
    plan = service.plan(
        identity.stream_id, revision, host="test-host", environment="isolated",
        recording_start=NOW + timedelta(seconds=1), expires_at=NOW + timedelta(minutes=1),
        budget={"max_pending": 32},
    )
    with pytest.raises(RepositoryConflict, match="PLAN_EXPIRED"):
        service.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW + timedelta(minutes=2))
    with factory() as session, session.begin():
        session.get(ReferenceStream, identity.stream_id).row_version += 1
    with pytest.raises(RepositoryConflict, match="ACTIVATION_DEPENDENCY_DRIFT"):
        service.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
