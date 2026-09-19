from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import (
    ActionKind,
    CompletedReferenceBar,
    ReferenceAction,
    ReferenceState,
    StreamIdentity,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

from app.db.base import Base
from app.reference_trading.contracts import PreparedBatch, SeedChunk, SourceAction
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict


AT = datetime(2026, 9, 19, 7, tzinfo=UTC)


def _stream() -> StreamIdentity:
    return StreamIdentity(
        strategy_code="newow-trend", formula_versions=("v1",), profile_id="default",
        reference_model_version="reference-v2", futures_adaptation_version="futures-v1",
        product="RB", frequency="1d", series_kind="actual_dominant",
        recording_mode="historical_replay", observation_policy_version=None,
    )


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _seed_repository(*, fault=None):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = ReferenceRepository(factory, fault_injector=fault)
    stream = _stream()
    stored = repository.ensure_stream(stream)
    manifest = {"dataset_revision": "fixture-v1"}
    revision = repository.create_revision(stream.stream_id, stored.row_version, _digest(manifest))
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), stream=stream, reference_state=ReferenceState.flat(stream),
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    token = repository.seal_seed(
        revision, manifest, checkpoint, "newow_product_replay_v1"
    )
    return repository, factory, stream, revision, manifest, token


def _open_batch(stream, revision, manifest, token, *, batch_key="bar-1", evidence=None):
    action = ReferenceAction(
        stream=stream, source_action_id="build-1", physical_contract="RB2610",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=AT, trading_day=date(2026, 9, 19), sequence=0,
        kind=ActionKind.OPEN_LONG, reference_price=Decimal("3500.123456789"),
    )
    transition = reduce_reference(
        ReferenceState.flat(stream), actions=(action,),
        completed_bar=CompletedReferenceBar(
            "RB2610", "owner-1", "calc-1", AT, date(2026, 9, 19),
            Decimal("3501.123456789"),
        ),
    )
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), AT, "fingerprint-1", "RB2610", "owner-1", "calc-1",
        stream, transition.state,
    )
    return PreparedBatch(
        stream_id=stream.stream_id,
        revision_id=revision,
        batch_key=batch_key,
        expected=token,
        dependency_manifest=manifest,
        source_actions=(SourceAction(action),),
        transitions=(transition,),
        checkpoint=checkpoint,
        strategy_schema="newow_product_replay_v1",
        source_evidence=evidence or {"bar": "fixture-1"},
    )


def test_commit_batch_is_atomic_durable_and_idempotent_before_cas() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    prepared = _open_batch(stream, revision, manifest, token)

    committed = repository.commit_batch(token, prepared)
    assert committed.outcome == "committed"
    assert committed.seq == 2
    assert repository.commit_batch(token, prepared).outcome == "noop"
    assert repository.read_batch(stream.stream_id, revision, "bar-1") == committed
    loaded, checkpoint = repository.load_checkpoint(stream.stream_id, revision)
    assert loaded.seq == 2
    assert checkpoint.reference_state == prepared.checkpoint.reference_state


def test_same_batch_identity_with_changed_payload_conflicts() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    repository.commit_batch(token, _open_batch(stream, revision, manifest, token))

    with pytest.raises(RepositoryConflict, match="BATCH_CONTENT_CONFLICT"):
        repository.commit_batch(
            token,
            _open_batch(
                stream, revision, manifest, token,
                evidence={"bar": "same-identity-different-content"},
            ),
        )


def test_different_batch_with_stale_expected_fails_without_implicit_retry() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    repository.commit_batch(token, _open_batch(stream, revision, manifest, token))

    with pytest.raises(RepositoryConflict, match="STALE_CHECKPOINT"):
        repository.commit_batch(
            token, _open_batch(stream, revision, manifest, token, batch_key="bar-2")
        )
    assert repository.read_batch(stream.stream_id, revision, "bar-2") is None


def test_fault_after_actions_rolls_back_batch_actions_and_checkpoint() -> None:
    def fault(stage: str) -> None:
        if stage == "after_actions":
            raise RuntimeError("injected")

    repository, _factory, stream, revision, manifest, token = _seed_repository(fault=fault)
    with pytest.raises(RuntimeError, match="injected"):
        repository.commit_batch(token, _open_batch(stream, revision, manifest, token))

    assert repository.read_batch(stream.stream_id, revision, "bar-1") is None
    loaded, checkpoint = repository.load_checkpoint(stream.stream_id, revision)
    assert loaded == token
    assert checkpoint.reference_state.open_trade is None


def test_no_signal_sealed_batch_advances_checkpoint_without_inventing_actions() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    transition = reduce_reference(
        ReferenceState.flat(stream),
        completed_bar=CompletedReferenceBar(
            "RB2610", "owner-1", "calc-1", AT, date(2026, 9, 19), Decimal("3500"),
        ),
    )
    prepared = PreparedBatch(
        stream.stream_id, revision, "sealed-no-signal", token, manifest, (),
        (transition,),
        AdapterCheckpoint(
            seed_replay_state(), AT, "fingerprint-no-signal", "RB2610", "owner-1",
            "calc-1", stream, transition.state,
        ),
        "newow_product_replay_v1", {"bar": "no-signal"},
    )

    committed = repository.commit_batch(token, prepared)
    loaded, checkpoint = repository.load_checkpoint(stream.stream_id, revision)

    assert committed.seq == 2
    assert loaded.seq == 2
    assert checkpoint.reference_state.computed_through == AT
    assert checkpoint.reference_state.open_trade is None


def test_same_bar_unsealed_action_then_seal_is_two_legal_atomic_batches() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    action = ReferenceAction(
        stream=stream, source_action_id="build-unsealed", physical_contract="RB2610",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=AT, trading_day=date(2026, 9, 19), sequence=0,
        kind=ActionKind.OPEN_LONG, reference_price=Decimal("3500"),
    )
    unsealed = reduce_reference(ReferenceState.flat(stream), actions=(action,))
    first = PreparedBatch(
        stream.stream_id, revision, "unsealed-action", token, manifest,
        (SourceAction(action),), (unsealed,),
        AdapterCheckpoint(
            seed_replay_state(), None, None, "RB2610", "owner-1", "calc-1",
            stream, unsealed.state,
        ),
        "newow_product_replay_v1", {"bar": "unsealed"},
    )
    repository.commit_batch(token, first)
    next_token, restored = repository.load_checkpoint(stream.stream_id, revision)
    sealed = reduce_reference(
        restored.reference_state,
        completed_bar=CompletedReferenceBar(
            "RB2610", "owner-1", "calc-1", AT, date(2026, 9, 19), Decimal("3501"),
        ),
    )
    second = PreparedBatch(
        stream.stream_id, revision, "seal-same-bar", next_token, manifest, (),
        (sealed,),
        AdapterCheckpoint(
            seed_replay_state(), AT, "fingerprint-sealed", "RB2610", "owner-1",
            "calc-1", stream, sealed.state,
        ),
        "newow_product_replay_v1", {"bar": "sealed"},
    )

    result = repository.commit_batch(next_token, second)
    final_token, checkpoint = repository.load_checkpoint(stream.stream_id, revision)

    assert result.seq == 3
    assert final_token.seq == 3
    assert checkpoint.reference_state.computed_through == AT
    assert checkpoint.reference_state.open_trade is not None
