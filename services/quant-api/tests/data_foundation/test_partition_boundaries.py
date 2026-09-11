"""Real coverage/store boundary contract on isolated authority and temporary Parquet."""
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, event, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import CatalogPartition
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest, StorageError
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession


@pytest.fixture
def authority(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Exchange(code="DCE", name="DCE"))
        session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
        session.add(Contract(contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=date(2024, 12, 1), expired_date=date(2025, 3, 1), provider="rqdata"))
        first = date(2024, 12, 27)
        for offset in range(45):
            day = first + timedelta(days=offset)
            session.add(TradingCalendar(exchange_code="DCE", trade_date=day,
                is_trading_day=day.weekday() < 5, provider="rqdata"))
            if day.weekday() < 5:
                session.add(TradingSession(exchange_code="DCE", instrument_symbol="jm",
                    session_name="day", start_time=time(9), end_time=time(10, 7),
                    effective_from=day, effective_to=day, is_active=True, provider="rqdata"))
        session.commit()
        starts = tmp_path / "starts.csv"
        starts.write_text("product,window_start,note\njm,2025-01-01,test\n")
        floor = tmp_path / "floor.txt"
        floor.write_text("2025-01-01\n")
        coverage = DatabaseCoverageSource(session, starts, history_floor_path=floor)
        yield session, coverage, tmp_path
    engine.dispose()


def _key(kind, frequency="1m"):
    return DatasetKey(kind, "jm", "JM2509" if kind == "contract" else "MAIN", frequency)


def _bar(day=date(2025, 1, 6), minute=1, *, hour=1):
    end = datetime.combine(day, time(hour), tzinfo=UTC) + timedelta(minutes=minute)
    value = Decimal("100")
    return CanonicalBar(end, day, value, value, value, value, 1, 10, 20)


def _request(key, bars):
    return PublishRequest(key, bars[0].trading_day.year, bars[0].trading_day.month,
        bars, tuple(bar.bar_end for bar in bars))


def _partition(result):
    return CatalogPartition(result.dataset, result.year, result.month, result.coverage_start,
        result.coverage_end, result.parquet_path, result.row_count)


@pytest.mark.parametrize("kind", ["continuous", "contract"])
def test_publish_and_independent_readback_metadata_sql_does_not_grow_with_bars(authority, kind):
    session, coverage, root = authority
    store = CanonicalMonthlyStore(root / "canonical", boundary_validator=coverage.valid_boundaries)
    counts = []
    selects = []
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(1)
    event.listen(session.get_bind(), "before_cursor_execute", count)
    try:
        for day_count, size in ((days, size) for days in (1, 3) for size in (1, 5, 60)):
            bars = tuple(_bar(date(2025, 1, 6 + day), minute)
                for day in range(day_count) for minute in range(1, size + 1))
            selects.clear()
            published = store.publish(_request(_key(kind), bars))
            publish_count = len(selects)
            selects.clear()
            assert store.read_catalog_partition(_partition(published)) == bars
            counts.append((publish_count, len(selects)))
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", count)
    print(f"{kind=} sizes=(1,5,60) days=(1,3) publish/readback SELECT counts: {counts}")
    assert all(left > 0 and right > 0 for left, right in counts)
    assert len(set(counts)) == 1


@pytest.mark.parametrize("kind", ["continuous", "contract"])
@pytest.mark.parametrize(("frequency", "minutes"), [
    ("1m", (1, 67)), ("5m", (5, 65, 67)), ("15m", (15, 60, 67)),
    ("30m", (30, 60, 67)), ("60m", (60, 67)), ("1d", (67,)), ("1w", (67,)),
])
def test_all_frequencies_keep_session_end_and_short_tail(authority, kind, frequency, minutes):
    _session, coverage, root = authority
    day = date(2025, 1, 10)  # Complete ISO week, including its last trading day.
    bars = tuple(_bar(day, minute) for minute in minutes)
    store = CanonicalMonthlyStore(root / "canonical", boundary_validator=coverage.valid_boundaries)
    result = store.publish(_request(_key(kind, frequency), bars))
    assert store.read_catalog_partition(_partition(result)) == bars
    bad = (_bar(day, 68),)
    with pytest.raises(StorageError, match="SESSION_BOUNDARY_INVALID"):
        store.publish(_request(_key(kind, frequency), bad))


