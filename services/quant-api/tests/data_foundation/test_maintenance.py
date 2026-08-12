from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.aggregation import SessionWindow
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.errors import InfrastructureError
from app.market_data.session_clock import SHANGHAI
from app.market_data.maintenance import (
    AuditRequest,
    BarBatch,
    HistoricalDataManager,
    RefreshRequest,
    UpdateRequest,
    _Target,
)
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Exchange, Instrument, MarketPartition, TradingCalendar, TradingSession


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        value.add(Exchange(code="DCE", name="DCE"))
        value.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
        value.commit()
        yield value


class FakeCoverage:
    def __init__(self, ends: dict[tuple[str, str, str, str], tuple[datetime, ...]]) -> None:
        self.ends = ends
        self.session_fact_error: Exception | None = None
        self.session_fact_calls: list[tuple[tuple[str, ...], date]] = []
        self.session_throughs: list[date | None] = []
        self.latest_errors: dict[str, Exception] = {}
        self.latest_calls: list[tuple[str, ...]] = []

    def product_start(self, _symbol: str) -> date:
        return date(2025, 1, 1)

    def latest_complete_day(self, products: tuple[str, ...]) -> date:
        self.latest_calls.append(products)
        error = self.latest_errors.get(products[0])
        if error is not None:
            raise error
        return date(2025, 1, 3)

    def latest_metadata_day(self, _products: tuple[str, ...]) -> date:
        return date(2025, 1, 3)

    def metadata_complete(self, _products: tuple[str, ...], _through: date) -> bool:
        return False

    def require_historical_session_facts(
        self, products: tuple[str, ...], through: date
    ) -> None:
        self.session_fact_calls.append((products, through))
        if self.session_fact_error is not None:
            raise self.session_fact_error

    def expected_bar_ends(
        self,
        key: DatasetKey,
        _year: int,
        _month: int,
        start: date,
        end: date,
    ) -> tuple[datetime, ...]:
        return tuple(
            value
            for value in self.ends.get(key.as_tuple(), ())
            if start <= value.date() <= end
        )

    def expected_bar_ends_for_trading_days(
        self,
        key: DatasetKey,
        trading_days: tuple[date, ...],
    ) -> tuple[datetime, ...]:
        allowed = set(trading_days)
        return tuple(
            value
            for value in self.ends.get(key.as_tuple(), ())
            if value.date() in allowed
        )

    def sessions(
        self,
        _key: DatasetKey,
        _year: int,
        _month: int,
        through: date | None = None,
    ) -> tuple[SessionWindow, ...]:
        self.session_throughs.append(through)
        start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
        return (SessionWindow(start, start + timedelta(minutes=5)),)


class FakeMetadata:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], date]] = []
        self.current_day_calls: list[tuple[tuple[str, ...], date]] = []

    def synchronize(self, products: tuple[str, ...], through: date, _starts) -> date:
        self.calls.append((products, through))
        return through

    def synchronize_current_day(
        self, products: tuple[str, ...], trading_day: date
    ) -> date:
        self.current_day_calls.append((products, trading_day))
        return trading_day


class FakeProvider:
    def __init__(self, bars: dict[tuple[str, str, str, str], tuple[CanonicalBar, ...]]) -> None:
        self.bars = bars
        self.calls: list[tuple[DatasetKey, tuple[datetime, ...]]] = []
        self.fail_symbols: set[str] = set()
        self.quota_after: int | None = None

    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch:
        self.calls.append((key, expected))
        if self.quota_after is not None and len(self.calls) > self.quota_after:
            raise _QuotaExhausted()
        if key.symbol in self.fail_symbols:
            raise RuntimeError("provider failed")
        selected = tuple(bar for bar in self.bars.get(key.as_tuple(), ()) if bar.bar_end in expected)
        return BarBatch(selected)


class _QuotaExhausted(RuntimeError):
    code = "PROVIDER_QUOTA_EXHAUSTED"


