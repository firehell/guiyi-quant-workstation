"""Isolated real-kernel forward throughput at 60 and 300 fixture streams.

The five families use their supported minute periods: three Newow 60m,
SuBing 60m, and HTDY 15m. This is not a product-capability opening.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketObservationSnapshot, MarketReadWindow
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.contracts import SeedChunk
from app.reference_trading.forward_inputs import (
    capture_htdy_live, capture_newow_live, capture_subing_live,
)
from app.reference_trading.models import ReferenceBatch, ReferenceRevision
from app.reference_trading.repository import ReferenceRepository, _digest
from guiyi_quant.newow.product_adapters import (
    build_product_identity, replay_step, seed_replay_state,
)
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import (
    REFERENCE_MODEL_VERSION as NEWOW_MODEL_VERSION,
    build_segment_id, futures_adaptation_version,
)
from guiyi_quant.reference_trading import RecordingMode, ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION as HTDY_MODEL_VERSION
from guiyi_quant.reference_trading.subing_forward import seed_subing_forward
from guiyi_quant.subing_reference import FORMULA_VERSIONS, REFERENCE_MODEL_VERSION as SUBING_MODEL_VERSION
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401


pytestmark = pytest.mark.isolated_postgresql
_ROOT = Path(__file__).resolve().parents[4]
_END = datetime(2026, 9, 23, 2, tzinfo=UTC)
_HTDY_BARS = tuple(CanonicalBar(
    _END - timedelta(minutes=15 * (31 - index)), _END.date(),
    Decimal(3500), Decimal(3510), Decimal(3490), Decimal(3500),
    Decimal(100), None, None,
) for index in range(32))


@pytest.fixture
def capacity_postgresql(isolated_postgres_engine: Engine):  # noqa: F811
    schema = "reference_p8_capacity_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = isolated_postgres_engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        yield scoped
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


class _MarketRead:
    def __init__(self, bar: CanonicalBar, contract: str, *, htdy: bool = False):
        self.bar = bar
        self.contract = contract
        self.htdy = htdy

    def observation_snapshot(self, _query, _after, _now):
        return MarketObservationSnapshot(
            state=None, source="realtime", trading_day=self.bar.trading_day,
            contract=self.contract, bars=(self.bar,),
        )

    def bars_until(self, _query, *, trading_day, end, limit):
        assert self.htdy and limit == 32 and end == self.bar.bar_end
        return MarketReadWindow(
            symbol="RB", series_kind="actual_dominant", frequency="15m",
            trading_day=trading_day, contract=self.contract, cutoff=end,
            bars=_HTDY_BARS, bar_contracts=(self.contract,) * 32,
        )

    def validate_alert_window(self, _window, *, context_bars):
        assert self.htdy and context_bars == 32


class _IdleMarketRead:
    def observation_snapshot(self, _query, _after, _now):
        return MarketObservationSnapshot(
            state=None, source="none", trading_day=_END.date(),
            contract=None, bars=(),
        )


def _newow_state(product: str, strategy: str, contract: str, owner: str):
    state = seed_replay_state()
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input(strategy, "60m")
    identity = build_product_identity(product, ProductStrategy(strategy), ProductFrequency.HOURLY)
    warmup = 50 if strategy == "main_rise" else 0
    for previous in case.bars[:warmup]:
        adapted = replace(previous, bar=replace(
            previous.bar, product=product, physical_contract=contract, segment_id=owner,
        ))
        state, _frame, _diagnostics = replay_step(identity, state, adapted)
    source = case.bars[warmup].bar
    bar = CanonicalBar(
        source.bar_end, source.trading_day,
        source.open, source.high, source.low, source.close,
        Decimal(source.volume), None, Decimal(source.open_interest),
    )
    return identity, state, bar


def _seed_and_capture(repo, factory, product: str, family: str) -> str:
    upper = product.upper()
    contract = upper + "2701"
    owner = build_segment_id(product, contract, datetime(2026, 1, 1, tzinfo=UTC))
    if family.startswith("newow_"):
        strategy = family.removeprefix("newow_")
        product_identity, state, bar = _newow_state(product, strategy, contract, owner)
        identity = StreamIdentity(
            family, product_identity.formula_versions, product_identity.profile_id,
            NEWOW_MODEL_VERSION, futures_adaptation_version("60m"), product,
            "60m", "actual_dominant", RecordingMode.FORWARD_OBSERVATION,
            "completed_live_v1",
        )
        schema = "newow_product_replay_v1"
    elif family == "subing_reference":
        bar = CanonicalBar(_END, _END.date(), 3500, 3510, 3490, 3500, 100, None, 200)
        state = seed_subing_forward()
        identity = StreamIdentity(
            family, (FORMULA_VERSIONS["60m"],), "subing_reference_60m_v1",
            SUBING_MODEL_VERSION, "subing_actual_dominant_v1", upper,
            "60m", "actual_dominant", RecordingMode.FORWARD_OBSERVATION,
            "completed_live_v1",
        )
        schema = "subing_forward_v1"
    else:
        assert family == "htdy"
        bar = _HTDY_BARS[-1]
        state = HtdyForwardState(HTDY_MODEL_VERSION, "latest_only_32_v1")
        identity = StreamIdentity(
            "htdy", ("huotian_dayou_original_v0",), "htdy-v1",
            HTDY_MODEL_VERSION, "actual_dominant_v1", upper,
            "15m", "actual_dominant", RecordingMode.FORWARD_OBSERVATION,
            "latest_only_32_v1",
        )
        schema = "htdy_first_seen_v1"
    start = bar.bar_end - timedelta(seconds=4)
    observed = bar.bar_end + timedelta(seconds=5)
    stored = repo.ensure_stream(identity)
    manifest = {"source": "p8-capacity-fixture"}
    revision = repo.create_revision(identity.stream_id, stored.row_version, _digest(manifest))
    repo.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, sha256(b"seed").hexdigest(), "seed"))
    repo.seal_seed(
        revision, manifest, AdapterCheckpoint(
            state, stream=identity,
            reference_state=ReferenceState.flat(identity, recording_start=start),
        ), schema,
    )
    fixture_acceptance = "p8-fixture-only" if family == "htdy" else None
    accepted = frozenset({(
        fixture_acceptance, identity.reference_model_version,
        identity.observation_policy_version, identity.product, identity.frequency,
    )}) if fixture_acceptance else frozenset()
    activation = ForwardActivation(factory, accepted_models=accepted)
    plan = activation.plan(
        identity.stream_id, revision, host="isolated-host", environment="isolated",
        recording_start=start, expires_at=start + timedelta(minutes=1),
        budget={"max_pending": 32}, model_acceptance_id=fixture_acceptance,
    )
    activation.apply(plan, expected_plan_hash=plan.plan_hash, now=start - timedelta(seconds=1))
    read = _MarketRead(bar, contract, htdy=family == "htdy")
    common = dict(revision_id=revision, generation=1, after=None, now=observed)
    if family.startswith("newow_"):
        capture = capture_newow_live(
            read, identity, wake_kind="scan",
            owner_segments=lambda *_: (owner, owner),
            expected_endpoints=lambda *_: (bar.bar_end,),
            capability_ready=lambda _: True, **common,
        )
    elif family == "subing_reference":
        capture = capture_subing_live(
            read, identity, wake_kind="scan",
            owner_segments=lambda *_: (owner, owner),
            expected_endpoints=lambda *_: (bar.bar_end,), **common,
        )
    else:
        capture = capture_htdy_live(
            read, identity, wake_kind="live_event", event_bar_end=bar.bar_end,
            owner_segments=lambda *_: (owner, owner), **common,
        )
    assert capture is not None
    repo.capture_forward(capture)
    return identity.stream_id


@pytest.mark.parametrize("stream_count", [60, 300])
def test_postgresql_real_kernel_forward_worker_capacity(capacity_postgresql, stream_count):
    products = tuple((_ROOT / "data/universe/operational_products.txt").read_text().splitlines())
    assert len(products) == 60 and len(set(products)) == 60
    factory = sessionmaker(capacity_postgresql, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    families = (
        ("newow_trend",) if stream_count == 60 else
        ("newow_trend", "newow_oscillation", "newow_main_rise", "subing_reference", "htdy")
    )
    ingest_started = perf_counter()
    stream_ids = tuple(
        _seed_and_capture(repo, factory, product, family)
        for product in products for family in families
    )
    ingest_seconds = perf_counter() - ingest_started
    assert len(stream_ids) == stream_count and len(set(stream_ids)) == stream_count
    worker = build_forward_reference_worker(
        repository=repo, market_read=_IdleMarketRead(), newow_reader=None,
        owner_segments=lambda *_: ("owner", "owner"),
        expected_endpoints=lambda *_: (),
        newow_capability_ready=lambda _: True, enabled=True,
    )
    started = perf_counter()
    worker.scan()
    completed = 0
    rounds = 0
    while worker.health().pending_keys:
        completed += worker.run_round()
        rounds += 1
        # Every durable pending capture gets one post-commit scan; the isolated
        # read seam proves no further Bar arrived, so both queue passes drain.
        assert rounds <= 2 * ((stream_count + 31) // 32) + 1
    elapsed = perf_counter() - started
    total_seconds = perf_counter() - ingest_started
    assert completed == stream_count, worker.health().blocked
    assert not worker.health().blocked
    assert elapsed <= (60 if stream_count == 60 else 900)
    assert total_seconds <= (60 if stream_count == 60 else 900)
    with factory() as session:
        seqs = session.execute(select(ReferenceRevision.last_seq)).scalars().all()
        pending = session.scalar(select(func.count()).select_from(ReferenceBatch).where(
            ReferenceBatch.kind == "capture", ReferenceBatch.consumed_by_batch_id.is_(None),
        ))
        calculations = session.scalar(select(func.count()).select_from(ReferenceBatch).where(
            ReferenceBatch.kind == "calculation",
        ))
    assert len(seqs) == stream_count and set(seqs) == {2}
    assert pending == 0 and calculations == stream_count
    if os.getenv("GUIYI_P8_BENCH_STREAM") == "1":
        print("P8_STREAM_METRIC=" + json.dumps({
            "streams": stream_count, "completed": completed, "rounds": rounds,
            "worker_seconds": round(elapsed, 3), "pending": pending,
            "typed_capture_and_seed_seconds": round(ingest_seconds, 3),
            "capture_to_project_seconds": round(total_seconds, 3),
            "calculations": calculations,
        }, sort_keys=True))