@pytest.mark.parametrize("kind", ["continuous", "contract"])
def test_sparse_dates_do_not_require_unrelated_calendar_or_session_facts(authority, kind):
    session, coverage, _root = authority
    gap = date(2025, 1, 7)
    session.execute(delete(TradingCalendar).where(TradingCalendar.trade_date == gap))
    session.execute(delete(TradingSession).where(TradingSession.effective_from == gap))
    session.commit()
    assert coverage.valid_boundaries(_key(kind), (_bar(), _bar(date(2025, 1, 8))))


@pytest.mark.parametrize("kind", ["continuous", "contract"])
def test_pair_membership_does_not_accept_another_days_timestamp(authority, kind):
    _session, coverage, _root = authority
    bars = (_bar(), replace(_bar(date(2025, 1, 7)), trading_day=date(2025, 1, 6)))
    assert not coverage.valid_boundaries(_key(kind), bars)
    assert not coverage.valid_boundaries(_key(kind), ())


@pytest.mark.parametrize("kind", ["continuous", "contract"])
@pytest.mark.parametrize("fault", ["missing_calendar", "closed_calendar", "inactive_session"])
def test_authority_faults_keep_existing_rejection_contract(authority, kind, fault):
    from app.market_data.errors import InfrastructureError
    session, coverage, _root = authority
    day = date(2025, 1, 6)
    if fault == "missing_calendar":
        session.execute(delete(TradingCalendar).where(TradingCalendar.trade_date == day))
    elif fault == "closed_calendar":
        session.execute(update(TradingCalendar).where(TradingCalendar.trade_date == day).values(is_trading_day=False))
    else:
        session.execute(update(TradingSession).where(TradingSession.effective_from == day).values(is_active=False))
    session.commit()
    if kind == "continuous" and fault == "inactive_session":
        with pytest.raises(InfrastructureError, match="TRADING_SESSION_MISSING"):
            coverage.valid_boundaries(_key(kind), (_bar(),))
    else:
        assert not coverage.valid_boundaries(_key(kind), (_bar(),))


@pytest.mark.parametrize("kind", ["continuous", "contract"])
def test_night_window_uses_previous_trading_day_and_rejects_missing_context(authority, kind):
    from app.market_data.errors import InfrastructureError
    session, coverage, _root = authority
    monday = date(2025, 1, 6)
    session.add(TradingSession(exchange_code="DCE", instrument_symbol="jm", session_name="night",
        start_time=time(21), end_time=time(2, 30), crosses_midnight=True,
        effective_from=monday, effective_to=monday, provider="rqdata", is_active=True))
    session.commit()
    bars = (replace(_bar(date(2025, 1, 3), 1, hour=13), trading_day=monday),
        replace(_bar(date(2025, 1, 3), 30, hour=18), trading_day=monday))
    assert coverage.valid_boundaries(_key(kind), bars)
    wrong = (replace(bars[0], bar_end=bars[0].bar_end + timedelta(days=2)),)
    assert not coverage.valid_boundaries(_key(kind), wrong)
    session.execute(delete(TradingCalendar).where(TradingCalendar.trade_date < monday))
    session.commit()
    with pytest.raises(InfrastructureError, match="PREVIOUS_TRADING_DAY_MISSING"):
        coverage.valid_boundaries(_key(kind), bars)


@pytest.mark.parametrize("kind", ["continuous", "contract"])
def test_weekly_boundary_requires_context_beyond_candidate_month(authority, kind):
    _session, coverage, _root = authority
    coverage.starts["jm"] = date(2024, 12, 1)
    coverage.history_floor = date(2024, 12, 1)
    key = _key(kind, "1w")
    assert not coverage.valid_boundaries(key, (_bar(date(2024, 12, 31), 67),))
    assert coverage.valid_boundaries(key, (_bar(date(2025, 1, 3), 67),))
    assert not coverage.valid_boundaries(key, (_bar(date(2025, 1, 2), 67),))


def test_contract_lifecycle_and_pre_rank1_warmup_keep_separate_history_floor(authority):
    session, coverage, _root = authority
    session.execute(update(Contract).values(listed_date=date(2025, 1, 6), expired_date=date(2025, 1, 9)))
    session.commit()
    coverage.history_floor = date(2025, 1, 8)
    key = _key("contract")  # No rank1 map exists: same-contract warmup remains valid.
    assert coverage.valid_boundaries(key, (_bar(), _bar(date(2025, 1, 8))))
    assert not coverage.valid_boundaries(key, (_bar(date(2025, 1, 3)), _bar()))
    assert not coverage.valid_boundaries(key, (_bar(), _bar(date(2025, 1, 9))))
    assert not coverage.valid_boundaries(_key("continuous"), (_bar(),))
    assert coverage.valid_boundaries(_key("continuous"), (_bar(date(2025, 1, 8)),))