class _FailThenQuotaProvider(FakeProvider):
    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch:
        self.calls.append((key, expected))
        if len(self.calls) == 1:
            raise RuntimeError("first target failed")
        raise _QuotaExhausted()


class _TrackingLease:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


def _daily(day: int, close: int) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        datetime(2025, 1, day, 7, tzinfo=UTC),
        date(2025, 1, day),
        value,
        value,
        value,
        value,
        1,
        10,
        20,
    )


def _minute(minute: int) -> CanonicalBar:
    value = Decimal(100 + minute)
    return CanonicalBar(
        datetime(2025, 1, 2, 1, minute, tzinfo=UTC),
        date(2025, 1, 2),
        value,
        value,
        value,
        value,
        1,
        10,
        20,
    )


def _manager(
    session: Session,
    tmp_path,
    coverage: FakeCoverage,
    provider: FakeProvider,
    metadata: FakeMetadata | None = None,
) -> HistoricalDataManager:
    catalog = MarketCatalog(session, tmp_path)
    return HistoricalDataManager(
        catalog=catalog,
        store=CanonicalMonthlyStore(tmp_path),
        coverage=coverage,
        metadata=metadata or FakeMetadata(),
        provider=provider,
    )


def test_update_apply_syncs_metadata_before_provider_and_fixed_through_repeats_noop(
    session, tmp_path
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    ends = (_daily(2, 100).bar_end, _daily(3, 101).bar_end)
    coverage = FakeCoverage({key.as_tuple(): ends})
    provider = FakeProvider({key.as_tuple(): (_daily(2, 100), _daily(3, 101))})
    metadata = FakeMetadata()
    manager = _manager(session, tmp_path, coverage, provider, metadata)

    first = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))
    second = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert first.applied == 1
    assert metadata.calls == [(('jm',), date(2025, 1, 3))]
    assert len(provider.calls) == 1
    assert second.status == "noop"
    assert second.planned == second.applied == second.provider_requests == 0


