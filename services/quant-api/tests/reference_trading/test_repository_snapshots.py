from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import func, select

from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import (
    ActionKind,
    ReferenceAction,
    ReferenceState,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

from app.reference_trading.contracts import PreparedBatch, SnapshotIdentity, SourceAction
from app.reference_trading.models import ReferenceActionRow
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_repository import AT, _digest, _open_batch, _seed_repository, _stream


def _close_batch(repository, stream, revision, manifest, token):
    _loaded, opened = repository.load_checkpoint(stream.stream_id, revision)
    close_at = datetime(2026, 9, 20, 7, tzinfo=UTC)
    close = ReferenceAction(
        stream=stream, source_action_id="clear-1", physical_contract="RB2610",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=close_at, trading_day=date(2026, 9, 20), sequence=0,
        kind=ActionKind.CLOSE, reference_price=Decimal("3510.987654321"),
        entry_action_id="build-1",
    )
    transition = reduce_reference(opened.reference_state, actions=(close,))
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), opened.computed_through, "fingerprint-2", "RB2610",
        "owner-1", "calc-1", stream, transition.state,
    )
    return PreparedBatch(
        stream.stream_id, revision, "bar-2", token, manifest,
        (SourceAction(close),), (transition,), checkpoint,
        "newow_product_replay_v1", {"bar": "fixture-2"},
    )


def test_old_snapshot_stays_open_after_new_close_and_cutoff_hides_future_exit() -> None:
    repository, _factory, stream, revision, manifest, seed = _seed_repository()
    opened = repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _checkpoint = repository.load_checkpoint(stream.stream_id, revision)
    published = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest)
    )
    # publish checks the dependency digest, not checkpoint hash
    assert published.seq == opened.seq
    token, _checkpoint = repository.load_checkpoint(stream.stream_id, revision)
    closed = repository.commit_batch(
        token, _close_batch(repository, stream, revision, manifest, token)
    )

    old_page = repository.read_trades(
        SnapshotIdentity(stream.stream_id, revision, opened.seq),
        cutoff=datetime(2026, 9, 19, 23, tzinfo=UTC), limit=20,
    )
    new_page = repository.read_trades(
        SnapshotIdentity(stream.stream_id, revision, closed.seq),
        cutoff=datetime(2026, 9, 20, 23, tzinfo=UTC), limit=20,
    )
    cutoff_page = repository.read_trades(
        SnapshotIdentity(stream.stream_id, revision, closed.seq),
        cutoff=datetime(2026, 9, 19, 23, tzinfo=UTC), limit=20,
    )

    assert old_page.items[0].status.value == "OPEN"
    assert old_page.items[0].mark_reference_price == Decimal("3501.123456789")
    assert new_page.items[0].status.value == "CLOSED"
    assert new_page.items[0].exit_reference_price == Decimal("3510.987654321")
    assert cutoff_page.items[0].status.value == "OPEN"
    assert cutoff_page.items[0].exit_bar_end is None


def test_action_keyset_pagination_has_explicit_end() -> None:
    repository, _factory, stream, revision, manifest, seed = _seed_repository()
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    snapshot = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest),
    )

    first = repository.read_actions(snapshot, cutoff=None, limit=1)

    assert [item.source_action_id for item in first.items] == ["build-1"]
    assert first.next_key is None


def test_candidate_snapshot_is_not_readable_and_invalidated_snapshot_fails() -> None:
    repository, _factory, stream, revision, manifest, seed = _seed_repository()
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    candidate = SnapshotIdentity(stream.stream_id, revision, token.seq)
    with __import__("pytest").raises(RepositoryConflict, match="SNAPSHOT_NOT_PUBLISHED"):
        repository.read_trades(candidate, cutoff=None, limit=20)

    snapshot = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest)
    )
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.invalidate_revision(stream.stream_id, revision, token.row_version, "source changed")
    with __import__("pytest").raises(RepositoryConflict, match="SNAPSHOT_INVALIDATED"):
        repository.read_trades(snapshot, cutoff=None, limit=20)


def test_forward_trade_requires_observed_at_before_cutoff() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.reference_trading.contracts import SeedChunk
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = ReferenceRepository(sessionmaker(engine, expire_on_commit=False))
    historical = _stream()
    stream = replace(
        historical,
        recording_mode="forward_observation",
        observation_policy_version="forward-flat-v1",
    )
    stored = repository.ensure_stream(stream)
    manifest = {"live": "fixture-v1"}
    revision = repository.create_revision(stream.stream_id, stored.row_version, _digest(manifest))
    initial = ReferenceState.flat(stream, recording_start=AT)
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), stream=stream, reference_state=initial,
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    token = repository.seal_seed(
        revision, manifest, checkpoint, "newow_product_replay_v1"
    )
    action = ReferenceAction(
        stream=stream, source_action_id="observed-build", physical_contract="RB2610",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=AT, trading_day=date(2026, 9, 19), sequence=0,
        kind=ActionKind.OPEN_LONG, reference_price=Decimal("3500"),
    )
    transition = reduce_reference(initial, actions=(action,))
    next_checkpoint = AdapterCheckpoint(
        seed_replay_state(), None, None, "RB2610", "owner-1", "calc-1",
        stream, transition.state,
    )
    observed_at = AT + timedelta(hours=1)
    prepared = PreparedBatch(
        stream.stream_id, revision, "observed-bar", token, manifest,
        (SourceAction(action, observed_at=observed_at),), (transition,), next_checkpoint,
        "newow_product_replay_v1", {"live": "fixture"},
    )
    repository.commit_batch(token, prepared)
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    snapshot = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest)
    )

    assert repository.read_trades(
        snapshot, cutoff=AT + timedelta(minutes=30), limit=20
    ).items == ()
    assert len(repository.read_trades(
        snapshot, cutoff=AT + timedelta(hours=2), limit=20
    ).items) == 1


