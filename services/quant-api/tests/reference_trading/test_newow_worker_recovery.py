from __future__ import annotations

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import os
import subprocess
import sys
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
    ForwardInputUnavailable, capture_htdy_live, capture_newow_canonical,
    capture_newow_live, capture_subing_live,
)
from app.reference_trading.models import ReferenceActionRow, ReferenceBatch, ReferenceStream
from app.reference_trading.newow_forward import _whole_number
from app.reference_trading.recovery import capture_observation_gap, evaluate_observation_gap
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict, _digest
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketObservationSnapshot, MarketReadWindow
from guiyi_quant.newow.product_adapters import replay_step, seed_replay_state
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


@pytest.mark.parametrize("raw, expected", [("100", 100), ("100.000000000000000000", 100)])
def test_forward_quantity_accepts_integral_decimal_encoding(raw, expected):
    assert _whole_number(raw) == expected


@pytest.mark.parametrize("raw", ["100.5", "NaN", "Infinity", "not-a-number"])
def test_forward_quantity_rejects_nonintegral_or_invalid_encoding(raw):
    with pytest.raises(ValueError, match="NEWOW_CAPTURE_BAR_INVALID"):
        _whole_number(raw)


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


def _setup(*, recovery_policy="block", engine=None, strategy="trend", frequency="1d"):
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input(strategy, frequency)
    warmup = 50 if strategy == "main_rise" else 0
    seed_state = seed_replay_state()
    for previous in case.bars[:warmup]:
        seed_state, _frame, _diagnostics = replay_step(case.identity, seed_state, previous)
    bar = replace(case.bars[warmup], source_bar_sha256=sha256(b"canonical-bar").hexdigest())
    start = bar.bar.bar_end - timedelta(seconds=4)
    observed = bar.bar.bar_end + timedelta(seconds=5)
    identity = StreamIdentity(
        f"newow_{strategy}", case.identity.formula_versions, case.identity.profile_id,
        NEWOW_REFERENCE_MODEL_VERSION, futures_adaptation_version(frequency), case.identity.product,
        frequency, "actual_dominant", RecordingMode.FORWARD_OBSERVATION,
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
            seed_state, stream=identity,
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
                frequency=ProductFrequency(frequency), as_of=as_of,
                replay_bars=(bar,),
                sources={ProductFrequency(frequency): SimpleNamespace(source_identity="owned")},
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
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1d", "1w"])
def test_postgresql_all_newow_canonical_forward_families(
    forward_postgresql: Engine, strategy: str, frequency: str,
) -> None:
    factory, repo, identity, revision, start, observed, reader = _setup(
        engine=forward_postgresql, strategy=strategy, frequency=frequency,
    )
    _assert_restart_projects_pending_capture_once(
        factory, repo, identity, revision, start, observed, reader,
    )
    with factory() as session:
        assert HistoricalReferenceQuery._registered(session.get(ReferenceStream, identity.stream_id))
    with factory() as session:
        calculation = session.query(ReferenceBatch).filter_by(
            stream_id=identity.stream_id, kind="calculation",
        ).one()
        assert calculation.source_evidence["presentation_v1"]["points"]
    signals = HistoricalReferenceQuery(factory).signals(
        identity.stream_id, since=observed.date(), through=observed.date(),
        cutoff=observed,
    )
    assert signals["snapshot"]


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
def test_postgresql_all_newow_hourly_forward_families(
    forward_postgresql: Engine, strategy: str,
) -> None:
    factory, repo, identity, revision, _start, observed, reader = _setup(
        engine=forward_postgresql, strategy=strategy, frequency="60m",
    )
    product_bar = reader.load(None, observed).replay_bars[0].bar
    bar = CanonicalBar(
        product_bar.bar_end, product_bar.trading_day,
        product_bar.open, product_bar.high, product_bar.low, product_bar.close,
        Decimal(product_bar.volume), None, Decimal(product_bar.open_interest),
    )

    class MarketRead:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=bar.trading_day,
                contract=product_bar.physical_contract, bars=(bar,),
            )

    capture = capture_newow_live(
        MarketRead(), identity, revision_id=revision, generation=1, after=None,
        now=observed, wake_kind="scan",
        owner_segments=lambda *_: (product_bar.segment_id, product_bar.segment_id),
        expected_endpoints=lambda *_: (bar.bar_end,),
        capability_ready=lambda _: True,
    )
    assert capture is not None and capture.source_kind == "completed_live"
    capture_id = repo.capture_forward(capture)
    restarted = _worker(repo, reader, observed)
    restarted.wake(identity.stream_id)
    assert restarted.run_round() == 1, restarted.health().blocked
    fresh = ReferenceRepository(factory)
    assert fresh.load_checkpoint(identity.stream_id, revision)[0].seq == 2
    assert fresh.read_pending_capture(identity.stream_id) is None
    with factory() as session:
        row = session.get(ReferenceBatch, capture_id)
        assert row.consumed_by_batch_id is not None
        calculation = session.query(ReferenceBatch).filter_by(
            stream_id=identity.stream_id, kind="calculation",
        ).one()
        assert calculation.source_evidence["presentation_v1"]["points"]