def test_update_apply_bootstraps_metadata_before_default_latest_complete_day(
    session, tmp_path
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    ends = (_daily(2, 100).bar_end, _daily(3, 101).bar_end)
    coverage = FakeCoverage({key.as_tuple(): ends})
    provider = FakeProvider({key.as_tuple(): (_daily(2, 100), _daily(3, 101))})
    events: list[str] = []
    metadata_ready = False

    def latest_complete_day(products: tuple[str, ...]) -> date:
        coverage.latest_calls.append(products)
        events.append("latest_complete_day")
        if not metadata_ready:
            raise InfrastructureError("TRADING_SESSION_MISSING")
        return date(2025, 1, 3)

    class OrderingMetadata(FakeMetadata):
        def synchronize(self, products, through, starts) -> date:
            nonlocal metadata_ready
            events.append("synchronize")
            metadata_ready = True
            return super().synchronize(products, through, starts)

    coverage.latest_complete_day = latest_complete_day  # type: ignore[method-assign]
    metadata = OrderingMetadata()
    manager = _manager(session, tmp_path, coverage, provider, metadata)

    result = manager.update(UpdateRequest(("jm",), None, None, True))

    assert result.status == "passed"
    assert events[:2] == ["synchronize", "latest_complete_day"]
    assert metadata.calls == [(('jm',), date(2025, 1, 3))]


def test_update_apply_blocks_without_acquiring_global_maintenance_lock(
    session, tmp_path, monkeypatch
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    ends = (_daily(2, 100).bar_end,)
    coverage = FakeCoverage({key.as_tuple(): ends})
    provider = FakeProvider({key.as_tuple(): (_daily(2, 100),)})
    metadata = FakeMetadata()
    manager = _manager(session, tmp_path, coverage, provider, metadata)
    monkeypatch.setattr(
        manager.catalog,
        "acquire_maintenance_lock",
        lambda: None,
        raising=False,
    )

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "blocked"
    assert result.stop_reason == "maintenance_locked"
    assert metadata.calls == []
    assert provider.calls == []


def test_update_syncs_current_day_metadata_inside_the_maintenance_lease(
    session, tmp_path, monkeypatch
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bar = _daily(2, 100)
    coverage = FakeCoverage({key.as_tuple(): (bar.bar_end,)})
    metadata = FakeMetadata()
    manager = _manager(session, tmp_path, coverage, FakeProvider({key.as_tuple(): (bar,)}), metadata)
    events: list[str] = []

    class Lease(_TrackingLease):
        def release(self) -> None:
            events.append("release")
            super().release()

    lease = Lease()

    def acquire():
        events.append("acquire")
        return lease

    monkeypatch.setattr(manager.catalog, "acquire_maintenance_lock", acquire)
    original_sync_current_day = metadata.synchronize_current_day

    def sync_current_day(products: tuple[str, ...], trading_day: date) -> date:
        events.append("current_day")
        return original_sync_current_day(products, trading_day)

    monkeypatch.setattr(metadata, "synchronize_current_day", sync_current_day)

    result = manager.update(
        UpdateRequest(
            ("jm",),
            None,
            date(2025, 1, 3),
            True,
            sync_current_day_metadata=True,
        )
    )

    assert result.status == "passed"
    assert metadata.current_day_calls == [(('jm',), date(2025, 1, 3))]
    assert events == ["acquire", "current_day", "release"]


def test_since_is_check_lower_bound_and_does_not_replace_covered_partition(
    session, tmp_path
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bars = (_daily(2, 100), _daily(3, 101))
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in bars)})
    provider = FakeProvider({key.as_tuple(): bars})
    manager = _manager(session, tmp_path, coverage, provider)
    manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    result = manager.update(
        UpdateRequest(("jm",), date(2025, 1, 2), date(2025, 1, 3), True)
    )

    assert result.status == "noop"
    assert len(provider.calls) == 1


def test_contract_targets_cover_only_rank1_mapping_days(session, tmp_path) -> None:
    continuous = DatasetKey("continuous", "jm", "MAIN", "1d")
    contract = DatasetKey("contract", "jm", "JM2509", "1d")
    coverage = FakeCoverage({
        continuous.as_tuple(): (_daily(2, 100).bar_end, _daily(3, 101).bar_end),
        contract.as_tuple(): (_daily(2, 200).bar_end, _daily(3, 201).bar_end),
    })
    provider = FakeProvider({})
    manager = _manager(session, tmp_path, coverage, provider)
    manager.catalog.upsert_main_contracts((("jm", date(2025, 1, 3), "JM2509"),))
    session.commit()

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), False))

    contract_targets = [
        target for target in result.target_windows if target["dataset"] == contract.as_tuple()
    ]
    assert contract_targets == [{
        "dataset": contract.as_tuple(),
        "year": 2025,
        "month": 1,
        "window_start": _daily(3, 201).bar_end.isoformat(),
        "window_end": _daily(3, 201).bar_end.isoformat(),
        "missing_bar_count": 1,
    }]


def test_derived_reads_canonical_1m_and_never_calls_provider(session, tmp_path) -> None:
    source_key = DatasetKey("continuous", "jm", "MAIN", "1m")
    derived_key = DatasetKey("continuous", "jm", "MAIN", "5m")
    source = tuple(_minute(index) for index in range(1, 6))
    coverage = FakeCoverage(
        {
            source_key.as_tuple(): tuple(bar.bar_end for bar in source),
            derived_key.as_tuple(): (source[-1].bar_end,),
        }
    )
    provider = FakeProvider({source_key.as_tuple(): source})
    manager = _manager(session, tmp_path, coverage, provider)

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.applied == 2
    assert [call[0].frequency.value for call in provider.calls] == ["1m"]
    assert manager.store.read_month(derived_key, 2025, 1)[0].close == Decimal("105")


