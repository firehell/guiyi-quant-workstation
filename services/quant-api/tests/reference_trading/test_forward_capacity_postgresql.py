"""Isolated real-kernel forward throughput at 60 and 300 fixture streams.

The five families use their supported minute periods: three Newow 60m,
SuBing 60m, and HTDY 15m. This is not a product-capability opening.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import gc
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey, SeriesPageQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_read_service import MarketObservationSnapshot, MarketReadWindow
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.contracts import SeedChunk
from app.reference_trading.forward_inputs import (
    capture_htdy_live, capture_newow_live, capture_subing_live,
)
from app.reference_trading.models import (
    ReferenceActionRow, ReferenceBatch, ReferenceMarkRow, ReferenceRevision,
)
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


class _MdsMarketRead:
    """Test-only completed observation sourced from real Catalog/Parquet/MDS reads."""

    def __init__(self, service: MarketDataService, product: str, frequency: str,
                 contract: str, target_bar: CanonicalBar):
        self.service = service
        self.product = product.upper()
        self.frequency = frequency
        self.contract = contract
        self.target_bar = target_bar
        self.read_count = 0
        self.read_seconds = 0.0

    def _page(self, limit: int, end: datetime) -> tuple[CanonicalBar, ...]:
        started = perf_counter()
        page = self.service.query_page(SeriesPageQuery(
            "actual_dominant", self.product, self.frequency,
            before=end + timedelta(microseconds=1), limit=limit,
        ))
        self.read_seconds += perf_counter() - started
        self.read_count += 1
        assert page.bars and page.bars[-1] == self.target_bar
        assert all(segment.contract == self.contract for segment in page.resolved_contract_segments)
        return page.bars

    def observation_snapshot(self, _query, _after, _now):
        bars = self._page(1, self.target_bar.bar_end)
        return MarketObservationSnapshot(
            state=None, source="realtime", trading_day=self.target_bar.trading_day,
            contract=self.contract, bars=bars,
        )

    def bars_until(self, _query, *, trading_day, end, limit):
        assert self.frequency == "15m" and trading_day == self.target_bar.trading_day
        assert end == self.target_bar.bar_end and limit == 32
        bars = self._page(limit, end)
        assert len(bars) == 32
        return MarketReadWindow(
            symbol=self.product, series_kind="actual_dominant", frequency="15m",
            trading_day=trading_day, contract=self.contract, cutoff=end,
            bars=bars, bar_contracts=(self.contract,) * len(bars),
        )

    def validate_alert_window(self, window, *, context_bars):
        assert context_bars == 32 and len(window.bars) == 32


class _LongLivedMdsMarketRead:
    """Expose successive completed fixture endpoints to one retained worker."""

    def __init__(self, service: MarketDataService):
        self.service = service
        self.wave = 0
        self.read_count = 0

    def target(self, frequency: str) -> CanonicalBar:
        end = (
            datetime(2026, 9, 23, 8, tzinfo=UTC) + timedelta(minutes=15 * self.wave)
            if frequency == "15m" else
            datetime(2026, 9, 23, 5 + self.wave, tzinfo=UTC)
        )
        return CanonicalBar(
            end, date(2026, 9, 23), Decimal(3500), Decimal(3510),
            Decimal(3490), Decimal(3500), Decimal(100), None, Decimal(200),
        )

    def _read(self, query, limit: int) -> tuple[CanonicalBar, ...]:
        frequency = query.frequency.value
        target = self.target(frequency)
        reader = _MdsMarketRead(
            self.service, query.symbol, frequency, query.symbol.upper() + "2701", target,
        )
        bars = reader._page(limit, target.bar_end)
        self.read_count += reader.read_count
        return bars

    def observation_snapshot(self, query, after, _now):
        target = self.target(query.frequency.value)
        if after is not None and target.bar_end <= after:
            return MarketObservationSnapshot(
                state=None, source="none", trading_day=target.trading_day,
                contract=None, bars=(),
            )
        bars = self._read(query, 1)
        return MarketObservationSnapshot(
            state=None, source="realtime", trading_day=target.trading_day,
            contract=query.symbol.upper() + "2701", bars=bars,
        )

    def bars_until(self, query, *, trading_day, end, limit):
        target = self.target(query.frequency.value)
        assert query.frequency.value == "15m" and trading_day == target.trading_day
        assert end == target.bar_end and limit == 32
        bars = self._read(query, limit)
        assert len(bars) == 32
        return MarketReadWindow(
            symbol=query.symbol, series_kind="actual_dominant", frequency="15m",
            trading_day=trading_day, contract=query.symbol.upper() + "2701",
            cutoff=end, bars=bars, bar_contracts=(query.symbol.upper() + "2701",) * 32,
        )

    def validate_alert_window(self, window, *, context_bars):
        assert context_bars == 32 and len(window.bars) == 32


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


def _seed_and_capture(repo, factory, product: str, family: str,
                      market_read: _MdsMarketRead | None = None) -> str:
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
    if market_read is not None:
        assert market_read.contract == contract
        bar = market_read.target_bar
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
    read = market_read or _MarketRead(bar, contract, htdy=family == "htdy")
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


def _publish_mds_fixture(
    engine: Engine, root: Path, products: tuple[str, ...], *, long_lived: bool = False,
) -> None:
    """Publish only disposable one-day physical partitions and rank-1 facts."""
    day = date(2026, 9, 23)
    store = CanonicalMonthlyStore(root)
    with Session(engine) as session:
        session.add(Exchange(code="SHFE", name="P8 fixture exchange"))
        session.add(TradingCalendar(
            exchange_code="SHFE", trade_date=day, is_trading_day=True,
            provider="rqdata",
        ))
        session.add_all(Instrument(
            symbol=product.lower(), name=product.upper(), exchange_code="SHFE",
            is_active=True,
        ) for product in products)
        session.add_all(Contract(
            contract_code=product.upper() + "2701", instrument_symbol=product.lower(),
            exchange_code="SHFE", listed_date=day,
            expired_date=day + timedelta(days=30), provider="rqdata",
        ) for product in products)
        session.add_all(TradingSession(
            exchange_code="SHFE", instrument_symbol=product.lower(),
            session_name="fixture_day", start_time=time(8 if long_lived else 9),
            end_time=time(17),
            effective_from=day, effective_to=day, is_active=True, provider="rqdata",
        ) for product in products)
        session.flush()
        catalog = MarketCatalog(session, root)
        catalog.upsert_main_contracts(tuple(
            (product.lower(), day, product.upper() + "2701")
            for product in products
        ))
        for product in products:
            periods = (("60m", 60, 8), ("15m", 15, 36 if long_lived else 32))
            for frequency, step_minutes, count in periods:
                bars = tuple(CanonicalBar(
                    datetime(2026, 9, 23, 0 if long_lived and frequency == "15m" else 1, tzinfo=UTC)
                    + timedelta(minutes=step_minutes * index), day,
                    Decimal(3500), Decimal(3510), Decimal(3490), Decimal(3500),
                    Decimal(100), None, Decimal(200),
                ) for index in range(1, count + 1))
                key = DatasetKey("contract", product.lower(), product.upper() + "2701", frequency)
                catalog.register_partition(store.publish(PublishRequest(
                    key, day.year, day.month, bars,
                    tuple(bar.bar_end for bar in bars),
                )))
        session.commit()


def test_postgresql_300_streams_acquire_from_real_mds(capacity_postgresql, tmp_path):
    products = tuple((_ROOT / "data/universe/operational_products.txt").read_text().splitlines())
    assert len(products) == 60 and len(set(products)) == 60
    _publish_mds_fixture(capacity_postgresql, tmp_path, products)
    families = (
        "newow_trend", "newow_oscillation", "newow_main_rise",
        "subing_reference", "htdy",
    )
    factory = sessionmaker(capacity_postgresql, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    reads = 0
    read_seconds = 0.0
    started = perf_counter()
    with Session(capacity_postgresql) as session:
        market_data = MarketDataService(
            MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path),
        )
        stream_ids = []
        for product in products:
            for family in families:
                frequency = "15m" if family == "htdy" else "60m"
                contract = product.upper() + "2701"
                target = CanonicalBar(
                    datetime(2026, 9, 23, 9, tzinfo=UTC), date(2026, 9, 23),
                    Decimal(3500), Decimal(3510), Decimal(3490), Decimal(3500),
                    Decimal(100), None, Decimal(200),
                )
                read = _MdsMarketRead(market_data, product, frequency, contract, target)
                stream_ids.append(_seed_and_capture(
                    repo, factory, product, family, market_read=read,
                ))
                reads += read.read_count
                read_seconds += read.read_seconds
    capture_seconds = perf_counter() - started
    assert len(stream_ids) == len(set(stream_ids)) == 300
    assert reads == 360  # One snapshot per stream; HTDY also reads 32-Bar context.
    worker = build_forward_reference_worker(
        repository=repo, market_read=_IdleMarketRead(), newow_reader=None,
        owner_segments=lambda *_: ("owner", "owner"),
        expected_endpoints=lambda *_: (), newow_capability_ready=lambda _: True,
        enabled=True,
    )
    worker_started = perf_counter()
    worker.scan()
    completed = 0
    rounds = 0
    while worker.health().pending_keys:
        completed += worker.run_round()
        rounds += 1
        assert rounds <= 21
    worker_seconds = perf_counter() - worker_started
    total_seconds = perf_counter() - started
    assert completed == 300, worker.health().blocked
    assert not worker.health().blocked
    assert not worker.health().pending_keys
    assert total_seconds <= 900
    with factory() as session:
        calculations = session.scalar(select(func.count()).select_from(ReferenceBatch).where(
            ReferenceBatch.kind == "calculation",
        ))
        pending = session.scalar(select(func.count()).select_from(ReferenceBatch).where(
            ReferenceBatch.kind == "capture", ReferenceBatch.consumed_by_batch_id.is_(None),
        ))
    assert calculations == 300 and pending == 0
    if os.getenv("GUIYI_P8_BENCH_MDS_STREAM") == "1":
        print("P8_MDS_STREAM_METRIC=" + json.dumps({
            "streams": len(stream_ids), "mds_reads": reads,
            "mds_seconds": round(read_seconds, 3),
            "capture_seconds": round(capture_seconds, 3),
            "worker_seconds": round(worker_seconds, 3),
            "total_seconds": round(total_seconds, 3),
            "rounds": rounds, "calculations": calculations, "pending": pending,
        }, sort_keys=True))


def test_postgresql_300_mds_same_process_rss_soak(
    isolated_postgres_engine: Engine, tmp_path_factory,  # noqa: F811
) -> None:
    """Repeat an equal real-MDS workload in one process and report settled RSS."""
    settled_rss_kib: list[int] = []
    for wave in range(5):
        schema = "reference_p8_soak_" + uuid4().hex
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped = isolated_postgres_engine.execution_options(
            schema_translate_map={None: schema},
        )
        try:
            Base.metadata.create_all(scoped)
            test_postgresql_300_streams_acquire_from_real_mds(
                scoped, tmp_path_factory.mktemp(f"p8-mds-soak-{wave}"),
            )
        finally:
            with isolated_postgres_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        del scoped
        gc.collect()
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True, text=True, check=True, timeout=5,
        )
        settled_rss_kib.append(int(result.stdout.strip()))
        print("P8_MDS_SOAK_WAVE=" + json.dumps({
            "wave": wave + 1, "settled_rss_kib": settled_rss_kib[-1],
        }, sort_keys=True), flush=True)
    print("P8_MDS_SOAK_METRIC=" + json.dumps({
        "settled_rss_kib": settled_rss_kib,
        "last_minus_first_kib": settled_rss_kib[-1] - settled_rss_kib[0],
    }, sort_keys=True), flush=True)


def test_postgresql_300_mds_retained_worker_five_completed_bars(
    capacity_postgresql: Engine, tmp_path,
) -> None:
    """Keep the same worker, streams, schema and MDS across equal 300-Bar waves."""
    products = tuple((_ROOT / "data/universe/operational_products.txt").read_text().splitlines())
    assert len(products) == 60 and len(set(products)) == 60
    _publish_mds_fixture(capacity_postgresql, tmp_path, products, long_lived=True)
    factory = sessionmaker(capacity_postgresql, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    families = (
        "newow_trend", "newow_oscillation", "newow_main_rise",
        "subing_reference", "htdy",
    )
    settled_rss_kib: list[int] = []
    wave_seconds: list[float] = []
    with Session(capacity_postgresql) as session:
        market_data = MarketDataService(
            MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path),
        )
        read = _LongLivedMdsMarketRead(market_data)
        seeded_stream_ids = []
        for product in products:
            for family in families:
                frequency = "15m" if family == "htdy" else "60m"
                seed_read = _MdsMarketRead(
                    market_data, product, frequency, product.upper() + "2701",
                    read.target(frequency),
                )
                seeded_stream_ids.append(_seed_and_capture(
                    repo, factory, product, family, market_read=seed_read,
                ))
                read.read_count += seed_read.read_count
        stream_ids = tuple(seeded_stream_ids)
        assert len(stream_ids) == len(set(stream_ids)) == 300
        main_rise_ids = {
            stream_id for stream_id, family in zip(stream_ids, families * 60, strict=True)
            if family == "newow_main_rise"
        }

        def owner_segments(identity, contract, _day, _end):
            owner = build_segment_id(
                identity.product.lower(), contract, datetime(2026, 1, 1, tzinfo=UTC),
            )
            return owner, owner

        worker = build_forward_reference_worker(
            repository=repo, market_read=read, newow_reader=None,
            owner_segments=owner_segments,
            expected_endpoints=lambda _identity, _contract, _day, _after, end: (end,),
            newow_capability_ready=lambda _: True,
            now=lambda: datetime(2026, 9, 23, 9, 1, tzinfo=UTC), enabled=True,
        )
        for wave in range(5):
            assert read.wave == wave
            if wave == 0:
                worker.scan()
            else:
                for stream_id, family in zip(stream_ids, families * 60, strict=True):
                    worker.wake(
                        stream_id, kind="live_event" if family == "htdy" else "scan",
                        bar_end=read.target("15m").bar_end if family == "htdy" else None,
                    )
            started = perf_counter()
            completed = 0
            rounds = 0
            while worker.health().pending_keys:
                completed += worker.run_round()
                rounds += 1
                assert rounds <= 21
            elapsed = perf_counter() - started
            wave_seconds.append(round(elapsed, 3))
            assert completed == 300, worker.health().blocked
            assert not worker.health().blocked
            assert worker.health().pending_keys == 0
            with factory() as check:
                seqs = check.execute(select(ReferenceRevision.last_seq)).scalars().all()
                pending = check.scalar(select(func.count()).select_from(ReferenceBatch).where(
                    ReferenceBatch.kind == "capture",
                    ReferenceBatch.consumed_by_batch_id.is_(None),
                ))
                calculations = check.scalar(select(func.count()).select_from(ReferenceBatch).where(
                    ReferenceBatch.kind == "calculation",
                ))
                action_rows = check.execute(select(
                    ReferenceActionRow.stream_id, ReferenceActionRow.kind,
                    ReferenceActionRow.bar_end, ReferenceActionRow.observed_at,
                )).all()
                actions = len(action_rows)
                marks = check.scalar(select(func.count()).select_from(ReferenceMarkRow))
            assert len(seqs) == 300 and set(seqs) == {2 + wave}
            assert pending == 0 and calculations == 300 * (wave + 1)
            assert actions == (60 if wave == 4 else 0)
            if wave == 4:
                assert {row.stream_id for row in action_rows} == main_rise_ids
                assert {row.kind for row in action_rows} == {"HINT"}
                assert {row.bar_end for row in action_rows} == {
                    datetime(2026, 9, 23, 9, tzinfo=UTC),
                }
                assert {row.observed_at for row in action_rows} == {
                    datetime(2026, 9, 23, 9, 1, tzinfo=UTC),
                }
            gc.collect()
            result = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True, text=True, check=True, timeout=5,
            )
            settled_rss_kib.append(int(result.stdout.strip()))
            print("P8_RETAINED_WORKER_WAVE=" + json.dumps({
                "wave": wave + 1, "completed": completed,
                "worker_seconds": wave_seconds[-1],
                "settled_rss_kib": settled_rss_kib[-1],
                "mds_reads": read.read_count,
                "actions": actions, "marks": marks, "pending": pending,
            }, sort_keys=True), flush=True)
            read.wave += 1
        assert read.read_count == 5 * 360
    print("P8_RETAINED_WORKER_METRIC=" + json.dumps({
        "settled_rss_kib": settled_rss_kib,
        "worker_seconds": wave_seconds,
        "last_minus_second_kib": settled_rss_kib[-1] - settled_rss_kib[1],
    }, sort_keys=True), flush=True)
