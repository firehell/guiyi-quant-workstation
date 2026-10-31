"""Real Canonical publication, semantic prefix proof and native replay parity."""

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
from app.market_data.catalog import MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.page_performance_adapter import project_page_performance
from app.market_data.newow.product_query import NewowProductQuery
from app.market_data.newow.product_reader import (
    NewowProductReader, ResolvedPerformanceWindow,
)
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.newow_fusion import SavedFusionSources
from app.reference_trading.planning import (
    HistoricalReferencePlanner,
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
)
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.models import ReferenceBatch
from app.reference_trading.page_material_storage import verify_source_integrity
from app.reference_trading.service import HistoricalReferenceService
from app.reference_trading.refresh_recovery import _readback
from app.reference_trading.query import HistoricalReferenceQuery
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.product_adapters import build_product_identity
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
    native_engine, tmp_path, monkeypatch
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
            pin_verified_inputs=True,
        )
        identity = _newow_stream(ProductStrategy.OSCILLATION, ProductFrequency.HOURLY)
        old = HistoricalStreamRequest(identity, first, old_last, end(old_last))
        new = HistoricalStreamRequest(identity, first, last, end(last))
        trend_identity = _newow_stream(ProductStrategy.TREND, ProductFrequency.HOURLY)
        trend_old = HistoricalStreamRequest(trend_identity, first, old_last, end(old_last))
        trend_new = HistoricalStreamRequest(trend_identity, first, last, end(last))
        fusion_identity = build_fusion_stream_identity("rb", "60m")
        fusion_old = HistoricalStreamRequest(fusion_identity, first, old_last, end(old_last))
        fusion_new = HistoricalStreamRequest(fusion_identity, first, last, end(last))
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
            == "newow_product_reader_prefix_v5"
        )
        assert (
            initial.streams[0].input_manifest["rank1"][-1][-1] == old_last.isoformat()
        )
        assert service.execute(initial, initial.plan_hash).status == "completed"
        trend_initial = plan("build", trend_old)
        assert service.execute(trend_initial, trend_initial.plan_hash).status == "completed"
        reader._fusion_sources = SavedFusionSources(factory)
        fusion_initial = plan("build", fusion_old)
        assert service.execute(fusion_initial, fusion_initial.plan_hash).status == "completed"
        def page_read_without_history(through, *, fusion=False):
            from app.market_data.newow.product_service import (
                NewowProductService, ProductServiceQuery, ProductSection, ReferenceMode, ReferencePart,
            )
            from app.reference_trading.persisted_newow import PersistedNewowReference
            from app.market_data.newow.snapshot_cache import SnapshotCache
            persisted = PersistedNewowReference(factory, cache=SnapshotCache())
            def factory_read(context, cancelled):
                return NewowProductReader(mds, coverage=coverage, active_products=("rb",),
                    context_frequencies=context, cancelled=cancelled, now=lambda: end(through))
            product = NewowProductService(factory_read, now=lambda: end(through),
                persisted_reference=persisted.section)
            query_request = ProductServiceQuery(product="rb", strategy=ProductStrategy.OSCILLATION,
                frequency=ProductFrequency.HOURLY, section=ProductSection.REFERENCE,
                performance_since=first, performance_through=through, as_of=end(through),
                include_fusion=fusion, reference_part=ReferencePart.PANEL,
                reference_mode=(ReferenceMode.FUSION_PAGE_ORDINARY if fusion
                                else ReferenceMode.PAGE_ORDINARY))
            with monkeypatch.context() as patch:
                def forbidden(*_args, **_kwargs):
                    pytest.fail("GET replayed historical strategy inputs")
                patch.setattr(NewowProductReader, "load_historical", forbidden)
                result = product.query(query_request)
                assert result.reference.value is not None, result.reference.status
                payload = result.reference.value.payload
                selected = (payload["fusion_comparison"]["page_performance"]
                            if fusion else payload["page_performance"])
                assert selected["ordinary"] is not None
                assert payload["reference_status"]["status"] == "current"
                persisted.validate_cached_generation(result.reference, reader=reader._newow)
                switched = product.query(replace(query_request, reference_mode=(
                    ReferenceMode.FUSION_PAGE_IDEAL if fusion else ReferenceMode.PAGE_IDEAL
                )))
                assert switched.reference.value is not None, switched.reference.status
                switched_payload = switched.reference.value.payload
                switched_page = (switched_payload["fusion_comparison"]["page_performance"]
                                 if fusion else switched_payload["page_performance"])
                assert switched_page["ideal"] is not None
                assert switched.reference.value.saved_generation == result.reference.value.saved_generation
                if fusion:
                    assert (switched_payload["fusion_comparison"]["reference_revision"]
                            == payload["fusion_comparison"]["reference_revision"])
                    return selected, switched_page
                return payload

        def pure_fusion_pages(through):
            full = reader._newow.load_historical(NewowProductQuery(
                "rb", ProductStrategy.OSCILLATION, ProductFrequency.HOURLY,
                first, through, first, through, end(through),
            ), end(through))
            try:
                product_identity = build_product_identity(
                    "rb", ProductStrategy.OSCILLATION, ProductFrequency.HOURLY,
                )
                resolved = ResolvedPerformanceWindow(
                    first, through, through, end(through) - timedelta(microseconds=1),
                )
                return tuple(project_page_performance(
                    full, product_identity, resolved, fusion=True, selected_mode=mode,
                ) for mode in ("ordinary", "ideal"))
            finally:
                full.close()

        def numerical_pages(pages):
            return tuple({key: value for key, value in page.items()
                          if key != "source_evidence_sha256"} for page in pages)

        old_page = page_read_without_history(old_last)
        old_fusion_pages = page_read_without_history(old_last, fusion=True)
        assert numerical_pages(old_fusion_pages) == numerical_pages(
            pure_fusion_pages(old_last)
        )
        old_revision = repo.read_state(identity.stream_id).revision_id
        old_seq = repo.read_state(identity.stream_id).checkpoint.seq
        old_source = repo.read_state(identity.stream_id).source_evidence[
            "input_integrity_v1"
        ]["source_integrity"]["evidence_sha256"]

        def republish_minute_interest(delta):
            revised = (replace(
                minute[0], open_interest=minute[0].open_interest + delta,
            ), *minute[1:])
            _publish_all(catalog, store, "1m", tuple(
                bar for bar in revised if bar.trading_day <= old_last
            ))
            session.commit()

        def source_verifications():
            with Session(native_engine) as read_session:
                return read_session.scalars(select(ReferenceBatch).where(
                    ReferenceBatch.stream_id == identity.stream_id,
                    ReferenceBatch.revision_id == old_revision,
                    ReferenceBatch.kind == "diagnostic",
                    ReferenceBatch.batch_key.like("source-verify:%"),
                )).all()

        republish_minute_interest(Decimal(1))
        same_endpoint = plan("advance", old)
        assert same_endpoint.streams[0].source_token == initial.streams[0].source_token
        assert same_endpoint.streams[0].input_manifest == initial.streams[0].input_manifest
        same_report = service.advance(same_endpoint, same_endpoint.plan_hash)
        assert same_report.status == "noop", [
            (item.status, item.reason) for item in same_report.streams
        ]
        assert repo.read_state(identity.stream_id).checkpoint.seq == old_seq
        evidence = source_verifications()
        assert len(evidence) == 1
        record = evidence[0].source_evidence["input_integrity_v1"]
        assert record["source_integrity"]["evidence_sha256"] != old_source
        assert verify_source_integrity(reader._newow, record["source_integrity"])
        assert service.advance(same_endpoint, same_endpoint.plan_hash).status == "noop"
        assert len(source_verifications()) == 1
        assert page_read_without_history(old_last)["page_performance"] == old_page["page_performance"]

        republish_minute_interest(Decimal(2))
        next_source = plan("advance", old)
        original_diagnostic = repo.record_diagnostic

        def uncertain_diagnostic(*args, **kwargs):
            original_diagnostic(*args, **kwargs)
            raise OSError("lost diagnostic receipt")

        monkeypatch.setattr(repo, "record_diagnostic", uncertain_diagnostic)
        unknown = service.advance(next_source, next_source.plan_hash)
        assert unknown.status == "blocked"
        assert unknown.streams[0].reason == "SOURCE_REVERIFY_OUTCOME_UNKNOWN"
        assert repo.read_state(identity.stream_id).checkpoint.seq == old_seq
        monkeypatch.setattr(repo, "record_diagnostic", original_diagnostic)
        assert service.advance(next_source, next_source.plan_hash).status == "noop"
        assert len(source_verifications()) == 2

        publish(last)
        coverage.last = last
        incremental = plan("advance", new)
        result = service.advance(incremental, incremental.plan_hash)
        assert result.status == "completed", [
            (r.status, r.reason) for r in result.streams
        ]
        assert repo.read_state(identity.stream_id).revision_id == old_revision
        trend_incremental = plan("advance", trend_new)
        trend_result = service.advance(trend_incremental, trend_incremental.plan_hash)
        assert trend_result.status == "completed", [
            (r.status, r.reason) for r in trend_result.streams
        ]
        osc_integrity = repo.read_state(identity.stream_id).source_evidence[
            "input_integrity_v1"
        ]["source_integrity"]
        trend_integrity = repo.read_state(trend_identity.stream_id).source_evidence[
            "input_integrity_v1"
        ]["source_integrity"]
        assert trend_integrity == osc_integrity
        fusion_incremental = plan("advance", fusion_new)
        fusion_result = service.advance(fusion_incremental, fusion_incremental.plan_hash)
        assert fusion_result.status == "completed", [
            (r.status, r.reason) for r in fusion_result.streams
        ]
        page_read_without_history(last)
        appended_fusion_pages = page_read_without_history(last, fusion=True)
        assert numerical_pages(appended_fusion_pages) == numerical_pages(
            pure_fusion_pages(last)
        )
        fusion_rebuild = plan("rebuild", fusion_new)
        rebuilt_fusion = service.rebuild(fusion_rebuild, fusion_rebuild.plan_hash)
        assert rebuilt_fusion.status == "completed", [
            (r.status, r.reason) for r in rebuilt_fusion.streams
        ]
        assert numerical_pages(page_read_without_history(last, fusion=True)) == numerical_pages(
            appended_fusion_pages
        )
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
        cancelled = {"value": False}

        def cancel_before_final_material(_count):
            cancelled["value"] = True

        partial = HistoricalReferenceService(
            repo, reader, cancelled=lambda: cancelled["value"],
            step_counter=cancel_before_final_material,
        ).rebuild(rebuilt, rebuilt.plan_hash)
        assert partial.status == "partial"
        assert partial.streams[0].reason == "INTERRUPTED"
        assert partial.streams[0].completed_bars == 0
        assert repo.read_state(identity.stream_id).revision_id == old_revision
        readback = _readback(repo, rebuilt, {
            "resume": asdict(partial.streams[0].resume_token),
        })
        assert readback["candidate_progress"]["max_committed_seq"] == 1
        assert numerical() == appended
        cancelled["value"] = False
        resumed = service.resume(
            rebuilt, partial.streams[0].resume_token, rebuilt.plan_hash,
        )
        assert resumed.status == "completed", [
            (item.status, item.reason) for item in resumed.streams
        ]
        assert repo.read_state(identity.stream_id).revision_id != old_revision
        assert repo.read_state(identity.stream_id, old_revision).revision_status == "superseded"
        assert numerical() == appended
        # Rewriting one old completed Close is not an append and cannot reuse the state.
        publish(last, revised=True)
        changed = plan("advance", new)
        rejected = service.advance(changed, changed.plan_hash)
        assert rejected.status == "blocked"
        assert rejected.streams[0].reason == "REBUILD_REQUIRED"