def _setup_other_forward_family(engine, identity, strategy_state, strategy_schema, start):
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    stored = repo.ensure_stream(identity)
    manifest = {"source": "isolated-live"}
    revision = repo.create_revision(identity.stream_id, stored.row_version, _digest(manifest))
    repo.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, sha256(b"seed").hexdigest(), "seed"))
    repo.seal_seed(
        revision, manifest, AdapterCheckpoint(
            strategy_state, stream=identity,
            reference_state=ReferenceState.flat(identity, recording_start=start),
        ), strategy_schema,
    )
    # This acceptance exists only inside the disposable fixture. It does not
    # approve the HTDY model for any product or Runtime environment.
    model_acceptance_id = "isolated-fixture-only" if identity.strategy_code == "htdy" else None
    accepted_models = frozenset({(
        model_acceptance_id, identity.reference_model_version,
        identity.observation_policy_version, identity.product, identity.frequency,
    )}) if model_acceptance_id else frozenset()
    activation = ForwardActivation(factory, accepted_models=accepted_models)
    plan = activation.plan(
        identity.stream_id, revision, host="isolated-host", environment="isolated",
        recording_start=start, expires_at=start + timedelta(minutes=1),
        budget={"max_pending": 32}, model_acceptance_id=model_acceptance_id,
        recovery_policy="block",
    )
    activation.apply(plan, expected_plan_hash=plan.plan_hash, now=start - timedelta(seconds=1))
    return factory, repo, revision


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("frequency", ["15m", "30m", "60m"])
def test_postgresql_subing_forward_capture_to_persisted_readback(
    forward_postgresql: Engine, frequency: str,
) -> None:
    from guiyi_quant.reference_trading.subing_forward import seed_subing_forward
    from guiyi_quant.subing_reference import FORMULA_VERSIONS, REFERENCE_MODEL_VERSION

    end = datetime(2026, 9, 23, 2, tzinfo=UTC)
    observed = end + timedelta(seconds=5)
    identity = StreamIdentity(
        "subing_reference", (FORMULA_VERSIONS[frequency],),
        f"subing_reference_{frequency}_v1", REFERENCE_MODEL_VERSION,
        "subing_actual_dominant_v1", "RB", frequency, "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "completed_live_v1",
    )
    factory, repo, revision = _setup_other_forward_family(
        forward_postgresql, identity, seed_subing_forward(),
        "subing_forward_v1", end - timedelta(seconds=4),
    )
    bar = CanonicalBar(end, end.date(), 3500, 3510, 3490, 3500, 100, None, 200)

    class MarketRead:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=bar.trading_day,
                contract="RB2610", bars=(bar,),
            )

    capture = capture_subing_live(
        MarketRead(), identity, revision_id=revision, generation=1, after=None,
        now=observed, wake_kind="scan",
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *_: (end,),
    )
    assert capture is not None
    capture_id = repo.capture_forward(capture)
    restarted = _worker(repo, object(), observed)
    restarted.wake(identity.stream_id)
    assert restarted.run_round() == 1, restarted.health().blocked
    assert ReferenceRepository(factory).load_checkpoint(identity.stream_id, revision)[0].seq == 2
    with factory() as session:
        assert session.get(ReferenceBatch, capture_id).consumed_by_batch_id is not None
        calculation = session.query(ReferenceBatch).filter_by(
            stream_id=identity.stream_id, kind="calculation",
        ).one()
        assert calculation.source_evidence["presentation_v1"]["points"]
        assert HistoricalReferenceQuery._registered(session.get(ReferenceStream, identity.stream_id))