def test_same_bar_actions_use_stable_keyset_without_dropping_an_item() -> None:
    repository, _factory, stream, revision, manifest, seed = _seed_repository()
    actions = tuple(
        ReferenceAction(
            stream=stream, source_action_id=f"hint-{sequence}", physical_contract="RB2610",
            owner_segment_id="owner-1", calculation_segment_id="calc-1",
            bar_end=AT, trading_day=date(2026, 9, 19), sequence=sequence,
            kind=ActionKind.HINT, reference_price=Decimal("3500"),
        )
        for sequence in (0, 1)
    )
    transition = reduce_reference(ReferenceState.flat(stream), actions=actions)
    prepared = PreparedBatch(
        stream.stream_id, revision, "same-bar-hints", seed, manifest,
        tuple(SourceAction(action) for action in actions), (transition,),
        AdapterCheckpoint(
            seed_replay_state(), None, None, "RB2610", "owner-1", "calc-1",
            stream, transition.state,
        ),
        "newow_product_replay_v1", {"bar": "same-bar"},
    )
    repository.commit_batch(seed, prepared)
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    snapshot = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest),
    )

    first = repository.read_actions(snapshot, cutoff=None, limit=1)
    second = repository.read_actions(
        snapshot, cutoff=None, limit=1, after_key=first.next_key,
    )

    assert [item.source_action_id for item in first.items] == ["hint-0"]
    assert first.next_key is not None
    assert [item.source_action_id for item in second.items] == ["hint-1"]
    assert second.next_key is None


def test_forward_reprojection_reuses_the_immutable_source_action() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.reference_trading.contracts import SeedChunk

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    stream = replace(
        _stream(), recording_mode="forward_observation",
        observation_policy_version="forward-flat-v1",
    )
    stored = repository.ensure_stream(stream)
    manifest = {"live": "fixture-v1"}
    first_revision = repository.create_revision(
        stream.stream_id, stored.row_version, _digest(manifest),
    )
    seed_checkpoint = AdapterCheckpoint(
        seed_replay_state(), stream=stream,
        reference_state=ReferenceState.flat(stream, recording_start=AT),
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(first_revision, SeedChunk("seed", 0, 1, root, "seed"))
    token = repository.seal_seed(
        first_revision, manifest, seed_checkpoint, "newow_product_replay_v1",
    )
    action = ReferenceAction(
        stream=stream, source_action_id="observed-build", physical_contract="RB2610",
        owner_segment_id="owner-1", calculation_segment_id="calc-1",
        bar_end=AT, trading_day=date(2026, 9, 19), sequence=0,
        kind=ActionKind.OPEN_LONG, reference_price=Decimal("3500"),
    )
    transition = reduce_reference(seed_checkpoint.reference_state, actions=(action,))
    observed_at = AT + timedelta(minutes=5)
    first_batch = PreparedBatch(
        stream.stream_id, first_revision, "observed-build", token, manifest,
        (SourceAction(action, observed_at=observed_at),), (transition,),
        AdapterCheckpoint(
            seed_replay_state(), None, None, "RB2610", "owner-1", "calc-1",
            stream, transition.state,
        ),
        "newow_product_replay_v1", {"live": "first-projection"},
    )
    repository.commit_batch(token, first_batch)
    token, _ = repository.load_checkpoint(stream.stream_id, first_revision)
    repository.publish_revision(
        stream.stream_id, first_revision, token.row_version, _digest(manifest),
    )

    token, _ = repository.load_checkpoint(stream.stream_id, first_revision)
    second_revision = repository.create_revision(
        stream.stream_id, token.row_version, _digest(manifest),
    )
    repository.stage_seed_chunk(second_revision, SeedChunk("seed", 0, 1, root, "seed"))
    second_seed = repository.seal_seed(
        second_revision, manifest, seed_checkpoint, "newow_product_replay_v1",
    )
    second_transition = reduce_reference(seed_checkpoint.reference_state, actions=(action,))
    second_batch = PreparedBatch(
        stream.stream_id, second_revision, "reproject-build", second_seed, manifest,
        (SourceAction(
            action, observed_at=observed_at, origin_revision_id=first_revision,
        ),),
        (second_transition,),
        AdapterCheckpoint(
            seed_replay_state(), None, None, "RB2610", "owner-1", "calc-1",
            stream, second_transition.state,
        ),
        "newow_product_replay_v1", {"live": "second-projection"},
    )
    repository.commit_batch(second_seed, second_batch)
    second_token, _ = repository.load_checkpoint(stream.stream_id, second_revision)
    second_snapshot = repository.publish_revision(
        stream.stream_id, second_revision, second_token.row_version, _digest(manifest),
    )

    with factory() as session:
        action_count = session.scalar(select(func.count()).select_from(ReferenceActionRow))
    projected = repository.read_actions(second_snapshot, cutoff=None, limit=20)

    assert action_count == 1
    assert [item.source_action_id for item in projected.items] == ["observed-build"]
