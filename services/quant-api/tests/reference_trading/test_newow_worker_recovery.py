from __future__ import annotations

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4
from threading import Event

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.contracts import SeedChunk
from app.reference_trading.forward_inputs import (
    ForwardInputUnavailable, capture_newow_canonical, capture_newow_live,
)
from app.reference_trading.models import ReferenceBatch, ReferenceStream
from app.reference_trading.recovery import capture_observation_gap, evaluate_observation_gap
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict, _digest
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketObservationSnapshot
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.product_identity import InputQualityPolicy
from guiyi_quant.newow.product_identity import (
    REFERENCE_MODEL_VERSION as NEWOW_REFERENCE_MODEL_VERSION,
    futures_adaptation_version,
)
from guiyi_quant.reference_trading import (
    ActionKind, RecordingMode, ReferenceAction, ReferenceState, StreamIdentity,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from app.reference_trading.contracts import CheckpointToken
from app.reference_trading.query import HistoricalReferenceQuery
from app.api import reference_trading as reference_api
from app.main import app
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401


@pytest.fixture
def forward_postgresql(isolated_postgres_engine: Engine):  # noqa: F811
    schema = "reference_p8_forward_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    try:
        yield scoped
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _setup(*, recovery_policy="block", engine=None):
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input("trend", "1d")
    bar = replace(case.bars[0], source_bar_sha256=sha256(b"canonical-bar").hexdigest())
    start = bar.bar.bar_end - timedelta(seconds=4)
    observed = bar.bar.bar_end + timedelta(seconds=5)
    identity = StreamIdentity(
        "newow_trend", case.identity.formula_versions, case.identity.profile_id,
        NEWOW_REFERENCE_MODEL_VERSION, futures_adaptation_version("1d"), case.identity.product,
        "1d", "actual_dominant", RecordingMode.FORWARD_OBSERVATION,
        "completed_canonical_v1",
    )
    engine = engine or create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    stored = repo.ensure_stream(identity)
    manifest = {"source": "isolated-canonical"}
    revision = repo.create_revision(identity.stream_id, stored.row_version, _digest(manifest))
    repo.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, sha256(b"seed").hexdigest(), "seed"))
    repo.seal_seed(
        revision, manifest, AdapterCheckpoint(
            seed_replay_state(), stream=identity,
            reference_state=ReferenceState.flat(identity, recording_start=start),
        ), "newow_product_replay_v1",
    )
    activation = ForwardActivation(factory)
    plan = activation.plan(
        identity.stream_id, revision, host="isolated-host", environment="isolated",
        recording_start=start, expires_at=start + timedelta(minutes=1),
        budget={"max_pending": 32}, recovery_policy=recovery_policy,
    )
    activation.apply(plan, expected_plan_hash=plan.plan_hash, now=start - timedelta(seconds=1))

    class Reader:
        calls = 0

        def load(self, _query, as_of):
            self.calls += 1
            return SimpleNamespace(
                frequency=ProductFrequency.DAILY, as_of=as_of,
                replay_bars=(bar,),
                sources={ProductFrequency.DAILY: SimpleNamespace(source_identity="owned")},
                input_quality_policy=InputQualityPolicy.V1,
                data_interruptions_by_frequency={},
            )

    return factory, repo, identity, revision, start, observed, Reader()


def _worker(repo, reader, observed):
    return build_forward_reference_worker(
        repository=repo, market_read=None, newow_reader=reader,
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *_: (),
        newow_capability_ready=lambda _identity: True,
        canonical_read_guard=nullcontext, now=lambda: observed, enabled=True,
    )


def test_newow_worker_restart_projects_pending_capture_once():
    factory, repo, identity, revision, start, observed, reader = _setup()
    _assert_restart_projects_pending_capture_once(factory, repo, identity, revision, start, observed, reader)