@pytest.mark.isolated_postgresql
def test_postgresql_htdy_first_seen_capture_to_persisted_readback(
    forward_postgresql: Engine,
) -> None:
    from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION

    base = datetime(2026, 9, 23, 0, tzinfo=UTC)
    bars = tuple(CanonicalBar(
        base + timedelta(minutes=15 * index), base.date(),
        3500, 3510, 3490, 3500, 100, None, None,
    ) for index in range(32))
    end = bars[-1].bar_end
    observed = end + timedelta(seconds=5)
    identity = StreamIdentity(
        "htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", "RB", "15m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "latest_only_32_v1",
    )
    factory, repo, revision = _setup_other_forward_family(
        forward_postgresql, identity,
        HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        "htdy_first_seen_v1", end - timedelta(seconds=4),
    )

    class MarketRead:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=end.date(),
                contract="RB2610", bars=(bars[-1],),
            )

        def bars_until(self, _query, *, trading_day, end, limit):
            assert trading_day == base.date() and limit == 32
            return MarketReadWindow(
                symbol="RB", series_kind="actual_dominant", frequency="15m",
                trading_day=trading_day, contract="RB2610", cutoff=end,
                bars=bars, bar_contracts=("RB2610",) * 32,
            )

        def validate_alert_window(self, _window, *, context_bars):
            assert context_bars == 32

    capture = capture_htdy_live(
        MarketRead(), identity, revision_id=revision, generation=1, after=None,
        now=observed, wake_kind="live_event", event_bar_end=end,
        owner_segments=lambda *_: ("owner", "calc"),
    )
    assert capture is not None and capture.eligibility == "first_seen"
    capture_id = repo.capture_forward(capture)
    restarted = _worker(repo, object(), observed)
    restarted.wake(identity.stream_id)
    assert restarted.run_round() == 1, restarted.health().blocked
    assert ReferenceRepository(factory).load_checkpoint(identity.stream_id, revision)[0].seq == 2
    with factory() as session:
        assert session.get(ReferenceBatch, capture_id).consumed_by_batch_id is not None
        calculation = session.query(ReferenceBatch).filter_by(
            stream_id=identity.stream_id, kind="calculation",
        ).one()
        assert calculation.source_evidence["presentation_v1"]["points"][0]["value"]["first_seen"]
        assert HistoricalReferenceQuery._registered(session.get(ReferenceStream, identity.stream_id))