def test_derived_limits_session_lookup_to_target_coverage(session, tmp_path) -> None:
    source_key = DatasetKey("continuous", "jm", "MAIN", "1m")
    derived_key = DatasetKey("continuous", "jm", "MAIN", "5m")
    source = tuple(_minute(index) for index in range(1, 6))
    coverage = FakeCoverage(
        {
            source_key.as_tuple(): tuple(bar.bar_end for bar in source),
            derived_key.as_tuple(): (source[-1].bar_end,),
        }
    )
    manager = _manager(session, tmp_path, coverage, FakeProvider({source_key.as_tuple(): source}))

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "passed"
    assert coverage.session_throughs == [source[-1].bar_end.date()]


def test_derived_ignores_later_same_month_1m_outside_target_sessions(session, tmp_path) -> None:
    source_key = DatasetKey("continuous", "jm", "MAIN", "1m")
    derived_key = DatasetKey("continuous", "jm", "MAIN", "5m")
    source = tuple(_minute(index) for index in range(1, 11))
    coverage = FakeCoverage({
        source_key.as_tuple(): tuple(bar.bar_end for bar in source),
        derived_key.as_tuple(): (source[4].bar_end,),
    })
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))
    _publish_existing(manager, source_key, source)

    manager._publish_derived(
        _Target(
            derived_key,
            2025,
            1,
            (source[4].bar_end,),
            (source[4].bar_end,),
            (),
        )
    )

    assert manager.store.read_month(derived_key, 2025, 1)[0].bar_end == source[4].bar_end


def test_fixed_through_update_preserves_later_same_month_canonical_bars(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    earlier = _daily(2, 100)
    later = _daily(3, 101)
    coverage = FakeCoverage({key.as_tuple(): (earlier.bar_end, later.bar_end)})
    manager = _manager(session, tmp_path, coverage, FakeProvider({key.as_tuple(): (earlier,)}))
    _publish_existing(manager, key, (later,))

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 2), True))

    assert result.status == "passed"
    assert tuple(
        bar.bar_end for bar in manager.store.read_month(key, 2025, 1)
    ) == (earlier.bar_end, later.bar_end)


def test_fixed_through_rebuilds_night_bar_from_future_trading_day(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    earlier = _daily(2, 100)
    future_night = CanonicalBar(
        datetime(2025, 1, 3, 13, 1, tzinfo=UTC),
        date(2025, 1, 4),
        Decimal("999"),
        Decimal("999"),
        Decimal("999"),
        Decimal("999"),
        1,
        10,
        20,
    )
    coverage = FakeCoverage({key.as_tuple(): (earlier.bar_end,)})
    manager = _manager(session, tmp_path, coverage, FakeProvider({key.as_tuple(): (earlier,)}))
    _publish_existing(manager, key, (future_night,))

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 2), True))

    assert result.status == "passed"
    assert manager.store.read_month(key, 2025, 1) == (earlier,)


def test_existing_complete_1m_rebuilds_derived_before_provider_quota(session, tmp_path) -> None:
    minute = DatasetKey("continuous", "jm", "MAIN", "1m")
    derived = DatasetKey("continuous", "jm", "MAIN", "5m")
    daily = DatasetKey("continuous", "jm", "MAIN", "1d")
    source = tuple(_minute(index) for index in range(1, 6))
    coverage = FakeCoverage({
        minute.as_tuple(): tuple(bar.bar_end for bar in source),
        derived.as_tuple(): (source[-1].bar_end,),
        daily.as_tuple(): (_daily(2, 100).bar_end,),
    })
    provider = FakeProvider({daily.as_tuple(): (_daily(2, 100),)})
    provider.quota_after = 0
    manager = _manager(session, tmp_path, coverage, provider)
    _publish_existing(manager, minute, source)

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "partial"
    assert manager.store.read_month(derived, 2025, 1)[0].close == Decimal("105")
    assert [call[0].frequency for call in provider.calls] == [BarFrequency.D1]