@pytest.mark.isolated_postgresql
def test_postgresql_restart_projects_typed_capture_once(
    forward_postgresql: Engine, monkeypatch,
) -> None:
    factory, repo, identity, revision, start, observed, reader = _setup(engine=forward_postgresql)
    _assert_restart_projects_pending_capture_once(
        factory, repo, identity, revision, start, observed, reader,
    )
    # Exercise the actual HTTP adapter over the independently committed rows.
    with factory() as session:
        assert HistoricalReferenceQuery._registered(session.get(ReferenceStream, identity.stream_id))
    monkeypatch.setattr(reference_api, "_query", HistoricalReferenceQuery(factory))
    with factory() as session:
        batches_before_get = session.query(ReferenceBatch).count()
    day = observed.date().isoformat()
    response = TestClient(app).get(
        f"/api/v1/reference-trading/streams/{identity.stream_id}/signals",
        params={"since": day, "through": day, "cutoff": observed.isoformat()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["snapshot"]
    with factory() as session:
        assert session.query(ReferenceBatch).count() == batches_before_get


@pytest.mark.isolated_postgresql
def test_postgresql_disable_wins_before_inflight_worker_commit(
    forward_postgresql: Engine,
) -> None:
    factory, repo, identity, revision, start, observed, reader = _setup(engine=forward_postgresql)
    captured = capture_newow_canonical(
        reader, identity, revision_id=revision, generation=1, after=None,
        recording_start=start, now=observed, capability_ready=lambda _: True,
    )
    assert captured is not None
    capture_id = repo.capture_forward(captured)
    worker = _worker(repo, reader, observed)
    worker.scan()
    prepared = Event()
    disabled = Event()
    original_commit = repo.commit_batch

    def delayed_commit(*args, **kwargs):
        prepared.set()
        assert disabled.wait(10), "disable never completed"
        return original_commit(*args, **kwargs)

    repo.commit_batch = delayed_commit
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(worker.run_round)
        assert prepared.wait(10), "worker never prepared a commit"
        ForwardActivation(factory).disable(
            identity.stream_id, expected_generation=1, now=observed,
        )
        disabled.set()
        assert result.result(timeout=10) == 0
    fresh = ReferenceRepository(factory)
    token, _ = fresh.load_checkpoint(identity.stream_id, revision)
    assert token.seq == 1
    with factory() as session:
        capture_row = session.get(ReferenceBatch, capture_id)
        assert capture_row.outcome == "pending"
        assert capture_row.consumed_by_batch_id is None


@pytest.mark.isolated_postgresql
def test_postgresql_unknown_commit_reads_durable_receipt_without_replay(
    forward_postgresql: Engine,
) -> None:
    factory, repo, identity, revision, start, observed, reader = _setup(engine=forward_postgresql)
    captured = capture_newow_canonical(
        reader, identity, revision_id=revision, generation=1, after=None,
        recording_start=start, now=observed, capability_ready=lambda _: True,
    )
    assert captured is not None
    capture_id = repo.capture_forward(captured)
    original_commit = repo.commit_batch
    calls = 0

    def lost_ack(*args, **kwargs):
        nonlocal calls
        calls += 1
        original_commit(*args, **kwargs)
        raise OSError("simulated acknowledgment loss after commit")

    repo.commit_batch = lost_ack
    worker = _worker(repo, reader, observed)
    worker.scan()
    assert worker.run_round() == 1
    assert calls == 1
    fresh = ReferenceRepository(factory)
    token, _ = fresh.load_checkpoint(identity.stream_id, revision)
    assert token.seq == 2
    assert fresh.read_pending_capture(identity.stream_id) is None
    with factory() as session:
        assert session.get(ReferenceBatch, capture_id).consumed_by_batch_id is not None


def _assert_restart_projects_pending_capture_once(
    factory, repo, identity, revision, start, observed, reader,
):
    captured = capture_newow_canonical(
        reader, identity, revision_id=revision, generation=1, after=None,
        recording_start=start, now=observed, capability_ready=lambda _: True,
    )
    assert captured is not None and captured.observed_at == observed
    capture_id = repo.capture_forward(captured)
    reader.calls = 0
    restarted = _worker(repo, reader, observed)
    restarted.scan()
    assert restarted.run_round() == 1
    assert reader.calls == 0
    assert repo.read_pending_capture(identity.stream_id) is None
    token, checkpoint = repo.load_checkpoint(identity.stream_id)
    assert token.seq == 2 and checkpoint.computed_through == captured.bar_end
    with factory() as session:
        row = session.get(ReferenceBatch, capture_id)
        assert row.consumed_by_batch_id is not None

    again = _worker(repo, reader, observed)
    again.scan()
    assert again.run_round() == 0
    assert repo.load_checkpoint(identity.stream_id)[0].seq == 2


def test_newow_hourly_capture_requires_completed_live_and_capability():
    _factory, _repo, daily_identity, _revision, start, observed, _reader = _setup()
    identity = replace(daily_identity, frequency="60m")
    bar = CanonicalBar(
        observed - timedelta(seconds=5), observed.date(),
        3500, 3510, 3490, 3500, 100, None, None,
    )

    class Read:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=bar.trading_day,
                contract="RB2610", bars=(bar,),
            )

    with pytest.raises(ForwardInputUnavailable, match="NEWOW_CAPABILITY_CLOSED"):
        capture_newow_live(
            Read(), identity, revision_id="revision", generation=1,
            after=start, now=observed, wake_kind="scan",
            owner_segments=lambda *_: ("owner", "calc"),
            expected_endpoints=lambda *_: (bar.bar_end,),
            capability_ready=lambda _: False,
        )
    capture = capture_newow_live(
        Read(), identity, revision_id="revision", generation=1,
        after=start, now=observed, wake_kind="scan",
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *_: (bar.bar_end,),
        capability_ready=lambda _: True,
    )
    assert capture.source_kind == "completed_live"
    assert capture.observed_at == observed

    class MissedRead:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=bar.trading_day,
                contract="RB2610", bars=(replace(bar, bar_end=bar.bar_end - timedelta(hours=1)), bar),
            )

    with pytest.raises(ForwardInputUnavailable, match="OBSERVATION_GAP"):
        capture_newow_live(
            MissedRead(), identity, revision_id="revision", generation=1,
            after=start, now=observed, wake_kind="scan",
            owner_segments=lambda *_: ("owner", "calc"),
            expected_endpoints=lambda *_: (bar.bar_end,),
            capability_ready=lambda _: True,
        )

    class UnavailableRead:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="unavailable", trading_day=bar.trading_day,
                contract=None, bars=(),
            )

    with pytest.raises(ForwardInputUnavailable, match="LIVE_SOURCE_UNAVAILABLE"):
        capture_newow_live(
            UnavailableRead(), identity, revision_id="revision", generation=1,
            after=start, now=observed, wake_kind="scan",
            owner_segments=lambda *_: ("owner", "calc"),
            expected_endpoints=lambda *_: (bar.bar_end,),
            capability_ready=lambda _: True,
        )


