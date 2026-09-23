from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import threading
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

from app.db.base import Base
from app.reference_trading.contracts import SeedChunk, prove_dependency_append
from app.reference_trading.models import REFERENCE_TABLES
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository import _digest, _open_batch, _stream


pytestmark = pytest.mark.isolated_postgresql


@pytest.fixture
def reference_postgresql(isolated_postgres_engine: Engine):  # noqa: F811
    schema = "reference_repo_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    tables = [Base.metadata.tables[name] for name in REFERENCE_TABLES]
    Base.metadata.create_all(scoped, tables=tables)
    try:
        yield scoped
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _seed(engine, *, fault=None):
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = ReferenceRepository(factory, fault_injector=fault)
    stream = _stream()
    stored = repository.ensure_stream(stream)
    manifest = {"dataset_revision": "postgres-fixture-v1"}
    revision = repository.create_revision(stream.stream_id, stored.row_version, _digest(manifest))
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), stream=stream, reference_state=ReferenceState.flat(stream),
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    token = repository.seal_seed(
        revision, manifest, checkpoint, "newow_product_replay_v1"
    )
    return repository, stream, revision, manifest, token


def test_two_postgresql_writers_same_batch_commit_once_then_noop(reference_postgresql) -> None:
    repository, stream, revision, manifest, token = _seed(reference_postgresql)
    prepared = _open_batch(stream, revision, manifest, token)
    barrier = threading.Barrier(2)

    def commit():
        barrier.wait()
        return repository.commit_batch(token, prepared)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in (pool.submit(commit), pool.submit(commit))]

    assert sorted(result.outcome for result in outcomes) == ["committed", "noop"]
    assert {result.seq for result in outcomes} == {2}


def test_two_postgresql_writers_different_batches_only_one_advances(reference_postgresql) -> None:
    repository, stream, revision, manifest, token = _seed(reference_postgresql)
    barrier = threading.Barrier(2)

    def commit(batch_key):
        barrier.wait()
        try:
            return repository.commit_batch(
                token, _open_batch(stream, revision, manifest, token, batch_key=batch_key)
            ).outcome
        except RepositoryConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [
            future.result()
            for future in (pool.submit(commit, "bar-a"), pool.submit(commit, "bar-b"))
        ]

    assert sorted(outcomes) == ["STALE_CHECKPOINT", "committed"]


@pytest.mark.parametrize("stage", ["after_actions", "after_trades", "before_checkpoint", "before_commit"])
def test_postgresql_injected_failure_rolls_back_every_table(reference_postgresql, stage) -> None:
    def fault(current):
        if current == stage:
            raise RuntimeError("injected")

    repository, stream, revision, manifest, token = _seed(reference_postgresql, fault=fault)
    with pytest.raises(RuntimeError, match="injected"):
        repository.commit_batch(token, _open_batch(stream, revision, manifest, token))

    assert repository.read_batch(stream.stream_id, revision, "bar-1") is None
    schema = reference_postgresql.get_execution_options()["schema_translate_map"][None]
    with reference_postgresql.connect() as connection:
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".reference_actions')) == 0
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".reference_trades')) == 0
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".reference_marks')) == 0


def test_postgresql_numeric_round_trip_keeps_decimal_precision(reference_postgresql) -> None:
    repository, stream, revision, manifest, token = _seed(reference_postgresql)
    repository.commit_batch(token, _open_batch(stream, revision, manifest, token))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    snapshot = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest)
    )

    action = repository.read_actions(snapshot, cutoff=None, limit=20).items[0]
    trade = repository.read_trades(snapshot, cutoff=None, limit=20).items[0]
    assert str(action.reference_price) == "3500.123456789"
    assert str(trade.mark_reference_price) == "3501.123456789"


def test_postgresql_dependency_advance_updates_manifest_and_checkpoint_atomically(
    reference_postgresql,
) -> None:
    repository, stream, revision, manifest, token = _seed(reference_postgresql)
    next_manifest = {
        "dataset_revision": "postgres-fixture-v1",
        "partitions": [{"key": "tail", "sha256": "a" * 64}],
    }
    prepared = replace(
        _open_batch(stream, revision, next_manifest, token),
        dependency_advance=prove_dependency_append(
            manifest, next_manifest, appended_ranges=("tail",),
        ),
    )

    repository.commit_batch(token, prepared)
    state = repository.read_state(stream.stream_id, revision)

    assert state.dependency_manifest == next_manifest
    assert state.dependency_digest == prepared.dependency_advance.new_digest
    assert state.checkpoint.seq == 2


def test_postgresql_seed_seal_and_publish_share_stream_then_revision_lock_order(
    reference_postgresql,
) -> None:
    factory = sessionmaker(reference_postgresql, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    stream = _stream()
    stored = repository.ensure_stream(stream)
    manifest = {"dataset_revision": "lock-order-v1"}
    revision = repository.create_revision(
        stream.stream_id, stored.row_version, _digest(manifest),
    )
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), stream=stream, reference_state=ReferenceState.flat(stream),
    )
    stream_locked = threading.Event()
    release_seal = threading.Event()
    publish_started = threading.Event()

    def pause_after_stream_lock(stage: str) -> None:
        if stage == "after_stream_lock":
            stream_locked.set()
            assert release_seal.wait(timeout=5)

    sealing_repository = ReferenceRepository(
        factory, fault_injector=pause_after_stream_lock,
    )

    def seal():
        return sealing_repository.seal_seed(
            revision, manifest, checkpoint, "newow_product_replay_v1",
        )

    def publish():
        publish_started.set()
        return repository.publish_revision(
            stream.stream_id, revision, stored.row_version, _digest(manifest),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        seal_future = pool.submit(seal)
        assert stream_locked.wait(timeout=5)
        publish_future = pool.submit(publish)
        assert publish_started.wait(timeout=5)
        release_seal.set()
        token = seal_future.result(timeout=5)
        snapshot = publish_future.result(timeout=5)

    assert token.seq == 1
    assert snapshot.revision_id == revision
    assert snapshot.seq == 1