def test_dry_run_plans_without_metadata_provider_or_writes(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    coverage = FakeCoverage({key.as_tuple(): (_daily(2, 100).bar_end,)})
    provider = FakeProvider({})
    metadata = FakeMetadata()
    manager = _manager(session, tmp_path, coverage, provider, metadata)

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), False))

    assert result.status == "planned"
    assert result.planned == 1
    assert metadata.calls == []
    assert provider.calls == []
    assert not tuple(tmp_path.rglob("part.parquet"))
    assert result.as_payload()["targets"] == [
        {
            "dataset": key.as_tuple(),
            "year": 2025,
            "month": 1,
            "window_start": _daily(2, 100).bar_end.isoformat(),
            "window_end": _daily(2, 100).bar_end.isoformat(),
            "missing_bar_count": 1,
        }
    ]


def test_refresh_replaces_an_existing_direct_month(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    old = _daily(2, 100)
    replacement = _daily(2, 200)
    coverage = FakeCoverage({key.as_tuple(): (replacement.bar_end,)})
    provider = FakeProvider({key.as_tuple(): (replacement,)})
    manager = _manager(session, tmp_path, coverage, provider)
    _publish_existing(manager, key, (old,))

    result = manager.refresh(RefreshRequest("jm", date(2025, 1, 1), date(2025, 1, 3), True))

    assert result.status == "passed"
    assert result.provider_requests == 1
    assert manager.store.read_month(key, 2025, 1) == (replacement,)


def test_refresh_mid_month_rebuilds_the_complete_intersecting_month(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bars = (_daily(2, 200), _daily(3, 201))
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in bars)})
    provider = FakeProvider({key.as_tuple(): bars})
    manager = _manager(session, tmp_path, coverage, provider)

    manager.refresh(RefreshRequest("jm", date(2025, 1, 3), date(2025, 1, 3), True))

    assert provider.calls[0][1] == tuple(bar.bar_end for bar in bars)
    assert manager.store.read_month(key, 2025, 1) == bars


def test_refresh_can_limit_force_plan_to_daily_and_weekly_frequencies(session, tmp_path) -> None:
    daily = DatasetKey("continuous", "jm", "MAIN", "1d")
    minute = DatasetKey("continuous", "jm", "MAIN", "1m")
    coverage = FakeCoverage(
        {
            daily.as_tuple(): (_daily(2, 100).bar_end,),
            minute.as_tuple(): (_minute(1).bar_end,),
        }
    )
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    result = manager.refresh(
        RefreshRequest(
            "jm",
            date(2025, 1, 2),
            date(2025, 1, 2),
            False,
            frozenset({BarFrequency.D1, BarFrequency.W1}),
        )
    )

    assert result.status == "planned"
    assert {item["dataset"][3] for item in result.target_windows} == {"1d"}


def test_update_rebuilds_a_partition_with_extra_bar(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    expected = (_daily(2, 200), _daily(3, 201))
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in expected)})
    provider = FakeProvider({key.as_tuple(): expected})
    manager = _manager(session, tmp_path, coverage, provider)
    _publish_existing(manager, key, expected + (_daily(4, 999),))

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "passed"
    assert provider.calls[0][1] == tuple(bar.bar_end for bar in expected)
    assert manager.store.read_month(key, 2025, 1) == expected


def test_audit_and_update_rebuild_when_catalog_uri_is_stale(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bars = (_daily(2, 200),)
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in bars)})
    provider = FakeProvider({key.as_tuple(): bars})
    manager = _manager(session, tmp_path, coverage, provider)
    _publish_existing(manager, key, bars)
    row = session.scalar(select(MarketPartition))
    assert row is not None
    row.file_uri = "stale/part.parquet"
    session.commit()

    audit = manager.audit(AuditRequest(("jm",)))
    assert [(finding.code, finding.category) for finding in audit.findings] == [
        ("PARTITION_CATALOG_MISMATCH", "physical")
    ]
    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "passed"
    assert provider.calls[0][1] == tuple(bar.bar_end for bar in bars)