def test_canonical_scan_blocks_uncaptured_multi_bar_gap():
    _factory, _repo, identity, revision, start, observed, reader = _setup()
    original_load = reader.load

    def two_bars(query, as_of):
        read = original_load(query, as_of)
        first = read.replay_bars[0]
        second = replace(
            first,
            bar=replace(
                first.bar,
                bar_end=first.bar.bar_end + timedelta(days=1),
                trading_day=first.bar.trading_day + timedelta(days=1),
            ),
            source_bar_sha256=sha256(b"second-canonical-bar").hexdigest(),
        )
        return SimpleNamespace(
            **{**vars(read), "replay_bars": (first, second)},
        )

    reader.load = two_bars
    with pytest.raises(ForwardInputUnavailable, match="OBSERVATION_GAP"):
        capture_newow_canonical(
            reader, identity, revision_id=revision, generation=1, after=None,
            recording_start=start, now=observed + timedelta(days=1, seconds=1),
            capability_ready=lambda _: True,
        )


def test_approved_gap_recovery_is_durable_and_restartable():
    _factory, repo, identity, _revision, _start, observed, reader = _setup(
        recovery_policy="interrupt_and_restart",
    )
    original_load = reader.load

    def two_bars(query, as_of):
        read = original_load(query, as_of)
        first = read.replay_bars[0]
        second = replace(
            first,
            bar=replace(first.bar,
                        bar_end=first.bar.bar_end + timedelta(days=1),
                        trading_day=first.bar.trading_day + timedelta(days=1)),
            source_bar_sha256=sha256(b"second-canonical-bar").hexdigest(),
        )
        return SimpleNamespace(**{**vars(read), "replay_bars": (first, second)})

    reader.load = two_bars
    detected = observed + timedelta(days=1, seconds=1)
    worker = _worker(repo, reader, detected)
    worker.scan()
    outcome = worker.run_round()
    assert outcome == 1, worker.health().blocked
    token, checkpoint = repo.load_checkpoint(identity.stream_id)
    assert token.seq == 2
    assert checkpoint.computed_through == detected
    assert checkpoint.reference_state.open_trade is None
    assert repo.read_pending_capture(identity.stream_id) is None
    restarted = _worker(repo, reader, detected + timedelta(seconds=1))
    restarted.scan()
    assert restarted.run_round() == 0
    assert repo.load_checkpoint(identity.stream_id)[0].seq == 2
    original = original_load

    def resumed_bar(query, as_of):
        read = original(query, as_of)
        first = read.replay_bars[0]
        resumed = replace(
            first,
            bar=replace(
                first.bar, bar_end=first.bar.bar_end + timedelta(days=2),
                trading_day=first.bar.trading_day + timedelta(days=2),
            ),
            source_bar_sha256=sha256(b"resumed-canonical-bar").hexdigest(),
        )
        return SimpleNamespace(**{**vars(read), "replay_bars": (resumed,)})

    reader.load = resumed_bar
    resumed_observed = detected + timedelta(days=1, seconds=1)
    later = _worker(repo, reader, resumed_observed)
    later.scan()
    assert later.run_round() == 1, later.health().blocked
    final_token, final_checkpoint = repo.load_checkpoint(identity.stream_id)
    assert final_token.seq == 3
    assert final_checkpoint.computed_through > detected
    assert final_checkpoint.reference_state.open_trade is None