@pytest.mark.isolated_postgresql
def test_postgresql_htdy_successive_windows_preserve_first_seen_and_reject_repaint(
    forward_postgresql: Engine,
) -> None:
    from app.reference_trading.htdy import evaluate_htdy_capture
    from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION

    base = datetime(2026, 9, 23, 0, tzinfo=UTC)
    bars = tuple(CanonicalBar(
        base + timedelta(minutes=15 * index), base.date(),
        3500, 3510, 3490, 3500, 100, None, None,
    ) for index in range(34))
    identity = StreamIdentity(
        "htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", "RB", "15m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "latest_only_32_v1",
    )
    factory, repo, revision = _setup_other_forward_family(
        forward_postgresql, identity,
        HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        "htdy_first_seen_v1", bars[31].bar_end - timedelta(seconds=4),
    )

    class MarketRead:
        def __init__(self, window):
            self.window = window

        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=base.date(),
                contract="RB2610", bars=(self.window[-1],),
            )

        def bars_until(self, _query, *, trading_day, end, limit):
            assert trading_day == base.date() and end == self.window[-1].bar_end
            assert limit == 32
            return MarketReadWindow(
                symbol="RB", series_kind="actual_dominant", frequency="15m",
                trading_day=trading_day, contract="RB2610", cutoff=end,
                bars=self.window, bar_contracts=("RB2610",) * 32,
            )

        def validate_alert_window(self, _window, *, context_bars):
            assert context_bars == 32

    query = HistoricalReferenceQuery(factory)
    params = {"since": base.date(), "through": base.date(), "point_kind": "signal"}
    old_snapshot = None
    for index in (31, 32):
        end = bars[index].bar_end
        observed = end + timedelta(seconds=5)
        capture = capture_htdy_live(
            MarketRead(bars[index - 31:index + 1]), identity,
            revision_id=revision, generation=1,
            after=None if index == 31 else bars[index - 1].bar_end,
            now=observed, wake_kind="live_event", event_bar_end=end,
            owner_segments=lambda *_: ("owner", "calc"),
        )
        assert capture is not None
        repo.capture_forward(capture)
        worker = _worker(repo, object(), observed)
        worker.wake(identity.stream_id)
        assert worker.run_round() == 1, worker.health().blocked
        page = query.signals(identity.stream_id, **params)
        assert len(page["items"]) == index - 30
        if index == 31:
            old_snapshot = page["snapshot"]
            first_signal = page["items"][0]
            assert first_signal["value"]["first_seen"] is True
            assert first_signal["value"]["bar_end"] == end.isoformat()
            assert first_signal["value"]["observed_at"] == observed.isoformat()
        else:
            assert page["items"][0] == first_signal
    assert old_snapshot is not None
    assert query.signals(identity.stream_id, snapshot_token=old_snapshot, **params)["items"] == [first_signal]

    # A later window that rewrites an overlapping completed Bar is captured as
    # evidence but cannot be projected over the durable checkpoint.
    repainted = list(bars[2:34])
    repainted[5] = replace(repainted[5], close=Decimal(3501))
    end = bars[33].bar_end
    capture = capture_htdy_live(
        MarketRead(tuple(repainted)), identity, revision_id=revision, generation=1,
        after=bars[32].bar_end, now=end + timedelta(seconds=5),
        wake_kind="live_event", event_bar_end=end,
        owner_segments=lambda *_: ("owner", "calc"),
    )
    assert capture is not None
    repo.capture_forward(capture)
    pending = ReferenceRepository(factory).read_pending_capture(identity.stream_id)
    assert pending is not None
    token, checkpoint = ReferenceRepository(factory).load_checkpoint(identity.stream_id, revision)
    with pytest.raises(ValueError, match="OBSERVATION_GAP"):
        evaluate_htdy_capture(
            token, checkpoint, {**pending[1], "capture_id": pending[0]},
            dependency_manifest={"source": "isolated-live"},
        )
    worker = _worker(repo, object(), end + timedelta(seconds=5))
    worker.wake(identity.stream_id)
    assert worker.run_round() == 0
    assert worker.health().blocked
    assert ReferenceRepository(factory).load_checkpoint(identity.stream_id, revision)[0].seq == 3
    assert ReferenceRepository(factory).read_pending_capture(identity.stream_id) is not None
    assert len(query.signals(identity.stream_id, **params)["items"]) == 2
    assert query.signals(identity.stream_id, snapshot_token=old_snapshot, **params)["items"] == [first_signal]