@pytest.mark.parametrize("kind", ["continuous", "contract"])
@pytest.mark.parametrize("fact", ["session", "lifecycle"])
def test_readback_observes_committed_authority_changes_without_cached_validation(authority, kind, fact):
    from app.market_data.errors import InfrastructureError
    session, coverage, root = authority
    store = CanonicalMonthlyStore(root / "canonical", boundary_validator=coverage.valid_boundaries)
    result = store.publish(_request(_key(kind), (_bar(),)))
    assert store.read_catalog_partition(_partition(result)) == (_bar(),)
    if fact == "session":
        session.execute(update(TradingSession).where(TradingSession.effective_from == date(2025, 1, 6))
            .values(start_time=time(9, 2)))
    else:
        session.execute(update(Contract).values(expired_date=date(2025, 1, 6)))
    session.commit()
    with pytest.raises((StorageError, InfrastructureError)):
        store.read_catalog_partition(_partition(result))


def test_database_failure_propagates_without_false_success(authority):
    from sqlalchemy.exc import OperationalError
    session, coverage, _root = authority
    Contract.__table__.drop(session.get_bind())
    with pytest.raises(OperationalError):
        coverage.valid_boundaries(_key("contract"), (_bar(),))


@pytest.mark.parametrize("kind", ["continuous", "contract"])
@pytest.mark.parametrize("fault", ["hash", "schema", "row_count", "coverage", "missing_file", "expected"])
def test_real_composition_strict_read_fault_keeps_committed_pointer(authority, kind, fault):
    import hashlib
    import pyarrow as pa
    import pyarrow.parquet as pq
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import build_historical_data_manager
    from app.market_data.historical_data_manager import _Target

    session, _coverage, root = authority
    config = root / "config/data/universe"
    config.mkdir(parents=True)
    (config / "product_window_starts.csv").write_bytes((root / "starts.csv").read_bytes())
    (config / "active_history_floor.txt").write_bytes((root / "floor.txt").read_bytes())
    manager = build_historical_data_manager(session, data_root=root / "canonical", config_root=root / "config")
    key = _key(kind)
    old = manager.store.publish(_request(key, (_bar(),)))
    target = _Target(key, 2025, 1, (_bar().bar_end,), (_bar().bar_end,), ())
    manager._commit_partition(old, target)
    pointer = manager.catalog.all_partitions(key)[0]
    candidate = manager.store.publish(_request(key, (replace(_bar(), close=Decimal("99"), low=Decimal("99")),)))
    if fault == "hash":
        candidate.parquet_path.write_bytes(b"corrupt")
    elif fault == "schema":
        pq.write_table(pa.table({"wrong_column": [1]}), candidate.parquet_path)
        renamed = candidate.parquet_path.with_name(
            f"part.{hashlib.sha256(candidate.parquet_path.read_bytes()).hexdigest()}.parquet")
        candidate.parquet_path.rename(renamed)
        candidate = replace(candidate, parquet_path=renamed)
    elif fault == "row_count":
        candidate = replace(candidate, row_count=2)
    elif fault == "coverage":
        candidate = replace(candidate, coverage_start=candidate.coverage_start - timedelta(minutes=1))
    elif fault == "missing_file":
        candidate.parquet_path.unlink()
    else:
        target = replace(target, expected=(target.expected[0], _bar(minute=2).bar_end))
    with pytest.raises(StorageError, match="STRICT_READ_VERIFICATION_FAILED"):
        manager._commit_partition(candidate, target)
    with Session(session.get_bind()) as reader:
        committed = MarketCatalog(reader, root / "canonical").all_partitions(key)
        assert committed == (pointer,)
    assert manager.store.read_catalog_partition(pointer) == (_bar(),)


def test_continuous_provider_and_intraday_floor_remain_fail_closed(authority):
    _session, coverage, _root = authority
    coverage.starts["jm"] = date(2025, 1, 8)
    assert not coverage.valid_boundaries(_key("continuous"), (_bar(),))
    coverage.starts["jm"] = date(2000, 1, 1)
    coverage.history_floor = date(2000, 1, 1)
    assert not coverage.valid_boundaries(_key("continuous"), (_bar(date(2009, 12, 31)),))