def test_quota_partial_preserves_completed_months_and_next_update_resumes(session, tmp_path) -> None:
    daily = DatasetKey("continuous", "jm", "MAIN", "1d")
    weekly = DatasetKey("continuous", "jm", "MAIN", "1w")
    daily_bar = _daily(2, 100)
    weekly_bar = _daily(3, 101)
    coverage = FakeCoverage({
        daily.as_tuple(): (daily_bar.bar_end,),
        weekly.as_tuple(): (weekly_bar.bar_end,),
    })
    provider = FakeProvider({daily.as_tuple(): (daily_bar,), weekly.as_tuple(): (weekly_bar,)})
    provider.quota_after = 1
    manager = _manager(session, tmp_path, coverage, provider)

    partial = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert partial.status == "partial"
    assert partial.stop_reason == "provider_quota_exhausted"
    assert partial.provider_requests == 2
    assert partial.applied == 1
    assert manager.store.read_month(daily, 2025, 1) == (daily_bar,)
    assert not manager.catalog.all_partitions(weekly)
    provider.quota_after = None
    resumed = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert resumed.status == "passed"
    assert [call[0].frequency for call in provider.calls] == [
        BarFrequency.D1,
        BarFrequency.W1,
        BarFrequency.W1,
    ]


def test_quota_partial_preserves_earlier_dataset_failures(session, tmp_path) -> None:
    daily = DatasetKey("continuous", "jm", "MAIN", "1d")
    weekly = DatasetKey("continuous", "jm", "MAIN", "1w")
    coverage = FakeCoverage({
        daily.as_tuple(): (_daily(2, 100).bar_end,),
        weekly.as_tuple(): (_daily(3, 101).bar_end,),
    })
    manager = _manager(
        session,
        tmp_path,
        coverage,
        _FailThenQuotaProvider({}),
    )

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "partial"
    assert result.stop_reason == "provider_quota_exhausted"
    assert result.failed == 1
    assert result.failures == ({
        "dataset": daily.as_tuple(),
        "year": 2025,
        "month": 1,
        "reason_code": "RuntimeError",
    },)


def test_refresh_holds_maintenance_lock_until_provider_fetch_completes(
    session, tmp_path, monkeypatch
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bar = _daily(2, 100)
    coverage = FakeCoverage({key.as_tuple(): (bar.bar_end,)})
    provider = FakeProvider({key.as_tuple(): (bar,)})
    manager = _manager(session, tmp_path, coverage, provider)
    lease = _TrackingLease()
    monkeypatch.setattr(manager.catalog, "acquire_maintenance_lock", lambda: lease)

    original_fetch = provider.fetch

    def fetch_while_locked(*args, **kwargs):
        assert not lease.released
        return original_fetch(*args, **kwargs)

    monkeypatch.setattr(provider, "fetch", fetch_while_locked)
    result = manager.refresh(RefreshRequest("jm", date(2025, 1, 2), date(2025, 1, 3), True))

    assert result.status == "passed"
    assert lease.released


def test_update_since_rebuilds_an_unreadable_intersecting_month(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bars = (_daily(2, 200), _daily(3, 201))
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in bars)})
    provider = FakeProvider({key.as_tuple(): bars})
    manager = _manager(session, tmp_path, coverage, provider)
    _publish_existing(manager, key, bars)
    manager.catalog.all_partitions(key)[0].file_path.write_bytes(b"invalid")

    result = manager.update(UpdateRequest(("jm",), date(2025, 1, 3), date(2025, 1, 3), True))

    assert result.status == "passed"
    assert provider.calls[0][1] == tuple(bar.bar_end for bar in bars)
    assert manager.store.read_month(key, 2025, 1) == bars


def test_refresh_apply_fails_closed_when_rank1_map_is_missing(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bar = _daily(2, 200)
    coverage = FakeCoverage({key.as_tuple(): (bar.bar_end,)})
    manager = _manager(session, tmp_path, coverage, FakeProvider({key.as_tuple(): (bar,)}))
    session.add(TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 2), is_trading_day=True))
    session.commit()

    with pytest.raises(ValueError, match="MAIN_CONTRACT_MAP_MISSING"):
        manager.refresh(RefreshRequest("jm", date(2025, 1, 2), date(2025, 1, 2), True))


