"""Real Canonical publication, semantic prefix proof and native replay parity."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
from app.market_data.catalog import MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.product_reader import NewowProductReader
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import (
    HistoricalReferencePlanner,
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
)
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.service import HistoricalReferenceService
from app.reference_trading.query import HistoricalReferenceQuery
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_historical_integration import (
    _Coverage,
    _bar,
    _publish_all,
    _newow_stream,
)


@pytest.fixture(params=["sqlite", "postgresql"])
def native_engine(request):
    if request.param == "sqlite":
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()
        return
    admin = request.getfixturevalue("isolated_postgres_engine")
    schema = "newow_append_" + uuid4().hex
    with admin.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = admin.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        yield scoped
    finally:
        with admin.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def test_same_month_native_append_matches_rebuild_and_rejects_prefix_revision(
    native_engine, tmp_path
):
    first, last = date(2026, 1, 5), date(2026, 1, 30)
    civil = tuple(first + timedelta(days=i) for i in range((last - first).days + 1))
    days = tuple(d for d in civil if d.weekday() < 5)
    old_last = days[-3]

    def end(day):
        return (
            datetime.combine(day, time(13), tzinfo=UTC)
            - timedelta(hours=8)
            + timedelta(microseconds=1)
        )

    coverage = _Coverage(first, old_last)
    factory = sessionmaker(native_engine, expire_on_commit=False)
    with Session(native_engine) as session:
        session.add_all(
            [
                Exchange(code="SHFE", name="SHFE"),
                Instrument(
                    symbol="rb", name="RB", exchange_code="SHFE", is_active=True
                ),
                Contract(
                    contract_code="RB2701",
                    instrument_symbol="rb",
                    exchange_code="SHFE",
                    listed_date=first,
                    expired_date=last + timedelta(days=30),
                    provider="rqdata",
                ),
            ]
        )
        session.add_all(
            [
                TradingCalendar(
                    exchange_code="SHFE",
                    trade_date=d,
                    is_trading_day=d.weekday() < 5,
                    provider="rqdata",
                )
                for d in civil
            ]
        )
        session.add_all(
            [
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol="rb",
                    session_name="day",
                    start_time=time(9),
                    end_time=time(13),
                    effective_from=d,
                    effective_to=d,
                    is_active=True,
                    provider="rqdata",
                )
                for d in days
            ]
        )
        session.commit()
        catalog, store = (
            MarketCatalog(session, tmp_path),
            CanonicalMonthlyStore(tmp_path),
        )
        catalog.upsert_main_contracts(tuple(("rb", d, "RB2701") for d in days))
        session.commit()
        # A repeated decline/rally produces real BUILD/CLEAR transitions after warm-up.
        prices = [
            3500 + (i % 24 if i % 24 < 12 else 24 - i % 24) * 30
            for i in range(len(days) * 4)
        ]
        hourly = tuple(
            replace(
                _bar(
                    datetime.combine(d, time(9), tzinfo=UTC)
                    - timedelta(hours=8)
                    + timedelta(hours=j + 1),
                    d,
                    prices[i * 4 + j],
                ),
                volume=Decimal(60),
                turnover=Decimal(60000),
            )
            for i, d in enumerate(days)
            for j in range(4)
        )
        minute = tuple(
            replace(
                b,
                bar_end=b.bar_end - timedelta(minutes=60 - j),
                volume=b.volume / 60,
                turnover=b.turnover / 60,
            )
            for b in hourly
            for j in range(1, 61)
        )
        daily = tuple(
            _bar(end(d) - timedelta(microseconds=1), d, prices[i * 4 + 3])
            for i, d in enumerate(days)
        )

        def publish(through, revised=False):
            bars = tuple(b for b in hourly if b.trading_day <= through)
            if revised:
                bars = (replace(bars[0], close=bars[0].close + 1), *bars[1:])
            _publish_all(
                catalog,
                store,
                "1m",
                tuple(b for b in minute if b.trading_day <= through),
            )
            _publish_all(catalog, store, "60m", bars)
            _publish_all(
                catalog,
                store,
                "1d",
                tuple(b for b in daily if b.trading_day <= through),
            )
            session.commit()

        publish(old_last)
        mds = MarketDataService(catalog, store)
        reader = MarketDataHistoricalInputReader(
            newow_reader=NewowProductReader(
                mds, coverage=coverage, active_products=("rb",), now=lambda: end(last)
            ),
            subing_service=None,
            compact_intraday_inputs=True,
        )
        identity = _newow_stream(ProductStrategy.OSCILLATION, ProductFrequency.HOURLY)
        old = HistoricalStreamRequest(identity, first, old_last, end(old_last))
        new = HistoricalStreamRequest(identity, first, last, end(last))
        budget = WorkBudget(1, 100_000, 120, 100_000_000)
        planner = HistoricalReferencePlanner(reader, now=lambda: end(last))
        repo = ReferenceRepository(factory)
        service = HistoricalReferenceService(repo, reader)

        def plan(operation, request):
            return planner.plan(
                HistoricalReferenceRequest(
                    operation, (request,), budget, batch_size=256
                )
            )

        initial = plan("build", old)
        assert (
            initial.streams[0].input_manifest["reader"]
            == "newow_product_reader_prefix_v4"
        )
        assert (
            initial.streams[0].input_manifest["rank1"][-1][-1] == old_last.isoformat()
        )
        assert service.execute(initial, initial.plan_hash).status == "completed"
        old_revision = repo.read_state(identity.stream_id).revision_id
        publish(last)
        coverage.last = last
        incremental = plan("advance", new)
        result = service.advance(incremental, incremental.plan_hash)
        assert result.status == "completed", [
            (r.status, r.reason) for r in result.streams
        ]
        assert repo.read_state(identity.stream_id).revision_id == old_revision
        query = HistoricalReferenceQuery(factory)

        def numerical():
            summary = query.summary(
                identity.stream_id, since=first, through=last, cutoff=end(last)
            )
            for k in ("snapshot", "revision_id", "seq", "coverage"):
                summary.pop(k, None)
            trades = query.trades(
                identity.stream_id,
                since=first,
                through=last,
                cutoff=end(last),
                limit=200,
            )["items"]
            for t in trades:
                for k in ("revision_id", "valid_from_seq", "valid_to_seq"):
                    t.pop(k, None)
            return summary, trades

        appended = numerical()
        assert appended[0]["closed_count"] > 0
        assert appended[1]
        rebuilt = plan("rebuild", new)
        assert service.rebuild(rebuilt, rebuilt.plan_hash).status == "completed"
        assert repo.read_state(identity.stream_id).revision_id != old_revision
        assert numerical() == appended
        # Rewriting one old completed Close is not an append and cannot reuse the state.
        publish(last, revised=True)
        changed = plan("advance", new)
        rejected = service.advance(changed, changed.plan_hash)
        assert rejected.status == "blocked"
        assert rejected.streams[0].reason == "REBUILD_REQUIRED"
