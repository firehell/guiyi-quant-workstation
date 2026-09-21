from __future__ import annotations

from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.reference_trading import ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.subing_reference import seed_subing_replay_state

from app.db.base import Base
from app.reference_trading.contracts import SeedChunk
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict


def _stream() -> StreamIdentity:
    return StreamIdentity(
        strategy_code="subing", formula_versions=("v1",), profile_id="default",
        reference_model_version="reference-v1", futures_adaptation_version="futures-v1",
        product="RB", frequency="1d", series_kind="actual_dominant",
        recording_mode="historical_replay", observation_policy_version=None,
    )


def _repository() -> ReferenceRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return ReferenceRepository(sessionmaker(engine, expire_on_commit=False))


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_seed_requires_every_chunk_and_restores_full_adapter_checkpoint() -> None:
    repository = _repository()
    stream = _stream()
    stored = repository.ensure_stream(stream)
    manifest = {"dataset_revision": "fixture-v1"}
    revision = repository.create_revision(stream.stream_id, stored.row_version, _digest(manifest))
    checkpoint = AdapterCheckpoint(
        strategy_state=seed_subing_replay_state(), stream=stream,
        reference_state=ReferenceState.flat(stream),
    )
    pieces = ("first", "second")
    root = sha256("".join(pieces).encode()).hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed-0", 0, 2, root, pieces[0]))

    with pytest.raises(RepositoryConflict, match="SEED_INCOMPLETE"):
        repository.seal_seed(revision, manifest, checkpoint, "subing_replay_v1")

    repository.stage_seed_chunk(revision, SeedChunk("seed-1", 1, 2, root, pieces[1]))
    token = repository.seal_seed(revision, manifest, checkpoint, "subing_replay_v1")
    repeated = repository.seal_seed(
        revision, manifest, checkpoint, "subing_replay_v1"
    )
    loaded_token, restored = repository.load_checkpoint(stream.stream_id, revision)

    assert repeated == token
    assert loaded_token == token
    assert restored == checkpoint


def test_seed_chunk_is_idempotent_but_same_identity_changed_content_conflicts() -> None:
    repository = _repository()
    stream = _stream()
    stored = repository.ensure_stream(stream)
    manifest = {"dataset_revision": "fixture-v1"}
    revision = repository.create_revision(stream.stream_id, stored.row_version, _digest(manifest))
    root = sha256(b"first").hexdigest()
    chunk = SeedChunk("seed-0", 0, 1, root, "first")

    repository.stage_seed_chunk(revision, chunk)
    repository.stage_seed_chunk(revision, chunk)
    with pytest.raises(RepositoryConflict, match="BATCH_CONTENT_CONFLICT"):
        repository.stage_seed_chunk(
            revision, SeedChunk("seed-0", 0, 1, sha256(b"changed").hexdigest(), "changed")
        )


def test_publish_is_compare_and_swap_and_keeps_candidate_invisible() -> None:
    repository = _repository()
    stream = _stream()
    stored = repository.ensure_stream(stream)
    manifest = {"dataset_revision": "fixture-v1"}
    digest = _digest(manifest)
    revision = repository.create_revision(stream.stream_id, stored.row_version, digest)
    checkpoint = AdapterCheckpoint(
        strategy_state=seed_subing_replay_state(), stream=stream,
        reference_state=ReferenceState.flat(stream),
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    repository.seal_seed(revision, manifest, checkpoint, "subing_replay_v1")

    with pytest.raises(RepositoryConflict, match="NO_ACTIVE_REVISION"):
        repository.load_checkpoint(stream.stream_id)

    snapshot = repository.publish_revision(stream.stream_id, revision, stored.row_version, digest)
    assert snapshot.revision_id == revision
    assert repository.load_checkpoint(stream.stream_id)[0].revision_id == revision
    with pytest.raises(RepositoryConflict, match="STALE_CHECKPOINT"):
        repository.publish_revision(stream.stream_id, revision, stored.row_version, digest)