def test_update_fails_before_provider_when_historical_session_facts_are_missing(
    session, tmp_path
) -> None:
    from app.market_data.errors import InfrastructureError

    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bar = _daily(2, 100)
    coverage = FakeCoverage({key.as_tuple(): (bar.bar_end,)})
    coverage.session_fact_error = InfrastructureError("HISTORICAL_SESSION_FACT_MISSING")
    provider = FakeProvider({key.as_tuple(): (bar,)})
    manager = _manager(session, tmp_path, coverage, provider)

    with pytest.raises(InfrastructureError, match="HISTORICAL_SESSION_FACT_MISSING"):
        manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert coverage.session_fact_calls == [(("jm",), date(2025, 1, 3))]
    assert provider.calls == []


def test_dataset_failure_is_isolated(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    coverage = FakeCoverage({key.as_tuple(): (_daily(2, 100).bar_end,)})
    provider = FakeProvider({})
    provider.fail_symbols.add("jm")
    manager = _manager(session, tmp_path, coverage, provider)

    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "failed"
    assert result.failed == 1


def test_catalog_commit_failure_leaves_published_file_for_later_repair(
    session, tmp_path, monkeypatch
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    old_bar = _daily(2, 100)
    new_bar = _daily(3, 101)
    coverage = FakeCoverage({key.as_tuple(): (old_bar.bar_end, new_bar.bar_end)})
    provider = FakeProvider({key.as_tuple(): (new_bar,)})
    manager = _manager(session, tmp_path, coverage, provider)
    _publish_existing(manager, key, (old_bar,))
    partition = manager.catalog.all_partitions(key)[0]
    old_parquet = partition.file_path.read_bytes()

    def fail_commit() -> None:
        raise SQLAlchemyError("injected")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(SQLAlchemyError, match="injected"):
        manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert partition.file_path.read_bytes() != old_parquet
    assert manager.store.read_month(key, 2025, 1) == (old_bar, new_bar)
    assert not tuple(tmp_path.rglob("*.bak"))


def test_strict_read_failure_leaves_partition_for_next_update(
    session, tmp_path, monkeypatch
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bar = _daily(2, 100)
    coverage = FakeCoverage({key.as_tuple(): (bar.bar_end,)})
    manager = _manager(session, tmp_path, coverage, FakeProvider({key.as_tuple(): (bar,)}))

    def unreadable(*_args, **_kwargs):
        from app.market_data.storage import StorageError

        raise StorageError("PARTITION_UNREADABLE")

    monkeypatch.setattr(manager.store, "read_month", unreadable)
    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), True))

    assert result.status == "failed"
    assert result.failures[0]["reason_code"] == "STRICT_READ_VERIFICATION_FAILED"
    assert tuple(tmp_path.rglob("part.parquet"))
    assert not tuple(tmp_path.rglob("manifest.json"))
    assert not tuple(tmp_path.rglob("*.bak"))