def test_gap_recovery_interrupts_open_without_exit_price():
    _factory, _repo, identity, revision, start, observed, _reader = _setup(
        recovery_policy="interrupt_and_restart",
    )
    entry = ReferenceAction(
        identity, "observed-entry", "RB2610", "owner", "calc",
        start, start.date(), 0, ActionKind.OPEN_LONG, Decimal("3500"),
    )
    opened = reduce_reference(
        ReferenceState.flat(identity, recording_start=start), actions=(entry,),
        completed_bar_end=start, completed_trading_day=start.date(),
        completed_reference_price=Decimal("3500"),
    )
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), start, "entry-fingerprint", "RB2610", "owner",
        "calc", identity, opened.state,
    )
    capture = capture_observation_gap(
        identity, revision_id=revision, generation=1,
        previous_watermark=start, observed_at=observed,
        reason="OBSERVATION_GAP", trading_day=start.date() + timedelta(days=1),
        endpoints=(start + timedelta(seconds=1),),
    )
    token = CheckpointToken(identity.stream_id, revision, 2, 2, sha256(b"open").hexdigest())
    prepared = evaluate_observation_gap(
        token, checkpoint,
        {**capture.evidence(), "capture_id": "capture-id"},
        dependency_manifest={"source": "fixture"},
    )
    trade = prepared.transitions[0].changed_trades[0]
    assert trade.status.value == "OBSERVATION_INTERRUPTED"
    assert trade.exit_reference_price is None
    assert trade.reference_return is None
    assert prepared.checkpoint.reference_state.open_trade is None
    assert prepared.source_evidence["presentation_v1"]["points"][0]["trading_day"] == (
        start.date() + timedelta(days=1)
    ).isoformat()


def test_default_block_policy_rejects_gap_capture():
    _factory, repo, identity, revision, start, observed, _reader = _setup()
    capture = capture_observation_gap(
        identity, revision_id=revision, generation=1,
        previous_watermark=start, observed_at=observed,
        reason="OBSERVATION_GAP", trading_day=start.date(),
        endpoints=(start + timedelta(seconds=1),),
    )
    with pytest.raises(RepositoryConflict, match="RECOVERY_POLICY_NOT_APPROVED"):
        repo.capture_forward(capture)


@pytest.mark.parametrize("frequency", ["1d", "1w"])
def test_newow_canonical_capture_uses_existing_mds_reader(frequency):
    from newow.product_fixtures import ProductCases

    cases = ProductCases()
    reader, query, _mds = cases.paged_reader(
        prefix_bars=12, page_size=20, frequency=frequency,
    )
    read = reader.load(query, cases.as_of)
    latest = read.replay_bars[-1]
    product_identity = build_product_identity(
        "rb", "trend", frequency, input_quality_policy=read.input_quality_policy,
    )
    stream = StreamIdentity(
        "newow_trend", product_identity.formula_versions,
        product_identity.profile_id, "newow_reference_v3", "newow_futures_v1",
        "rb", frequency, "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "completed_canonical_v1",
    )
    capture = capture_newow_canonical(
        reader, stream, revision_id="revision", generation=1,
        after=None, recording_start=latest.bar.bar_end,
        now=cases.as_of, capability_ready=lambda _: True,
    )
    assert capture is not None
    assert capture.bar_end == latest.bar.bar_end
    assert capture.observed_at == cases.as_of
    assert capture.input_payload["source_bar_sha256"] == latest.source_bar_sha256
    assert capture.input_payload["source_identity"] == latest.bar.source_identity