@pytest.mark.isolated_postgresql
def test_postgresql_htdy_actual_buy_then_sell_reverses_durable_trade(
    forward_postgresql: Engine,
) -> None:
    from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION

    base = datetime(2026, 9, 23, 0, tzinfo=UTC)
    neutral = ("10", "11", "9", "10")
    buy = ("0.1", "10", "0.1", "0.1")
    sell = ("0.1", "40", "0.1", "30.025")
    prices = [neutral] * 29 + [buy] * 3 + [neutral] + [sell] * 3
    bars = tuple(CanonicalBar(
        base + timedelta(minutes=15 * index), base.date(),
        *(Decimal(value) for value in prices[index]), Decimal(100), None, None,
    ) for index in range(len(prices)))
    identity = StreamIdentity(
        "htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", "RB", "15m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "latest_only_32_v1",
    )
    factory, repo, revision = _setup_other_forward_family(
        forward_postgresql, identity,
        HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        "htdy_first_seen_v1", bars[31].bar_end - timedelta(seconds=4),
    )

    class MarketRead:
        def __init__(self, window):
            self.window = window

        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=base.date(),
                contract="RB2610", bars=(self.window[-1],),
            )

        def bars_until(self, _query, *, trading_day, end, limit):
            assert trading_day == base.date() and end == self.window[-1].bar_end and limit == 32
            return MarketReadWindow(
                symbol="RB", series_kind="actual_dominant", frequency="15m",
                trading_day=trading_day, contract="RB2610", cutoff=end,
                bars=self.window, bar_contracts=("RB2610",) * 32,
            )

        def validate_alert_window(self, _window, *, context_bars):
            assert context_bars == 32

    for index in range(31, 36):
        end = bars[index].bar_end
        observed = end + timedelta(seconds=5)
        capture = capture_htdy_live(
            MarketRead(bars[index - 31:index + 1]), identity,
            revision_id=revision, generation=1,
            after=None if index == 31 else bars[index - 1].bar_end,
            now=observed, wake_kind="live_event", event_bar_end=end,
            owner_segments=lambda *_: ("owner", "calc"),
        )
        assert capture is not None
        repo.capture_forward(capture)
        worker = _worker(repo, object(), observed)
        worker.wake(identity.stream_id)
        assert worker.run_round() == 1, worker.health().blocked

    with factory() as session:
        actions = session.query(ReferenceActionRow).filter_by(
            stream_id=identity.stream_id,
        ).order_by(ReferenceActionRow.bar_end, ReferenceActionRow.sequence).all()
    assert [action.kind for action in actions] == ["OPEN_LONG", "CLOSE", "OPEN_SHORT"]
    assert actions[1].entry_source_action_id == actions[0].source_action_id
    query = HistoricalReferenceQuery(factory)
    params = {"since": base.date(), "through": base.date()}
    signals = query.signals(identity.stream_id, point_kind="signal", **params)["items"]
    assert [item["value"]["observation_types"] for item in signals] == [
        ["buy"], [], [], [], ["sell"],
    ]
    summary = query.summary(identity.stream_id, **params)
    assert summary["closed_count"] == 1 and summary["open_count"] == 1