def test_strict_verify_weekly_short_week_excludes_previous_friday(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1w")
    previous = CanonicalBar(datetime(2025, 3, 28, 7, tzinfo=UTC), date(2025, 3, 28), *(Decimal("100"),) * 4, 1, 10, 20)
    expected = tuple(
        CanonicalBar(datetime(2025, 4, day, 7, tzinfo=UTC), date(2025, 4, day), *(Decimal("100"),) * 4, 1, 10, 20)
        for day in (3, 11, 18, 25, 30)
    )
    manager = _manager(session, tmp_path, FakeCoverage({}), FakeProvider({}))
    for year, month, bars in ((2025, 3, (previous,)), (2025, 4, expected)):
        partition = manager.store.publish(PublishRequest(key, year, month, bars, tuple(bar.bar_end for bar in bars)))
        manager.catalog.register_partition(partition)
    target = _Target(key, 2025, 4, tuple(bar.bar_end for bar in expected), tuple(bar.bar_end for bar in expected), ())

    manager._strict_verify(target)


def test_audit_reports_missing_partition_without_remote_calls(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    coverage = FakeCoverage({key.as_tuple(): (_daily(2, 100).bar_end,)})
    provider = FakeProvider({})
    manager = _manager(session, tmp_path, coverage, provider)
    result = manager.audit(AuditRequest(("jm",)))

    assert result.status == "failed"
    assert {finding.code for finding in result.findings} == {"EXPECTED_PARTITION_MISSING"}
    assert provider.calls == []


def test_audit_honors_explicit_fixed_through_boundary(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    result = manager.audit(AuditRequest(("jm",), through=date(2025, 1, 2)))

    assert result.through == date(2025, 1, 2)
    assert coverage.latest_calls == []


def test_audit_uses_preceding_complete_day_when_current_session_metadata_is_pending(
    session, tmp_path
) -> None:
    starts = tmp_path / "starts.csv"
    starts.write_text("product,window_start,note\njm,2025-01-09,test\n")
    floor = tmp_path / "history-floor.txt"
    floor.write_text("2025-01-09\n")
    for trading_day in (date(2025, 1, 9), date(2025, 1, 10)):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=trading_day,
                is_trading_day=True,
            )
        )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="day",
            start_time=time(9),
            end_time=time(9, 5),
            effective_from=date(2025, 1, 9),
            effective_to=date(2025, 1, 9),
            crosses_midnight=False,
            is_active=True,
        )
    )
    session.commit()
    coverage = DatabaseCoverageSource(
        session,
        starts,
        history_floor_path=floor,
        now=lambda: datetime(2025, 1, 10, 10, tzinfo=SHANGHAI),
    )
    provider = FakeProvider({})
    manager = _manager(session, tmp_path, coverage, provider)  # type: ignore[arg-type]

    result = manager.audit(AuditRequest(("jm",)))

    assert result.through == date(2025, 1, 9)
    assert provider.calls == []


def test_audit_preserves_unreadable_partition_reason(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bars = (_daily(2, 100),)
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in bars)})
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))
    _publish_existing(manager, key, bars)
    manager.catalog.all_partitions(key)[0].file_path.write_bytes(b"invalid")

    result = manager.audit(AuditRequest(("jm",)))

    assert [(item.code, item.category) for item in result.findings] == [
        ("PARTITION_UNREADABLE", "physical")
    ]


def test_audit_continues_after_known_session_metadata_failure(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    coverage.latest_errors["a"] = InfrastructureError("TRADING_SESSION_MISSING")
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    result = manager.audit(AuditRequest(("a", "jm")))

    assert result.status == "failed"
    assert result.findings[0].code == "TRADING_SESSION_MISSING"
    assert result.findings[0].category == "metadata_session"
    assert result.findings[0].dataset == ("metadata", "a", "session", "1d")
    assert result.findings[0].year is None
    assert result.findings[0].month is None
    assert coverage.latest_calls == [("a",), ("jm",)]


def test_audit_reports_calendar_metadata_failure(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    coverage.latest_errors["jm"] = InfrastructureError("TRADING_CALENDAR_MISSING")
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    result = manager.audit(AuditRequest(("jm",)))

    assert [(item.code, item.category) for item in result.findings] == [
        ("TRADING_CALENDAR_MISSING", "metadata_calendar")
    ]


def test_audit_reraises_unknown_coverage_error(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    coverage.latest_errors["jm"] = RuntimeError("database disconnected")
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    with pytest.raises(RuntimeError, match="database disconnected"):
        manager.audit(AuditRequest(("jm",)))


def _publish_existing(
    manager: HistoricalDataManager,
    key: DatasetKey,
    bars: tuple[CanonicalBar, ...],
) -> None:
    published = manager.store.publish(PublishRequest(
        key,
        2025,
        1,
        bars,
        tuple(bar.bar_end for bar in bars),
    ))
    manager.catalog.register_partition(published)
    manager.catalog.session.commit()
