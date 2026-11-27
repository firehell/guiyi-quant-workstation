"""Disposable-only PostgreSQL closeout locking and committed-view verification."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.models import Contract, Exchange, Instrument
from tests.data_foundation.test_catalog_publication_postgresql import isolated_postgresql  # noqa: F401
from tests.data_foundation.test_daily_maintenance import daily_manager
from tests.data_foundation.test_observation_stream import isolated_redis  # noqa: F401
from tests.data_foundation.test_after_market_closeout import (
    close, closeout_case, test_real_partial_catalog_and_parquet_closeout_is_readonly as assert_partial,  # noqa: F401
)

pytestmark = pytest.mark.isolated_postgresql


def test_closeout_postgresql_busy_and_partial_readonly(isolated_postgresql, tmp_path, closeout_case):  # noqa: F811
    Base.metadata.create_all(isolated_postgresql)
    with Session(isolated_postgresql) as db:
        db.add(Exchange(code="DCE", name="DCE"))
        db.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
        db.flush()
        db.add(Contract(contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=date(2025, 1, 1), expired_date=date(2026, 1, 1), provider="rqdata"))
        db.commit()
        manager = daily_manager.__wrapped__(db, tmp_path)
        closeout_case["manager"] = manager
        with Session(isolated_postgresql) as other:
            lease = MarketCatalog(other, manager.store.root).acquire_maintenance_lock()
            assert lease is not None
            try:
                result = close(closeout_case, apply=True)
                assert result["status"] == "blocked" and result["status_written"] is False
                assert closeout_case["path"].read_bytes() == closeout_case["content"]
            finally:
                lease.release()
        audit = manager.audit
        def readonly_audit(*args, **kwargs):
            assert db.scalar(text("SHOW transaction_read_only")) == "on"
            assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            return audit(*args, **kwargs)
        manager.audit = readonly_audit
        assert_partial(manager, closeout_case)


@pytest.mark.parametrize("formal_late", [False, True])
def test_candidate_archive_reads_commits_in_fresh_postgresql_transaction_and_keeps_night_redis(
    isolated_postgresql, isolated_redis, tmp_path, monkeypatch, formal_late,  # noqa: F811
):
    from contextlib import contextmanager
    from decimal import Decimal

    from app.market_data.catalog import MarketCatalog
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.market_data.domain import CanonicalBar
    from app.market_data.historical_data_manager import UpdateRequest
    from app.market_data.live_market import RedisLiveStore, _bar_payload
    from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
    from app.market_data.market_archive import verified_archive_readback
    from tests.data_foundation.test_daily_maintenance import _manager

    Base.metadata.create_all(isolated_postgresql)
    with Session(isolated_postgresql) as db:
        db.add(Exchange(code="DCE", name="DCE"))
        db.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
        db.flush()
        db.add(Contract(contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=date(2025, 1, 1), expired_date=date(2026, 1, 1), provider="rqdata"))
        db.commit()
        manager = daily_manager.__wrapped__(db, tmp_path)
        day = date(2025, 3, 7)
        next_day = date(2025, 3, 10)
        live = RedisLiveStore(isolated_redis)
        live.set_subscriptions(day, {"jm": "JM2509"})
        live.set_subscriptions(next_day, {"jm": "JM2509"})
        journal = ObservationStream(isolated_redis, kind="completed")
        for observed_day in (day, next_day):
            endpoint = datetime.combine(observed_day, datetime.min.time(), tzinfo=UTC)
            price = Decimal(10)
            bar = CanonicalBar(endpoint, observed_day, price, price, price, price, price, price, price)
            live.put_bar(observed_day, "jm", "1m", bar, contract="JM2509")
            journal.append(ObservationEnvelope(
                "fixture", observed_day, endpoint, "live:bar:jm:1m",
                _bar_payload(bar, contract="JM2509"), True,
            ))
        prior_immutable = isolated_redis.xrange(journal.key(day))
        next_immutable = isolated_redis.xrange(journal.key(next_day))
        assert prior_immutable and next_immutable

        @contextmanager
        def open_read():
            with Session(isolated_postgresql) as reader:
                coverage = DatabaseCoverageSource(
                    reader, tmp_path / "starts.csv", history_floor_path=tmp_path / "floor.txt",
                    now=manager.coverage._now,
                )
                candidate = _manager(reader, manager.store.root, coverage, manager.provider)
                original = candidate._plan_daily_recovery
                def plan(*args):
                    assert reader.scalar(text("SHOW transaction_read_only")) == "on"
                    return original(*args)
                candidate._plan_daily_recovery = plan
                yield candidate

        with pytest.raises(ValueError, match="MARKET_ARCHIVE_SCOPE_INCOMPLETE"):
            with verified_archive_readback(open_read, ("jm",), day, []):
                pytest.fail("incomplete history must not allow cleanup")
        assert live.subscriptions(day) == {"jm": "JM2509"}

        if formal_late:
            from app.market_data.after_market import AfterMarketResult, AfterMarketUpdater
            from app.market_data import late_provider_recovery as late
            from app.market_data.market_archive import current_retained_receipt
            from app.market_data.session_clock import SHANGHAI

            now = datetime(2025, 3, 9, 19, 5, tzinfo=SHANGHAI)
            schedule = tmp_path / "late-provider-recovery-status.json"
            monkeypatch.setattr(late, "load_operational_products", lambda: ("jm",))
            # Calendar, Session and rank1 are already seeded in the test Catalog.
            monkeypatch.setattr(late, "_sync_archive_metadata", lambda *_: None)
            late.schedule_failure(
                schedule, AfterMarketResult("failed", day, 2, "RQDATA_NOT_READY"),
                ("jm",), datetime(2025, 3, 7, 18, 5, tzinfo=SHANGHAI),
                archive_scope=lambda: None,
            )

            @contextmanager
            def inspect_archive(products, target_day, publications):
                with verified_archive_readback(open_read, products, target_day, publications,
                                               verify_rank1_day=True) as revisions:
                    with Session(isolated_postgresql) as other:
                        assert MarketCatalog(other, manager.store.root).acquire_maintenance_lock() is None
                    yield revisions

            root = tmp_path / "receipts"
            updater = AfterMarketUpdater(
                manager=manager, rqdata=None, live_store=live, now=lambda: now,
                status_path=tmp_path / "after-market-status.json", archive_readback=inspect_archive,
                archive_root=root, sleep=lambda _: pytest.fail("retry"), notification_transport=None,
            )
            result = late.run_scheduled(
                manager, path=schedule, now=lambda: now, ready=lambda target: target == day,
                invalidate=lambda: None, verify_identity=lambda: None, live_store=live, formal_archive=updater,
            )
            assert result["status"] == "passed", late._read(schedule)["runs"][day.isoformat()].get("recovery_error")
            assert manager.publication_evidence
            assert current_retained_receipt(root, now=now).trading_day == day
            assert not updater.status_path.exists()
        else:
            result = manager.update(UpdateRequest(
                ("jm",), None, day, apply=True, mode="daily",
                require_source_ready=True, sync_current_day_metadata=False,
            ))
            assert result.status == "passed" and manager.publication_evidence
            original_calls = len(manager.provider.calls)
            with verified_archive_readback(open_read, ("jm",), day, manager.publication_evidence) as revisions:
                assert set(revisions) == {"jm"}
                with Session(isolated_postgresql) as other:
                    assert MarketCatalog(other, manager.store.root).acquire_maintenance_lock() is None
                live.cleanup_trading_day(day)
            assert len(manager.provider.calls) == original_calls
        assert live.subscriptions(day) is None
        assert live.subscriptions(next_day) == {"jm": "JM2509"}
        assert live.cleanup_readback(day) == {"remaining_bar_keys": 0, "subscription_present": False}
        assert live.cleanup_readback(next_day) == {"remaining_bar_keys": 1, "subscription_present": True}
        assert isolated_redis.xrange(journal.key(day)) == prior_immutable
        assert isolated_redis.xrange(journal.key(next_day)) == next_immutable

        publications = manager.publication_evidence
        bad = [*publications[:-1], {**publications[-1], "file_name": "part." + "a" * 64 + ".parquet"}]
        with pytest.raises(ValueError, match="MARKET_ARCHIVE_POINTER_CHANGED"):
            with verified_archive_readback(open_read, ("jm",), day, bad):
                pytest.fail("pointer mismatch must not qualify")


def test_first_isolated_archive_builds_committed_reference_in_empty_postgresql(
    isolated_postgresql, isolated_redis, tmp_path, monkeypatch,  # noqa: F811
):
    from contextlib import contextmanager
    from datetime import time, timedelta
    from decimal import Decimal
    from types import SimpleNamespace

    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from app.market_data import composition
    from app.market_data.after_market import AfterMarketUpdater
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
    from app.market_data.historical_data_manager import UpdateRequest
    from app.market_data.live_market import RedisLiveStore
    from app.market_data.market_archive import (
        RECEIPT_DIRECTORY, read_archive_receipt, verified_archive_readback,
    )
    from app.market_data.newow.market_reference_after_close import latest_reference, run_receipt
    from app.models import MainContractMap, TradingCalendar, TradingSession
    from app.reference_trading.models import ReferenceStream
    from tests.data_foundation.test_daily_maintenance import FakeProvider, _manager

    Base.metadata.create_all(isolated_postgresql)
    factory = sessionmaker(isolated_postgresql, expire_on_commit=False)
    sandbox = tmp_path
    canonical = sandbox / "canonical"
    starts = sandbox / "starts.csv"
    floor = sandbox / "floor.txt"
    first = date(2026, 10, 5)
    day = date(2026, 10, 30)
    now = datetime.combine(day, time(10, 10), tzinfo=UTC)
    starts.write_text(f"product,window_start\njm,{first}\n")
    floor.write_text(f"{first}\n")
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(canonical))
    def coverage_for(session, **_kwargs):
        return DatabaseCoverageSource(session, starts, history_floor_path=floor, now=lambda: now)
    monkeypatch.setattr(composition, "build_database_coverage_source", coverage_for)

    with factory.begin() as session:
        session.add(Exchange(code="DCE", name="DCE"))
        session.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
        session.flush()
        session.add(Contract(contract_code="JM2701", instrument_symbol="jm", exchange_code="DCE",
            listed_date=first, expired_date=date(2027, 1, 31), provider="rqdata"))
        session.flush()
        for delta in range(-40, (day - first).days + 9):
            current = first + timedelta(days=delta)
            trading = current.weekday() < 5
            session.add(TradingCalendar(exchange_code="DCE", trade_date=current,
                is_trading_day=trading, has_night_session=False, provider="rqdata"))
            if trading and current >= first:
                session.add(TradingSession(exchange_code="DCE", instrument_symbol="jm", session_name="day",
                    start_time=time(9), end_time=time(9, 5), crosses_midnight=False,
                    effective_from=current, effective_to=current, is_active=True, provider="rqdata"))
                session.add(MainContractMap(symbol="jm", trade_date=current, contract_code="JM2701", rank=1))
    with factory() as writer:
        coverage = coverage_for(writer)
        data = {}
        for kind, owner in ((DatasetKind.CONTINUOUS, "MAIN"), (DatasetKind.CONTRACT, "JM2701")):
            for frequency in (BarFrequency.M1, BarFrequency.D1, BarFrequency.W1):
                key = DatasetKey(kind, "jm", owner, frequency)
                ends = coverage.expected_bar_ends(key, day.year, day.month, first, day)
                data[key.as_tuple()] = tuple(CanonicalBar(
                    end, end.date(), Decimal(100), Decimal(101), Decimal(99), Decimal(100),
                    Decimal(5 if frequency is BarFrequency.W1 else 1),
                    Decimal(50 if frequency is BarFrequency.W1 else 10), Decimal(20),
                ) for end in ends)
        provider = FakeProvider(data)
        manager = _manager(writer, canonical, coverage, provider)
        assert manager.update(UpdateRequest(("jm",), None, day - timedelta(days=1), apply=True)).status == "passed"
        assert writer.scalar(select(func.count()).select_from(ReferenceStream)) == 0
        writer.rollback()

        @contextmanager
        def open_readback():
            with factory() as reader:
                yield _manager(reader, canonical, coverage_for(reader), provider)

        live = RedisLiveStore(isolated_redis)
        live.set_subscriptions(day, {"jm": "JM2701"})
        path = sandbox / "after-market-status.json"
        outcomes = []
        def reference_after_close(receipt_path, selected_day):
            assert receipt_path.parent == sandbox / RECEIPT_DIRECTORY
            receipt = read_archive_receipt(receipt_path, now=now)
            assert receipt.trading_day == selected_day
            outcomes.append(run_receipt(sandbox, receipt, session_factory=factory))
            if outcomes[0]["status"] == "completed":
                repeated = run_receipt(sandbox, receipt, session_factory=factory)
                assert repeated["status"] == "already_consumed"
                assert repeated["sections"] == outcomes[0]["sections"]
        archive = AfterMarketUpdater(
            manager=manager, rqdata=SimpleNamespace(is_future_data_ready=lambda current: current == day),
            live_store=live, status_path=path, sleep=lambda _seconds: pytest.fail("supplier retry not expected"),
            notification_transport=None, now=lambda: now, products=("jm",),
            archive_readback=lambda products, trading_day, publications: verified_archive_readback(
                open_readback, products, trading_day, publications,
            ),
            research_update=reference_after_close,
        )
        assert archive.run().status == "passed"
        assert outcomes[0]["status"] == "completed", (outcomes, (sandbox / "newow-historical-refresh-state.json").read_text())
        assert outcomes[0]["routes"] == 24
        assert outcomes[0]["sections"] == {"status": "completed", "expected": 18, "complete": 18}
        assert latest_reference("jm", "trend", "1d", session_factory=factory)["through"] == day.isoformat()
        assert latest_reference("jm", "dual_fusion", "1w", session_factory=factory)["through"] == day.isoformat()

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.reference_trading import router
        from app.market_data.newow.product_service import NewowProductService

        def unexpected_calculation(*_args, **_kwargs):
            pytest.fail("archive section GET must only read saved results")

        monkeypatch.setattr(NewowProductService, "query", unexpected_calculation)
        app = FastAPI()
        app.state.market_foundation_reference_sessions = factory
        app.state.market_foundation_section_root = sandbox
        app.include_router(router)
        with TestClient(app) as client:
            for strategy, section, extra in (
                ("trend", "auxiliary", {"component": "macd"}),
                ("oscillation", "comparator", {}),
            ):
                response = client.get("/api/v1/reference-trading/newow/after-close/section", params={
                    "product": "jm", "strategy": strategy, "frequency": "1d", "section": section, **extra,
                })
                assert response.status_code == 200, response.json()
                result = response.json()
                assert result["status"] == "ready"
                assert result["receipt"] == outcomes[0]["receipt"]
                if section == "comparator":
                    from guiyi_quant.newow.page_comparator import CANDIDATE_WINDOWS
                    comparator = result["result"]["comparator"]
                    assert comparator["status"]["status"] == "ready"
                    value = comparator["value"]["result"]["value"]
                    assert value["candidate_windows"] == list(CANDIDATE_WINDOWS)
                    assert len(value["segments"][0]["results"]) == 5
                assert result["result"]["meta"]["snapshot_token"] == result["chart"]["meta"]["snapshot_token"]
                assert datetime.fromisoformat(result["result"]["meta"]["as_of"]) == latest_reference(
                    "jm", strategy, "1d", session_factory=factory,
                )["cutoff"]

            from app.market_data.newow.market_reference_sections import _path

            comparator_path = _path(sandbox, latest_reference("jm", "oscillation", "1d", session_factory=factory))
            import json
            corrupt = json.loads(comparator_path.read_text())
            corrupt["chart"]["meta"]["snapshot_token"] = "0" * 64
            comparator_path.write_text(json.dumps(corrupt))
            response = client.get("/api/v1/reference-trading/newow/after-close/section", params={
                "product": "jm", "strategy": "oscillation", "frequency": "1d", "section": "comparator",
            })
            assert response.status_code == 503
            assert response.json() == {"detail": {"code": "MARKET_REFERENCE_SECTION_UNAVAILABLE"}}