@pytest.mark.isolated_postgresql
def test_postgresql_htdy_actual_same_bar_conflict_stays_pending(
    forward_postgresql: Engine,
) -> None:
    from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION

    base = datetime(2026, 9, 23, 0, tzinfo=UTC)
    neutral = ("10", "11", "9", "10")
    conflict = ("0.1", "18", "0.1", "18")
    prices = [neutral] * 29 + [conflict] * 3
    bars = tuple(CanonicalBar(
        base + timedelta(minutes=15 * index), base.date(),
        *(Decimal(value) for value in prices[index]), Decimal(100), None, None,
    ) for index in range(32))
    end = bars[-1].bar_end
    identity = StreamIdentity(
        "htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", "RB", "15m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "latest_only_32_v1",
    )
    factory, repo, revision = _setup_other_forward_family(
        forward_postgresql, identity,
        HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        "htdy_first_seen_v1", end - timedelta(seconds=4),
    )

    class MarketRead:
        def observation_snapshot(self, _query, _after, _now):
            return MarketObservationSnapshot(
                state=None, source="realtime", trading_day=base.date(),
                contract="RB2610", bars=(bars[-1],),
            )

        def bars_until(self, _query, *, trading_day, end, limit):
            assert trading_day == base.date() and end == bars[-1].bar_end and limit == 32
            return MarketReadWindow(
                symbol="RB", series_kind="actual_dominant", frequency="15m",
                trading_day=trading_day, contract="RB2610", cutoff=end,
                bars=bars, bar_contracts=("RB2610",) * 32,
            )

        def validate_alert_window(self, _window, *, context_bars):
            assert context_bars == 32

    observed = end + timedelta(seconds=5)
    capture = capture_htdy_live(
        MarketRead(), identity, revision_id=revision, generation=1,
        after=None, now=observed, wake_kind="live_event", event_bar_end=end,
        owner_segments=lambda *_: ("owner", "calc"),
    )
    assert capture is not None
    repo.capture_forward(capture)
    worker = _worker(repo, object(), observed)
    worker.wake(identity.stream_id)
    assert worker.run_round() == 0
    assert worker.health().blocked
    assert ReferenceRepository(factory).read_pending_capture(identity.stream_id) is not None
    assert ReferenceRepository(factory).load_checkpoint(identity.stream_id, revision)[0].seq == 1


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


_CRASH_WORKER = """
import os
import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.reference_trading.repository import ReferenceRepository
from tests.reference_trading.test_newow_worker_recovery import _worker

url, schema, stream_id, observed, crash_at = sys.argv[1:]
engine = create_engine(url).execution_options(schema_translate_map={None: schema})
factory = sessionmaker(engine, expire_on_commit=False)
repo = ReferenceRepository(
    factory,
    fault_injector=lambda stage: os._exit(42)
    if stage == "before_commit" and crash_at == "before_commit" else None,
)
if crash_at == "after_commit":
    commit = repo.commit_batch
    def exit_after_commit(*args, **kwargs):
        commit(*args, **kwargs)
        os._exit(43)
    repo.commit_batch = exit_after_commit
worker = _worker(repo, object(), datetime.fromisoformat(observed))
worker.wake(stream_id)
worker.run_round()
sys.exit(99)
"""


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("crash_at,expected_exit,committed", [
    ("before_commit", 42, False),
    ("after_commit", 43, True),
])
def test_postgresql_process_crash_preserves_exact_capture_outcome(
    forward_postgresql: Engine, crash_at: str, expected_exit: int, committed: bool,
) -> None:
    factory, repo, identity, revision, start, observed, reader = _setup(engine=forward_postgresql)
    captured = capture_newow_canonical(
        reader, identity, revision_id=revision, generation=1, after=None,
        recording_start=start, now=observed, capability_ready=lambda _: True,
    )
    assert captured is not None
    capture_id = repo.capture_forward(captured)
    schema = forward_postgresql.get_execution_options()["schema_translate_map"][None]
    result = subprocess.run(
        [sys.executable, "-c", _CRASH_WORKER, str(forward_postgresql.url),
         schema, identity.stream_id, observed.isoformat(), crash_at],
        cwd=os.getcwd(), capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == expected_exit, result.stderr
    fresh = ReferenceRepository(factory)
    token, _ = fresh.load_checkpoint(identity.stream_id, revision)
    assert token.seq == (2 if committed else 1)
    with factory() as session:
        row = session.get(ReferenceBatch, capture_id)
        assert (row.consumed_by_batch_id is not None) is committed
    assert (fresh.read_pending_capture(identity.stream_id) is None) is committed
    restarted = _worker(fresh, reader, observed)
    restarted.scan()
    assert restarted.run_round() == (0 if committed else 1)
    assert fresh.load_checkpoint(identity.stream_id, revision)[0].seq == 2
    assert fresh.read_pending_capture(identity.stream_id) is None


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
        product_identity.profile_id, "newow_reference_v3",
        futures_adaptation_version(frequency, read.input_quality_policy),
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
