from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import CatalogError, ContractFact, MarketCatalog
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    DatasetKey,
    ResolvedContractSegment,
    SeriesQuery,
    SeriesPageQuery,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.source_quality import (
    NonpositiveCloseFact,
    PriceUnavailableFact,
    source_quality_fact_from_record,
)
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    MarketPartition,
    TradingCalendar,
    TradingSession,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            (
                Exchange(code="DCE", name="DCE"),
                Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True),
                TradingSession(
                    exchange_code="DCE",
                    instrument_symbol="jm",
                    session_name="day",
                    start_time=time(9),
                    end_time=time(15),
                    effective_from=date(2025, 1, 1),
                    is_active=True,
                ),
            )
        )
        session.commit()
        yield session


def _bar(day: int, close: int, *, month: int = 1, hour: int = 7) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        datetime(2025, month, day, hour, tzinfo=UTC),
        date(2025, month, day),
        value,
        value + 1,
        value - 1,
        value,
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )


def _publish(
    catalog: MarketCatalog,
    store: CanonicalMonthlyStore,
    key: DatasetKey,
    bars: tuple[CanonicalBar, ...],
) -> None:
    partition = store.publish(
        PublishRequest(
            key,
            bars[0].trading_day.year,
            bars[0].trading_day.month,
            bars,
            tuple(bar.bar_end for bar in bars),
        )
    )
    catalog.register_partition(partition)


def _query(kind: str, frequency: str = "1d") -> SeriesQuery:
    return SeriesQuery(
        kind,
        "jm",
        frequency,
        datetime(2025, 1, 1, 7, tzinfo=UTC),
        datetime(2025, 1, 3, 7, tzinfo=UTC),
    )


def _add_page_contract(session: Session, *, listed: date = date(2025, 1, 2)) -> None:
    session.add(Contract(
        contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
        listed_date=listed, expired_date=date(2025, 12, 1), provider="rqdata",
    ))


def test_actual_dominant_rejects_missing_intraday_endpoints_in_query_and_page(
    session, tmp_path
) -> None:
    session.scalar(select(TradingSession)).end_time = time(9, 5)
    day = date(2025, 1, 2)
    _add_page_contract(session)
    session.add(TradingCalendar(
        exchange_code="DCE", trade_date=day, is_trading_day=True,
    ))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1m")
    first = CanonicalBar(
        datetime(2025, 1, 2, 1, 1, tzinfo=UTC), day,
        Decimal(100), Decimal(101), Decimal(99), Decimal(100),
        Decimal(1), Decimal(100), Decimal(20),
    )
    last = CanonicalBar(
        datetime(2025, 1, 2, 1, 5, tzinfo=UTC), day,
        Decimal(100), Decimal(101), Decimal(99), Decimal(100),
        Decimal(1), Decimal(100), Decimal(20),
    )
    _publish(catalog, store, key, (first, last))
    catalog.upsert_main_contracts((("jm", day, "JM2509"),))
    session.commit()
    service = MarketDataService(catalog, store)

    with pytest.raises(MarketDataError, match="MAPPED_CONTRACT_DATASET_MISSING"):
        service.query(SeriesQuery(
            "actual_dominant", "jm", "1m",
            datetime(2025, 1, 2, 1, tzinfo=UTC),
            datetime(2025, 1, 2, 1, 5, tzinfo=UTC),
        ))
    with pytest.raises(MarketDataError, match="MAPPED_CONTRACT_DATASET_MISSING"):
        service.query_page(SeriesPageQuery(
            "actual_dominant", "jm", "1m", limit=5,
        ))
    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        service.query(SeriesQuery(
            "contract", "jm", "1m",
            datetime(2025, 1, 2, 1, tzinfo=UTC),
            datetime(2025, 1, 2, 1, 5, tzinfo=UTC),
            contract="JM2509",
        ))
    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        service.query_page(SeriesPageQuery(
            "contract", "jm", "1m", limit=5, contract="JM2509",
        ))


def test_physical_night_page_does_not_require_prelisting_day_session(
    session, tmp_path
) -> None:
    listing_day = date(2025, 1, 3)
    prior_day = date(2025, 1, 2)
    session.add_all((
        TradingCalendar(exchange_code="DCE", trade_date=prior_day, is_trading_day=True),
        TradingCalendar(exchange_code="DCE", trade_date=listing_day, is_trading_day=True),
        Contract(
            contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=listing_day, expired_date=date(2025, 9, 1), provider="rqdata",
        ),
    ))
    template = session.scalar(select(TradingSession))
    template.start_time = time(21)
    template.end_time = time(22)
    template.effective_from = listing_day
    template.effective_to = listing_day
    session.commit()
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    bar = CanonicalBar(
        datetime(2025, 1, 2, 14, tzinfo=UTC), listing_day,
        Decimal(100), Decimal(101), Decimal(99), Decimal(100),
        Decimal(1), Decimal(100), Decimal(20),
    )
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "60m"), (bar,))
    catalog.upsert_main_contracts((("jm", listing_day, "JM2509"),))
    session.commit()
    service = MarketDataService(catalog, store)

    result = service.query_page(SeriesPageQuery(
        "contract", "jm", "60m", limit=5, contract="JM2509",
    ))
    assert result.bars == (bar,)

    template.is_active = False
    session.commit()
    with pytest.raises(MarketDataError, match="TRADING_SESSION_MISSING"):
        service.query_page(SeriesPageQuery(
            "contract", "jm", "60m", limit=5, contract="JM2509",
        ))


def test_page_cursor_rejects_missing_bar_immediately_before_cursor(session, tmp_path) -> None:
    session.scalar(select(TradingSession)).end_time = time(9, 5)
    day = date(2025, 1, 2)
    _add_page_contract(session)
    session.add(TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    bars = tuple(CanonicalBar(
        datetime(2025, 1, 2, 1, minute, tzinfo=UTC), day,
        Decimal(100), Decimal(101), Decimal(99), Decimal(100),
        Decimal(1), Decimal(100), Decimal(20),
    ) for minute in (1, 2, 3, 5))
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1m"), bars)
    catalog.upsert_main_contracts((("jm", day, "JM2509"),))
    session.commit()
    service = MarketDataService(catalog, store)
    for kind, contract in (("contract", "JM2509"), ("actual_dominant", None)):
        with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING|MAPPED_CONTRACT_DATASET_MISSING"):
            service.query_page(SeriesPageQuery(
                kind, "jm", "1m", before=bars[-1].bar_end,
                limit=2, contract=contract,
            ))


def test_physical_page_rejects_whole_missing_first_listed_trading_day(session, tmp_path) -> None:
    session.scalar(select(TradingSession)).end_time = time(9, 1)
    _add_page_contract(session)
    session.add_all(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True,
    ) for day in (2, 3))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    bar = CanonicalBar(
        datetime(2025, 1, 3, 1, 1, tzinfo=UTC), date(2025, 1, 3),
        Decimal(100), Decimal(101), Decimal(99), Decimal(100),
        Decimal(1), Decimal(100), Decimal(20),
    )
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1m"), (bar,))
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        MarketDataService(catalog, store).query_page(SeriesPageQuery(
            "contract", "jm", "1m", limit=5, contract="JM2509",
        ))


def test_physical_as_of_page_does_not_include_future_contract_bars(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    _add_page_contract(session)
    session.add_all(tuple(
        TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day),
            is_trading_day=True,
        ) for day in (2, 3, 4)
    ))
    _publish(catalog, store, key, (_bar(2, 100), _bar(3, 101), _bar(4, 102)))
    session.commit()

    bars = MarketDataService(catalog, store).query_physical_bars_as_of(
        symbol="jm", contract="JM2509", frequency="1d",
        trading_day=date(2025, 1, 3), limit=3,
    )

    assert tuple(bar.trading_day for bar in bars) == (
        date(2025, 1, 2), date(2025, 1, 3),
    )


def test_physical_daily_as_of_does_not_require_prelisting_sessions(session, tmp_path) -> None:
    session.scalar(select(TradingSession)).effective_from = date(2025, 9, 15)
    session.add_all((
        TradingCalendar(exchange_code="DCE", trade_date=date(2025, 9, 12), is_trading_day=True),
        TradingCalendar(exchange_code="DCE", trade_date=date(2025, 9, 15), is_trading_day=True),
    ))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    _add_page_contract(session, listed=date(2025, 9, 15))
    bar = _bar(15, 100, month=9)
    _publish(catalog, store, key, (bar,))
    session.commit()

    assert MarketDataService(catalog, store).query_physical_bars_as_of(
        symbol="jm", contract="JM2509", frequency="1d",
        trading_day=date(2025, 9, 15), limit=5,
    ) == (bar,)


def test_physical_weekly_range_rejects_missing_middle_week(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1w")
    _add_page_contract(session)
    session.add_all(tuple(
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2025, 1, day),
            is_trading_day=date(2025, 1, day).weekday() < 5,
        ) for day in range(1, 18)
    ))
    _publish(catalog, store, key, (_bar(3, 100), _bar(17, 102)))
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        MarketDataService(catalog, store).query(SeriesQuery(
            "contract", "jm", "1w",
            datetime(2025, 1, 3, 7, tzinfo=UTC) - timedelta(microseconds=1),
            datetime(2025, 1, 17, 7, tzinfo=UTC),
            contract="JM2509",
        ))
    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        MarketDataService(catalog, store).query_page(SeriesPageQuery(
            "contract", "jm", "1w", limit=2, contract="JM2509",
        ))


def test_catalog_registers_minimal_month_partition(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bar = _bar(2, 1)
    store = CanonicalMonthlyStore(tmp_path)
    partition = store.publish(PublishRequest(key, 2025, 1, (bar,), (bar.bar_end,)))
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(partition)
    session.commit()

    row = catalog.all_partitions(key)[0]
    assert row.file_path == partition.parquet_path
    assert row.row_count == 1
    assert not hasattr(row, "manifest_path")


def test_month_publication_requires_exact_valid_or_source_exception_coverage(
    session, tmp_path
) -> None:
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    valid = _bar(2, 100)
    missing_at = datetime(2025, 1, 3, 7, tzinfo=UTC)
    exception = PriceUnavailableFact(
        bar_end=missing_at, trading_day=date(2025, 1, 3),
        open=Decimal(0), high=Decimal(0), low=Decimal(0),
        close=Decimal(100), volume=Decimal(2), turnover=Decimal(200),
        open_interest=Decimal(10),
        request_sha256="a" * 64, response_sha256="b" * 64,
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store = CanonicalMonthlyStore(tmp_path)
    request = PublishRequest(
        key, 2025, 1, (valid,), (valid.bar_end, missing_at),
        price_unavailable=(exception,),
    )
    published = store.publish(request)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(published)
    session.commit()
    partition = catalog.all_partitions(key)[0]
    bars, unavailable = store.read_catalog_partition_quality(partition)
    assert bars == (valid,)
    assert unavailable == (exception,)
    assert partition.row_count == 1
    assert partition.coverage_end == valid.bar_end
    with pytest.raises(MarketDataError, match="PRICE_UNAVAILABLE"):
        MarketDataService(catalog, store).query(SeriesQuery(
            "contract", "jm", "1d",
            datetime(2025, 1, 1, 7, tzinfo=UTC), missing_at,
            contract="JM2509",
        ))


def test_source_exception_cannot_cover_unknown_or_overlapping_bar(session, tmp_path):
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    valid = _bar(2, 100)
    exception = PriceUnavailableFact(
        bar_end=valid.bar_end, trading_day=valid.trading_day,
        open=Decimal(0), high=Decimal(0), low=Decimal(0),
        close=Decimal(100), volume=Decimal(2), turnover=Decimal(200),
        open_interest=Decimal(10), request_sha256="a" * 64,
        response_sha256="b" * 64,
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store = CanonicalMonthlyStore(tmp_path)
    with pytest.raises(Exception, match="SOURCE_QUALITY_COVERAGE_INVALID"):
        store.publish(PublishRequest(
            key, 2025, 1, (valid,), (valid.bar_end,),
            price_unavailable=(exception,),
        ))


def test_nonpositive_close_fact_is_typed_and_round_trips_without_becoming_no_trade():
    fact = NonpositiveCloseFact(
        bar_end=datetime(2025, 1, 3, 7, tzinfo=UTC),
        trading_day=date(2025, 1, 3),
        open=Decimal(0), high=Decimal(0), low=Decimal(0), close=Decimal(0),
        volume=Decimal(0), turnover=Decimal(0), open_interest=Decimal(0),
        request_sha256="a" * 64, response_sha256="b" * 64,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
    )

    assert source_quality_fact_from_record(fact.to_record()) == fact
    assert fact.classification == "NONPOSITIVE_CLOSE"
    assert "NO_TRADE" not in fact.to_record().values()
    with pytest.raises(ValueError, match="SOURCE_QUALITY_PRICE_INVALID"):
        NonpositiveCloseFact(
            bar_end=fact.bar_end, trading_day=fact.trading_day,
            open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1),
            volume=Decimal(0), turnover=Decimal(0), open_interest=Decimal(0),
            request_sha256="a" * 64, response_sha256="b" * 64,
            observed_at=fact.observed_at,
        )


def test_subing_d1_quality_union_is_exact_and_existing_quality_reader_rejects_new_type(
    session, tmp_path,
):
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    valid = _bar(2, 100)
    break_at = datetime(2025, 1, 3, 7, tzinfo=UTC)
    interruption = NonpositiveCloseFact(
        bar_end=break_at, trading_day=date(2025, 1, 3),
        open=Decimal(0), high=Decimal(0), low=Decimal(0), close=Decimal(0),
        volume=Decimal(0), turnover=Decimal(0), open_interest=Decimal(10),
        request_sha256="c" * 64, response_sha256="d" * 64,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, (valid,), (valid.bar_end, break_at),
        nonpositive_close=(interruption,),
    )))
    session.commit()
    market = MarketDataService(catalog, store)
    query = SeriesQuery(
        "contract", "jm", "1d",
        datetime(2025, 1, 1, 7, tzinfo=UTC), break_at,
        contract="JM2509",
    )

    with pytest.raises(MarketDataError, match="SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED"):
        market.read_physical_daily_quality(query)
    bars, facts = market.read_physical_daily_quality_union(query)
    assert bars == (valid,)
    assert facts == (interruption,)


@pytest.mark.parametrize(
    ("kind", "contract"),
    (("contract", "JM2509"), ("actual_dominant", None)),
)
def test_strict_d1_pages_reject_nonpositive_close_quality_fact(
    session, tmp_path, kind, contract,
) -> None:
    _add_page_contract(session, listed=date(2025, 1, 1))
    for day in (date(2025, 1, 2), date(2025, 1, 3)):
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=day, is_trading_day=True,
        ))
        session.add(MainContractMap(
            symbol="jm", trade_date=day, contract_code="JM2509",
            rank=1, rule="volume_open_interest",
        ))
    valid = _bar(2, 100)
    break_at = datetime(2025, 1, 3, 7, tzinfo=UTC)
    interruption = NonpositiveCloseFact(
        bar_end=break_at, trading_day=date(2025, 1, 3),
        open=Decimal(0), high=Decimal(0), low=Decimal(0), close=Decimal(0),
        volume=Decimal(0), turnover=Decimal(0), open_interest=Decimal(10),
        request_sha256="c" * 64, response_sha256="d" * 64,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        DatasetKey("contract", "jm", "JM2509", "1d"),
        2025,
        1,
        (valid,),
        (valid.bar_end, break_at),
        nonpositive_close=(interruption,),
    )))
    session.commit()

    with pytest.raises(
        MarketDataError, match="SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED",
    ):
        MarketDataService(catalog, store).query_page(SeriesPageQuery(
            kind, "jm", "1d", limit=2, contract=contract,
        ))


def test_all_price_unavailable_month_has_no_fake_price_coverage(session, tmp_path):
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    unavailable_at = datetime(2025, 1, 2, 7, tzinfo=UTC)
    exception = PriceUnavailableFact(
        bar_end=unavailable_at, trading_day=date(2025, 1, 2),
        open=Decimal(0), high=Decimal(0), low=Decimal(0),
        close=Decimal(100), volume=Decimal(2), turnover=Decimal(200),
        open_interest=Decimal(10), request_sha256="a" * 64,
        response_sha256="b" * 64, observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, (), (unavailable_at,), price_unavailable=(exception,),
    )))
    session.commit()
    partition = catalog.all_partitions(key)[0]
    assert partition.coverage_start is None
    assert partition.coverage_end is None
    assert partition.row_count == 0
    assert store.read_catalog_partition_quality(partition) == ((), (exception,))


def test_quality_read_rejects_catalog_source_window_mismatch(session, tmp_path):
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    unavailable_at = datetime(2025, 1, 2, 7, tzinfo=UTC)
    exception = PriceUnavailableFact(
        bar_end=unavailable_at, trading_day=date(2025, 1, 2),
        open=Decimal(0), high=Decimal(0), low=Decimal(0),
        close=Decimal(100), volume=Decimal(2), turnover=Decimal(200),
        open_interest=Decimal(10), request_sha256="a" * 64,
        response_sha256="b" * 64, observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, (), (unavailable_at,), price_unavailable=(exception,),
    )))
    partition = catalog.all_partitions(key)[0]
    from dataclasses import replace
    from app.market_data.storage import StorageError
    with pytest.raises(StorageError, match="SOURCE_QUALITY_COVERAGE_INVALID"):
        store.read_catalog_partition_quality(replace(
            partition, source_coverage_end=unavailable_at + timedelta(days=1),
        ))


def test_actual_dominant_d1_quality_read_proves_every_owner_day(
    session, tmp_path, monkeypatch
):
    session.scalar(select(TradingSession)).is_active = False
    session.add(Contract(
        contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 1), expired_date=date(2025, 12, 1),
        provider="rqdata",
    ))
    session.add(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, 1), is_trading_day=False,
    ))
    for day in (2, 3):
        session.add(TradingSession(
            exchange_code="DCE", instrument_symbol="jm", session_name="day",
            start_time=time(9), end_time=time(15),
            effective_from=date(2025, 1, day), effective_to=date(2025, 1, day),
            is_active=True, provider="rqdata",
        ))
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True,
        ))
        session.add(MainContractMap(
            symbol="jm", trade_date=date(2025, 1, day), contract_code="JM2509",
            rank=1, rule="volume_open_interest",
        ))
    session.commit()
    valid = _bar(2, 100)
    missing_at = datetime(2025, 1, 3, 7, tzinfo=UTC)
    exception = PriceUnavailableFact(
        missing_at, date(2025, 1, 3), Decimal(0), Decimal(0), Decimal(0),
        Decimal(100), Decimal(2), Decimal(200), Decimal(10),
        "a" * 64, "b" * 64, datetime(2026, 9, 15, tzinfo=UTC),
    )
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, (valid,), (valid.bar_end, missing_at),
        price_unavailable=(exception,),
    )))
    session.commit()
    result, unavailable = MarketDataService(catalog, store).query_actual_dominant_trading_days_quality(
        ActualDominantTradingDayQuery("jm", "1d", date(2025, 1, 2), date(2025, 1, 3))
    )
    assert result.bars == (valid,)
    assert unavailable == (("JM2509", exception),)
    assert result.resolved_contract_segments[0].contract == "JM2509"
    market = MarketDataService(catalog, store)
    original_window = market._trading_day_window

    def night_anchored_window(*, symbol, since, through):
        start, end = original_window(symbol=symbol, since=since, through=through)
        return start - timedelta(days=2), end

    # An overnight first session can precede the first daily partition's
    # synthetic coverage_start without implying a missing trading-day Bar.
    monkeypatch.setattr(market, "_trading_day_window", night_anchored_window)
    prefix_bars, prefix_gaps = market.query_contract_replay_quality(
        symbol="jm", contract="JM2509", through=date(2025, 1, 3),
        cutoff=missing_at,
    )
    assert prefix_bars == (valid,)
    assert prefix_gaps == (exception,)
    monkeypatch.setattr(
        market, "read_physical_daily_quality",
        lambda *_args, **_kwargs: ((valid,), ()),
    )
    with pytest.raises(MarketDataError, match="CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"):
        market.query_contract_replay_quality(
            symbol="jm", contract="JM2509", through=date(2025, 1, 3),
            cutoff=missing_at,
        )


def test_contract_weekly_quality_read_has_no_bar_for_proven_price_gap(session, tmp_path):
    session.scalar(select(TradingSession)).is_active = False
    session.add(Contract(
        contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 1), expired_date=date(2025, 12, 1),
        provider="rqdata",
    ))
    session.add(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, 1), is_trading_day=False,
    ))
    for day in (2, 3):
        session.add(TradingSession(
            exchange_code="DCE", instrument_symbol="jm", session_name="day",
            start_time=time(9), end_time=time(15),
            effective_from=date(2025, 1, day), effective_to=date(2025, 1, day),
            is_active=True, provider="rqdata",
        ))
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True,
        ))
        session.add(MainContractMap(
            symbol="jm", trade_date=date(2025, 1, day), contract_code="JM2509",
            rank=1, rule="volume_open_interest",
        ))
    session.commit()
    valid = _bar(2, 100)
    gap_end = datetime(2025, 1, 3, 7, tzinfo=UTC)
    exception = PriceUnavailableFact(
        gap_end, date(2025, 1, 3), Decimal(0), Decimal(0), Decimal(0),
        Decimal(100), Decimal(2), Decimal(200), Decimal(10),
        "a" * 64, "b" * 64, datetime(2026, 9, 15, tzinfo=UTC),
    )
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, (valid,), (valid.bar_end, gap_end),
        price_unavailable=(exception,),
    )))
    session.commit()
    market = MarketDataService(catalog, store)
    bars, interruptions = market.query_contract_weekly_replay_quality(
        symbol="jm", contract="JM2509", through=date(2025, 1, 3), cutoff=gap_end,
    )
    assert bars == ()
    assert len(interruptions) == 1
    assert interruptions[0].week_end == gap_end
    assert interruptions[0].unavailable_days == (date(2025, 1, 3),)
    actual, actual_gaps = market.query_actual_dominant_trading_days_quality(
        ActualDominantTradingDayQuery("jm", "1w", date(2025, 1, 2), date(2025, 1, 3)),
    )
    assert actual.bars == ()
    assert len(actual_gaps) == 1
    assert actual_gaps[0][0] == "JM2509"
    assert actual_gaps[0][1] == interruptions[0]
    incomplete, incomplete_gaps = market.query_actual_dominant_trading_days_quality(
        ActualDominantTradingDayQuery("jm", "1w", date(2025, 1, 2), date(2025, 1, 2)),
    )
    assert incomplete.bars == ()
    assert incomplete_gaps == ()
    with pytest.raises(MarketDataError):
        market.query_contract_trading_days(ContractTradingDayQuery(
            "jm", "JM2509", "1w", date(2025, 1, 2), date(2025, 1, 3),
        ))


@pytest.mark.parametrize("mismatch", [None, "close", "turnover"])
def test_contract_weekly_quality_read_validates_stored_normal_week(
    session, tmp_path, mismatch,
):
    session.scalar(select(TradingSession)).is_active = False
    session.add(Contract(
        contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 1), expired_date=date(2025, 12, 1),
        provider="rqdata",
    ))
    session.add(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, 1), is_trading_day=False,
    ))
    for day in (2, 3):
        session.add(TradingSession(
            exchange_code="DCE", instrument_symbol="jm", session_name="day",
            start_time=time(9), end_time=time(15),
            effective_from=date(2025, 1, day), effective_to=date(2025, 1, day),
            is_active=True, provider="rqdata",
        ))
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True,
        ))
    session.commit()
    first, second = _bar(2, 100), _bar(3, 101)
    weekly = CanonicalBar(
        second.bar_end, second.trading_day, first.open, second.high,
        first.low, Decimal(102 if mismatch == "close" else 101),
        Decimal(2), Decimal(21 if mismatch == "turnover" else 20), Decimal(20),
    )
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1d"),
             (first, second))
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1w"),
             (weekly,))
    session.commit()
    market = MarketDataService(catalog, store)
    if mismatch is not None:
        with pytest.raises(MarketDataError, match="WEEKLY_SOURCE_BAR_CONFLICT"):
            market.query_contract_weekly_replay_quality(
                symbol="jm", contract="JM2509", through=date(2025, 1, 3),
                cutoff=second.bar_end,
            )
    else:
        assert market.query_contract_weekly_replay_quality(
            symbol="jm", contract="JM2509", through=date(2025, 1, 3),
            cutoff=second.bar_end,
        ) == ((weekly,), ())


def test_catalog_contract_fact_normalizes_exact_identity(session, tmp_path) -> None:
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 2),
            expired_date=date(2025, 9, 25),
            provider="rqdata",
        )
    )
    session.commit()
    catalog = MarketCatalog(session, tmp_path)

    expected = ContractFact(
        symbol="jm",
        contract="JM2509",
        exchange="DCE",
        provider="rqdata",
        listed_date=date(2025, 1, 2),
        expired_date=date(2025, 9, 25),
    )
    assert catalog.contract_fact("jm", "JM2509") == expected
    assert catalog.contract_fact(" JM ", " jm2509 ") == expected


def test_catalog_contract_fact_rejects_unknown_contract(session, tmp_path) -> None:
    with pytest.raises(CatalogError, match="CONTRACT_NOT_FOUND"):
        MarketCatalog(session, tmp_path).contract_fact("jm", "JM2509")


def test_as_of_calendar_seam_maps_real_catalog_error_to_mds_contract(
    session, tmp_path
) -> None:
    """A caller never needs to classify raw CatalogError at the as-of boundary."""
    service = MarketDataService(
        MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
    )

    with pytest.raises(MarketDataError) as raised:
        service.trading_days_overlapping_window(
            symbol="cu",
            start=datetime(2025, 1, 2, tzinfo=UTC),
            end=datetime(2025, 1, 3, tzinfo=UTC),
        )

    assert raised.value.code == "INSTRUMENT_EXCHANGE_MISSING"


@pytest.mark.parametrize(
    ("symbol", "provider", "listed_date", "expired_date", "error_code"),
    [
        ("rb", "rqdata", date(2025, 1, 2), date(2025, 9, 25), "CONTRACT_SYMBOL_MISMATCH"),
        ("jm", "other", date(2025, 1, 2), date(2025, 9, 25), "CONTRACT_PROVIDER_UNSUPPORTED"),
        ("jm", "rqdata", None, date(2025, 9, 25), "CONTRACT_METADATA_MISSING"),
        ("jm", "rqdata", date(2025, 1, 2), None, "CONTRACT_METADATA_MISSING"),
        (
            "jm",
            "rqdata",
            date(2025, 9, 25),
            date(2025, 9, 25),
            "CONTRACT_ACTIVE_WINDOW_MISSING",
        ),
        (
            "jm",
            "rqdata",
            date(2025, 9, 26),
            date(2025, 9, 25),
            "CONTRACT_ACTIVE_WINDOW_MISSING",
        ),
    ],
)
def test_catalog_contract_fact_fails_closed_for_invalid_metadata(
    session,
    tmp_path,
    symbol,
    provider,
    listed_date,
    expired_date,
    error_code,
) -> None:
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=listed_date,
            expired_date=expired_date,
            provider=provider,
        )
    )
    session.commit()

    with pytest.raises(CatalogError, match=error_code):
        MarketCatalog(session, tmp_path).contract_fact(symbol, "jm2509")


def test_latest_dominants_uses_repository_display_name_instead_of_provider_code(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    session.add(Instrument(symbol="xx", name="legacy", exchange_code="DCE", is_active=False))
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 2), "JM2505"),
            ("xx", date(2025, 1, 2), "XX2505"),
        )
    )
    session.commit()

    items = MarketDataService(catalog, CanonicalMonthlyStore(tmp_path)).list_latest_dominants()

    assert len(items) == 1
    assert items[0].symbol == "jm"
    assert items[0].product_name == "焦煤"
    assert items[0].sector == "black"


def test_latest_dominant_segment_returns_current_contiguous_rank1_segment(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    for day, contract in ((2, "JM2505"), (3, "JM2505"), (6, "JM2509"), (7, "JM2509")):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
        catalog.upsert_main_contracts((("jm", date(2025, 1, day), contract),))
    session.commit()

    segment = MarketDataService(
        catalog, CanonicalMonthlyStore(tmp_path)
    ).latest_dominant_segment("jm")

    assert segment.symbol == "jm"
    assert segment.contract == "JM2509"
    assert segment.start_trading_day == date(2025, 1, 6)
    assert segment.end_trading_day == date(2025, 1, 7)


def test_latest_dominant_segment_fails_closed_for_missing_map_after_known_contract(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    for day in (3, 6, 7):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 3), "JM2505"),
            ("jm", date(2025, 1, 7), "JM2509"),
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        MarketDataService(
            catalog, CanonicalMonthlyStore(tmp_path)
        ).latest_dominant_segment("jm")


def test_actual_dominant_segments_returns_full_boundaries_for_intersecting_window(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    trading_days = {2, 3, 6, 7, 8, 9, 10}
    for day in range(1, 11):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=day in trading_days,
            )
        )
    catalog.upsert_main_contracts(
        tuple(
            (
                "jm",
                date(2025, 1, day),
                "JM2505" if day <= 7 else "JM2509",
            )
            for day in sorted(trading_days)
        )
    )
    session.commit()

    segments = MarketDataService(
        catalog, CanonicalMonthlyStore(tmp_path)
    ).actual_dominant_segments(
        "jm",
        date(2025, 1, 3),
        date(2025, 1, 8),
    )

    assert segments == (
        ResolvedContractSegment(
            "JM2505", date(2025, 1, 2), date(2025, 1, 7)
        ),
        ResolvedContractSegment(
            "JM2509", date(2025, 1, 8), date(2025, 1, 10)
        ),
    )


def test_actual_dominant_segments_fails_closed_for_missing_natural_calendar_day(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    for day in (2, 4):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=True,
            )
        )
        catalog.upsert_main_contracts(
            (("jm", date(2025, 1, day), "JM2505"),)
        )
    session.commit()

    with pytest.raises(MarketDataError, match="^TRADING_CALENDAR_MISSING$"):
        MarketDataService(
            catalog, CanonicalMonthlyStore(tmp_path)
        ).actual_dominant_segments(
            "jm",
            date(2025, 1, 2),
            date(2025, 1, 4),
        )


def test_dominant_segment_for_day_returns_historical_containing_segment(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    contracts = {
        2: "JM2505",
        3: "JM2505",
        6: "JM2509",
        7: "JM2509",
        8: "JM2509",
    }
    for day in range(2, 9):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=day in contracts,
            )
        )
    catalog.upsert_main_contracts(
        tuple(("jm", date(2025, 1, day), contract) for day, contract in contracts.items())
    )
    session.commit()

    service = MarketDataService(catalog, CanonicalMonthlyStore(tmp_path))

    historical = service.dominant_segment_for_day("jm", date(2025, 1, 3))
    latest = service.latest_dominant_segment("jm")

    assert historical.contract == "JM2505"
    assert historical.start_trading_day == date(2025, 1, 2)
    assert historical.end_trading_day == date(2025, 1, 3)
    assert latest.contract == "JM2509"


def test_dominant_segment_for_day_preserves_normalized_symbol_identity(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    session.add(
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2025, 1, 2),
            is_trading_day=True,
        )
    )
    catalog.upsert_main_contracts(
        (("jm", date(2025, 1, 2), "JM2505"),)
    )
    session.commit()

    segment = MarketDataService(
        catalog, CanonicalMonthlyStore(tmp_path)
    ).dominant_segment_for_day(" JM ", date(2025, 1, 2))

    assert segment.symbol == "jm"


def test_dominant_segment_for_day_fails_closed_for_calendar_gap(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    for day, is_trading_day in ((2, True), (3, True), (5, False), (6, True)):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=is_trading_day,
            )
        )
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 2), "JM2505"),
            ("jm", date(2025, 1, 3), "JM2505"),
            ("jm", date(2025, 1, 6), "JM2509"),
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="TRADING_CALENDAR_MISSING"):
        MarketDataService(
            catalog, CanonicalMonthlyStore(tmp_path)
        ).dominant_segment_for_day("jm", date(2025, 1, 3))


def test_dominant_segment_for_day_fails_closed_for_mapping_gap(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    for day in range(2, 7):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=day in (2, 3, 6),
            )
        )
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 2), "JM2505"),
            ("jm", date(2025, 1, 6), "JM2509"),
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        MarketDataService(
            catalog, CanonicalMonthlyStore(tmp_path)
        ).dominant_segment_for_day("jm", date(2025, 1, 2))


def test_contract_bars_for_trading_day_reads_only_real_contract_dataset(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    session.add_all(
        (
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 2), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True
            ),
        )
    )
    real_key = DatasetKey("contract", "jm", "JM2505", "1m")
    continuous_key = DatasetKey("continuous", "jm", "MAIN", "1m")
    _publish(catalog, store, real_key, (_bar(2, 200), _bar(3, 201)))
    _publish(catalog, store, continuous_key, (_bar(2, 900),))
    session.commit()

    bars = MarketDataService(catalog, store).contract_bars_for_trading_day(
        symbol="jm",
        contract="JM2505",
        frequency="1m",
        trading_day=date(2025, 1, 2),
    )

    assert tuple(bar.close for bar in bars) == (Decimal("200"),)

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        MarketDataService(catalog, store).contract_bars_for_trading_day(
            symbol="jm",
            contract="JM2509",
            frequency="1m",
            trading_day=date(2025, 1, 2),
        )


def test_contract_bars_for_trading_day_uses_canonical_trading_day_for_night_bar(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    session.add_all(
        (
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 4), is_trading_day=False
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 5), is_trading_day=False
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True
            ),
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="night",
                start_time=time(21),
                end_time=time(23),
                effective_from=date(2025, 1, 6),
                effective_to=date(2025, 1, 6),
                is_active=True,
            ),
        )
    )
    night_bar = CanonicalBar(
        datetime(2025, 1, 3, 13, 2, tzinfo=UTC),
        date(2025, 1, 6),
        Decimal("200"),
        Decimal("201"),
        Decimal("199"),
        Decimal("200"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    key = DatasetKey("contract", "jm", "JM2509", "1m")
    _publish(catalog, store, key, (night_bar,))
    session.commit()

    bars = MarketDataService(catalog, store).contract_bars_for_trading_day(
        symbol="jm",
        contract="JM2509",
        frequency="1m",
        trading_day=date(2025, 1, 6),
    )

    assert bars == (night_bar,)


def test_contract_bars_for_trading_day_returns_empty_only_for_formal_nontrading_day(
    session, tmp_path
) -> None:
    session.add(
        TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, 4), is_trading_day=False
        )
    )
    session.commit()

    bars = MarketDataService(
        MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
    ).contract_bars_for_trading_day(
        symbol="jm",
        contract="JM2505",
        frequency="1m",
        trading_day=date(2025, 1, 4),
    )

    assert bars == ()


def test_continuous_and_contract_query_use_catalogued_physical_partitions(
    session, tmp_path
) -> None:
    session.add_all(tuple(
        TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day),
            is_trading_day=True,
        ) for day in (2, 3)
    ))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    continuous = DatasetKey("continuous", "jm", "MAIN", "1d")
    contract = DatasetKey("contract", "jm", "JM2505", "1d")
    _publish(catalog, store, continuous, (_bar(2, 100), _bar(3, 101)))
    _publish(catalog, store, contract, (_bar(2, 200), _bar(3, 201)))
    session.commit()

    service = MarketDataService(catalog, store)
    assert [bar.close for bar in service.query(_query("continuous")).bars] == [
        Decimal("100"),
        Decimal("101"),
    ]
    result = service.query(
        SeriesQuery(
            "contract",
            "jm",
            "1d",
            datetime(2025, 1, 1, 7, tzinfo=UTC),
            datetime(2025, 1, 3, 7, tzinfo=UTC),
            "JM2505",
        )
    )
    assert [bar.close for bar in result.bars] == [Decimal("200"), Decimal("201")]
    assert result.requested_trading_day_window is None


def test_query_reads_across_monthly_physical_partitions(session, tmp_path) -> None:
    session.add_all((
        TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, 31),
            is_trading_day=True,
        ),
        TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 2, 1),
            is_trading_day=True,
        ),
    ))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(31, 100),))
    _publish(catalog, store, key, (_bar(1, 101, month=2),))
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "continuous",
            "jm",
            "1d",
            datetime(2025, 1, 30, 7, tzinfo=UTC),
            datetime(2025, 2, 1, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("100"), Decimal("101")]


def test_query_fails_closed_for_an_internal_missing_month(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(31, 100),))
    _publish(catalog, store, key, (_bar(1, 101, month=3),))
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        MarketDataService(catalog, store).query(
            SeriesQuery(
                "continuous",
                "jm",
                "1d",
                datetime(2025, 1, 30, 7, tzinfo=UTC),
                datetime(2025, 3, 1, 7, tzinfo=UTC),
            )
        )


def test_derived_query_reads_derived_partition_without_1m_fallback(
    session, tmp_path
) -> None:
    session.add(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, 2),
        is_trading_day=True,
    ))
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "15m")
    _publish(catalog, store, key, (_bar(2, 100),))
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "continuous",
            "jm",
            "15m",
            datetime(2025, 1, 2, 6, 45, tzinfo=UTC),
            datetime(2025, 1, 2, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("100")]


def test_actual_dominant_switches_contracts_and_uses_week_last_owner(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    first = DatasetKey("contract", "jm", "JM2505", "1d")
    second = DatasetKey("contract", "jm", "JM2509", "1d")
    _publish(catalog, store, first, (_bar(2, 100), _bar(3, 101)))
    _publish(catalog, store, second, (_bar(6, 200), _bar(7, 201)))
    for day, contract in ((2, "JM2505"), (3, "JM2505"), (6, "JM2509"), (7, "JM2509")):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
        catalog.upsert_main_contracts((("jm", date(2025, 1, day), contract),))
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "actual_dominant",
            "jm",
            "1d",
            datetime(2025, 1, 1, 7, tzinfo=UTC),
            datetime(2025, 1, 7, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [
        Decimal("100"),
        Decimal("101"),
        Decimal("200"),
        Decimal("201"),
    ]
    assert [segment.contract for segment in result.resolved_contract_segments] == [
        "JM2505",
        "JM2509",
    ]


def test_actual_dominant_fails_closed_when_rank1_map_is_incomplete(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2505", "1d")
    _publish(catalog, store, key, (_bar(2, 100), _bar(3, 101)))
    for day in (2, 3):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
    catalog.upsert_main_contracts((("jm", date(2025, 1, 2), "JM2505"),))
    session.commit()

    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        MarketDataService(catalog, store).query(_query("actual_dominant"))


def test_actual_dominant_fails_closed_when_a_mapped_day_has_no_bar(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2505", "1d")
    _publish(catalog, store, key, (_bar(2, 100),))
    for day in (2, 3):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
        catalog.upsert_main_contracts((("jm", date(2025, 1, day), "JM2505"),))
    session.commit()

    with pytest.raises(MarketDataError, match="MAPPED_CONTRACT_DATASET_MISSING"):
        MarketDataService(catalog, store).query(_query("actual_dominant"))


def test_actual_dominant_uses_the_next_trading_day_for_a_night_session(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    contract = DatasetKey("contract", "jm", "JM2509", "1m")
    _publish(
        catalog,
        store,
        contract,
        (
            CanonicalBar(
                datetime(2025, 1, 3, 13, 2, tzinfo=UTC),
                date(2025, 1, 6),
                Decimal("200"),
                Decimal("201"),
                Decimal("199"),
                Decimal("200"),
                Decimal(1),
                Decimal(10),
                Decimal(20),
            ),
        ),
    )
    session.add_all(
        (
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True
            ),
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="night",
                start_time=time(21),
                end_time=time(23),
                effective_from=date(2025, 1, 6),
                effective_to=date(2025, 1, 6),
                is_active=True,
            ),
        )
    )
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 3), "JM2505"),
            ("jm", date(2025, 1, 6), "JM2509"),
        )
    )
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "actual_dominant",
            "jm",
            "1m",
            datetime(2025, 1, 3, 13, 1, tzinfo=UTC),
            datetime(2025, 1, 3, 13, 2, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("200")]
    assert [segment.contract for segment in result.resolved_contract_segments] == [
        "JM2509"
    ]


def test_actual_dominant_after_day_close_does_not_require_future_session_facts(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    contract = DatasetKey("contract", "jm", "JM2505", "1d")
    _publish(catalog, store, contract, (_bar(3, 100),))
    session.add_all(
        (
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True
            ),
        )
    )
    session.scalar(select(TradingSession)).effective_to = date(2025, 1, 3)
    catalog.upsert_main_contracts((("jm", date(2025, 1, 3), "JM2505"),))
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "actual_dominant",
            "jm",
            "1d",
            datetime(2025, 1, 3, 0, tzinfo=UTC),
            datetime(2025, 1, 3, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("100")]


def test_actual_dominant_trading_day_query_normalizes_and_rejects_invalid_window() -> None:
    query = ActualDominantTradingDayQuery(
        " JM ",
        "1m",
        date(2025, 1, 6),
        date(2025, 1, 6),
    )

    assert query.symbol == "jm"
    with pytest.raises(ValueError):
        ActualDominantTradingDayQuery(
            "jm",
            "1m",
            date(2025, 1, 7),
            date(2025, 1, 6),
        )


def test_contract_trading_day_query_normalizes_identity_and_rejects_invalid_window() -> (
    None
):
    query = ContractTradingDayQuery(
        " JM ",
        " jm2509 ",
        "1m",
        date(2025, 1, 6),
        date(2025, 1, 6),
    )

    assert query.symbol == "jm"
    assert query.contract == "JM2509"
    with pytest.raises(ValueError):
        ContractTradingDayQuery(
            "jm",
            "AG2502",
            "1m",
            date(2025, 1, 6),
            date(2025, 1, 6),
        )
    with pytest.raises(ValueError):
        ContractTradingDayQuery(
            "jm",
            "JM2509",
            "1m",
            date(2025, 1, 7),
            date(2025, 1, 6),
        )


def test_contract_trading_day_query_uses_weekend_night_and_last_session_bounds(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    contract = DatasetKey("contract", "jm", "JM2509", "60m")
    friday_night = CanonicalBar(
        datetime(2025, 1, 3, 14, tzinfo=UTC),
        date(2025, 1, 6),
        Decimal("100"),
        Decimal("101"),
        Decimal("99"),
        Decimal("100"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    monday_close = CanonicalBar(
        datetime(2025, 1, 6, 7, tzinfo=UTC),
        date(2025, 1, 6),
        Decimal("101"),
        Decimal("102"),
        Decimal("100"),
        Decimal("101"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    tuesday = CanonicalBar(
        datetime(2025, 1, 7, 7, tzinfo=UTC),
        date(2025, 1, 7),
        Decimal("102"),
        Decimal("103"),
        Decimal("101"),
        Decimal("102"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    from dataclasses import replace
    night_bars = (
        friday_night,
        replace(friday_night, bar_end=datetime(2025, 1, 3, 15, tzinfo=UTC)),
    )
    day_bars = tuple(replace(
        monday_close, bar_end=datetime(2025, 1, 6, hour, tzinfo=UTC)
    ) for hour in range(2, 8))
    _publish(catalog, store, contract, (*night_bars, *day_bars, tuesday))
    session.add_all(
        (
            Contract(
                contract_code="JM2509",
                instrument_symbol="jm",
                exchange_code="DCE",
                listed_date=date(2025, 1, 4),
                expired_date=date(2025, 9, 25),
                status="active",
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 4), is_trading_day=False
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 5), is_trading_day=False
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 7), is_trading_day=True
            ),
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="night",
                start_time=time(21),
                end_time=time(23),
                effective_from=date(2025, 1, 6),
                is_active=True,
            ),
        )
    )
    session.commit()

    result = MarketDataService(catalog, store).query_contract_trading_days(
        ContractTradingDayQuery(
            "jm",
            "JM2509",
            "60m",
            date(2025, 1, 4),
            date(2025, 1, 6),
        )
    )

    assert result.bars == (*night_bars, *day_bars)
    assert result.request_identity["start"] == "2025-01-03T13:00:00+00:00"
    assert result.request_identity["end"] == "2025-01-06T07:00:00+00:00"


@pytest.mark.parametrize(
    "present_days",
    ((7, 8), (6, 8)),
    ids=("leading-row-absent", "intermediate-row-absent"),
)
def test_contract_trading_day_query_fails_closed_for_missing_calendar_row(
    session,
    tmp_path,
    present_days,
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 6),
            expired_date=date(2025, 1, 9),
            status="active",
        )
    )
    for day in present_days:
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=True,
            )
        )
    session.commit()

    with pytest.raises(MarketDataError, match="^TRADING_CALENDAR_MISSING$"):
        MarketDataService(catalog, store).query_contract_trading_days(
            ContractTradingDayQuery(
                "jm",
                "JM2509",
                "1d",
                date(2025, 1, 6),
                date(2025, 1, 8),
            )
        )


def test_contract_trading_day_query_requires_expiry_metadata(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 6),
            expired_date=None,
            status="active",
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="^CONTRACT_METADATA_MISSING$"):
        MarketDataService(catalog, store).query_contract_trading_days(
            ContractTradingDayQuery(
                "jm",
                "JM2509",
                "1d",
                date(2025, 1, 6),
                date(2025, 1, 6),
            )
        )


def test_contract_trading_day_query_preserves_missing_contract_error(
    session, tmp_path
) -> None:
    with pytest.raises(MarketDataError, match="^CONTRACT_METADATA_MISSING$"):
        MarketDataService(
            MarketCatalog(session, tmp_path),
            CanonicalMonthlyStore(tmp_path),
        ).query_contract_trading_days(
            ContractTradingDayQuery(
                "jm",
                "JM2509",
                "1d",
                date(2025, 1, 6),
                date(2025, 1, 6),
            )
        )


def test_contract_trading_day_query_rejects_retired_product(
    session, tmp_path
) -> None:
    with pytest.raises(MarketDataError, match="^PRODUCT_RETIRED$"):
        MarketDataService(
            MarketCatalog(session, tmp_path),
            CanonicalMonthlyStore(tmp_path),
        ).query_contract_trading_days(
            ContractTradingDayQuery(
                "br", "BR2509", "1d", date(2025, 1, 6), date(2025, 1, 6),
            )
        )


def test_contract_trading_day_query_rejects_non_rqdata_contract(
    session, tmp_path
) -> None:
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 6),
            expired_date=date(2025, 9, 25),
            provider="other",
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="^CONTRACT_PROVIDER_UNSUPPORTED$"):
        MarketDataService(
            MarketCatalog(session, tmp_path),
            CanonicalMonthlyStore(tmp_path),
        ).query_contract_trading_days(
            ContractTradingDayQuery(
                "jm",
                "JM2509",
                "1d",
                date(2025, 1, 6),
                date(2025, 1, 6),
            )
        )


def test_contract_trading_day_query_clamps_to_exclusive_expiry_ceiling(
    session,
    tmp_path,
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    active_bars = (_bar(6, 206), _bar(7, 207))
    expired_bar = _bar(8, 208)
    _publish(catalog, store, key, (*active_bars, expired_bar))
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 6),
            expired_date=date(2025, 1, 8),
            status="active",
        )
    )
    for day in (6, 7):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=True,
            )
        )
    session.commit()

    result = MarketDataService(catalog, store).query_contract_trading_days(
        ContractTradingDayQuery(
            "jm",
            "JM2509",
            "1d",
            date(2025, 1, 6),
            date(2025, 1, 9),
        )
    )

    assert result.bars == active_bars
    assert result.request_identity["end"] == "2025-01-07T07:00:00+00:00"
    assert result.requested_trading_day_window == (
        date(2025, 1, 6),
        date(2025, 1, 7),
    )


def test_contract_trading_day_query_rejects_window_after_expiry(
    session,
    tmp_path,
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 6),
            expired_date=date(2025, 1, 8),
            status="active",
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="^CONTRACT_ACTIVE_WINDOW_MISSING$"):
        MarketDataService(catalog, store).query_contract_trading_days(
            ContractTradingDayQuery(
                "jm",
                "JM2509",
                "1d",
                date(2025, 1, 8),
                date(2025, 1, 9),
            )
        )


def test_contract_trading_day_query_clamps_to_contract_active_floor(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    first_available = _bar(6, 209)
    _publish(catalog, store, key, (first_available,))
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 6),
            expired_date=date(2025, 9, 25),
            status="active",
        )
    )
    for day in (2, 3, 6):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
    session.commit()

    result = MarketDataService(catalog, store).query_contract_trading_days(
        ContractTradingDayQuery(
            "jm",
            "JM2509",
            "1d",
            date(2025, 1, 2),
            date(2025, 1, 6),
        )
    )

    assert result.bars == (first_available,)
    assert result.request_identity["start"] == "2025-01-06T01:00:00+00:00"
    assert result.request_identity["end"] == "2025-01-06T07:00:00+00:00"


def test_contract_trading_day_query_accepts_complete_monday_listing_after_weekend(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    first_bar = _bar(6, 209)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1d"), (first_bar,))
    session.add_all((
        Contract(
            contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=date(2025, 1, 6), expired_date=date(2025, 9, 25),
            status="active",
        ),
        TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True),
        TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True),
        TradingSession(
            exchange_code="DCE", instrument_symbol="jm", session_name="night",
            start_time=time(21), end_time=time(23),
            effective_from=date(2025, 1, 6), is_active=True,
        ),
    ))
    session.commit()

    result = MarketDataService(catalog, store).query_contract_trading_days(
        ContractTradingDayQuery("jm", "JM2509", "1d", date(2025, 1, 6), date(2025, 1, 6))
    )

    assert result.bars == (first_bar,)
    assert result.request_identity["start"] == "2025-01-03T13:00:00+00:00"


def test_contract_trading_day_query_fails_closed_for_incomplete_first_session(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "60m")
    late_first_bar = CanonicalBar(
        datetime(2025, 1, 6, 3, tzinfo=UTC),
        date(2025, 1, 6),
        Decimal("100"),
        Decimal("101"),
        Decimal("99"),
        Decimal("100"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    _publish(catalog, store, key, (late_first_bar, _bar(6, 101)))
    session.add_all(
        (
            Contract(
                contract_code="JM2509",
                instrument_symbol="jm",
                exchange_code="DCE",
                listed_date=date(2025, 1, 6),
                expired_date=date(2025, 9, 25),
                status="active",
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True
            ),
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        MarketDataService(catalog, store).query_contract_trading_days(
            ContractTradingDayQuery(
                "jm",
                "JM2509",
                "60m",
                date(2025, 1, 6),
                date(2025, 1, 6),
            )
        )


def test_trading_day_query_includes_weekend_night_and_excludes_future_day(
    session, tmp_path
) -> None:
    session.scalar(select(TradingSession)).end_time = time(9, 5)
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    contract = DatasetKey("contract", "jm", "JM2509", "1m")
    friday_night = CanonicalBar(
        datetime(2025, 1, 3, 13, 5, tzinfo=UTC),
        date(2025, 1, 6),
        Decimal("100"),
        Decimal("101"),
        Decimal("99"),
        Decimal("100"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    monday_day = CanonicalBar(
        datetime(2025, 1, 6, 1, 5, tzinfo=UTC),
        date(2025, 1, 6),
        Decimal("101"),
        Decimal("102"),
        Decimal("100"),
        Decimal("101"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    from dataclasses import replace
    night_bars = tuple(replace(
        friday_night,
        bar_end=datetime(2025, 1, 3, 13, minute, tzinfo=UTC),
    ) for minute in range(1, 6))
    day_bars = tuple(replace(
        monday_day,
        bar_end=datetime(2025, 1, 6, 1, minute, tzinfo=UTC),
    ) for minute in range(1, 6))
    _publish(catalog, store, contract, (*night_bars, *day_bars))
    session.add_all(
        (
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True
            ),
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, 7), is_trading_day=True
            ),
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="night",
                start_time=time(21),
                end_time=time(21, 5),
                effective_from=date(2025, 1, 6),
                is_active=True,
            ),
        )
    )
    catalog.upsert_main_contracts(
        (("jm", date(2025, 1, 6), "JM2509"),)
    )
    session.commit()

    result = MarketDataService(catalog, store).query_actual_dominant_trading_days(
        ActualDominantTradingDayQuery(
            "jm",
            "1m",
            date(2025, 1, 6),
            date(2025, 1, 6),
        )
    )

    assert result.bars == (*night_bars, *day_bars)
    assert result.request_identity["start"] == "2025-01-03T13:00:00+00:00"
    assert result.request_identity["end"] == "2025-01-06T01:05:00+00:00"
    assert result.requested_trading_day_window == (
        date(2025, 1, 6),
        date(2025, 1, 6),
    )


def test_actual_dominant_week_uses_last_trading_day_owner(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    first = DatasetKey("contract", "jm", "JM2505", "1w")
    second = DatasetKey("contract", "jm", "JM2509", "1w")
    _publish(catalog, store, first, (_bar(10, 105),))
    _publish(catalog, store, second, (_bar(10, 209),))
    for day in (6, 7, 8, 9, 10):
        session.add(
            TradingCalendar(
                exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
            )
        )
        catalog.upsert_main_contracts(
            (("jm", date(2025, 1, day), "JM2505" if day < 8 else "JM2509"),)
        )
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "actual_dominant",
            "jm",
            "1w",
            datetime(2025, 1, 5, tzinfo=UTC),
            datetime(2025, 1, 10, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("209")]
    assert result.resolved_contract_segments[0].contract == "JM2509"


def test_actual_dominant_week_does_not_require_previous_friday_owner_for_night_start(
    session, tmp_path
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    contract = DatasetKey("contract", "jm", "JM2509", "1w")
    weekly_bar = CanonicalBar(
        datetime(2024, 8, 2, 7, tzinfo=UTC),
        date(2024, 8, 2),
        Decimal("209"),
        Decimal("210"),
        Decimal("208"),
        Decimal("209"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    _publish(catalog, store, contract, (weekly_bar,))
    session.execute(update(TradingSession).values(effective_from=date(2024, 7, 26)))
    session.add_all(
        TradingCalendar(
            exchange_code="DCE", trade_date=day, is_trading_day=True
        )
        for day in (
            date(2024, 7, 26),
            date(2024, 7, 29),
            date(2024, 7, 30),
            date(2024, 7, 31),
            date(2024, 8, 1),
            date(2024, 8, 2),
        )
    )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="night",
            start_time=time(21),
            end_time=time(23),
            effective_from=date(2024, 7, 29),
            is_active=True,
        )
    )
    catalog.upsert_main_contracts(
        tuple(
            ("jm", day, "JM2509")
            for day in (
                date(2024, 7, 29),
                date(2024, 7, 30),
                date(2024, 7, 31),
                date(2024, 8, 1),
                date(2024, 8, 2),
            )
        )
    )
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "actual_dominant",
            "jm",
            "1w",
            datetime(2024, 7, 26, 13, tzinfo=UTC),
            datetime(2024, 8, 2, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("209")]
    assert result.resolved_contract_segments == (
        ResolvedContractSegment(
            contract="JM2509",
            start_trading_day=date(2024, 8, 2),
            end_trading_day=date(2024, 8, 2),
        ),
    )


@pytest.mark.parametrize(
    ("request_end", "last_trading_day"),
    (
        (datetime(2024, 8, 1, 13, 1, tzinfo=UTC), date(2024, 8, 2)),
        (datetime(2024, 8, 2, 3, tzinfo=UTC), date(2024, 8, 2)),
        (datetime(2024, 8, 1, 3, tzinfo=UTC), date(2024, 8, 1)),
    ),
    ids=("thursday-night", "friday-intraday", "holiday-short-week-intraday"),
)
def test_actual_dominant_week_omits_incomplete_tail_week(
    session, tmp_path, request_end, last_trading_day
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    contract = DatasetKey("contract", "jm", "JM2509", "1w")
    completed_bar = CanonicalBar(
        datetime(2024, 7, 26, 7, tzinfo=UTC),
        date(2024, 7, 26),
        Decimal("109"),
        Decimal("110"),
        Decimal("108"),
        Decimal("109"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    tail_bar = CanonicalBar(
        datetime.combine(last_trading_day, time(7), UTC),
        last_trading_day,
        Decimal("209"),
        Decimal("210"),
        Decimal("208"),
        Decimal("209"),
        Decimal(1),
        Decimal(10),
        Decimal(20),
    )
    _publish(catalog, store, contract, (completed_bar,))
    _publish(catalog, store, contract, (tail_bar,))
    session.execute(update(TradingSession).values(effective_from=date(2024, 7, 22)))
    trading_days = tuple(
        day
        for day in (
            date(2024, 7, 22),
            date(2024, 7, 23),
            date(2024, 7, 24),
            date(2024, 7, 25),
            date(2024, 7, 26),
            date(2024, 7, 29),
            date(2024, 7, 30),
            date(2024, 7, 31),
            date(2024, 8, 1),
            date(2024, 8, 2),
        )
        if day <= last_trading_day
    )
    session.add_all(
        TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True)
        for day in trading_days
    )
    session.add(
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2024, 7, 19),
            is_trading_day=True,
        )
    )
    if last_trading_day == date(2024, 8, 1):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2024, 8, 2),
                is_trading_day=False,
            )
        )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="night",
            start_time=time(21),
            end_time=time(23),
            effective_from=date(2024, 7, 22),
            is_active=True,
        )
    )
    catalog.upsert_main_contracts(
        tuple(("jm", day, "JM2509") for day in trading_days)
    )
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            "actual_dominant",
            "jm",
            "1w",
            datetime(2024, 7, 21, tzinfo=UTC),
            request_end,
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("109")]
    assert result.resolved_contract_segments == (
        ResolvedContractSegment(
            contract="JM2509",
            start_trading_day=date(2024, 7, 26),
            end_trading_day=date(2024, 7, 26),
        ),
    )


@pytest.mark.parametrize(
    "failure",
    ("missing_partition", "unreadable", "row_count", "file_path", "coverage"),
)
def test_query_fails_closed_for_missing_or_invalid_physical_partition(
    session, tmp_path, failure
) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    if failure == "missing_partition":
        with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
            MarketDataService(catalog, store).query(_query("continuous"))
        return
    _publish(catalog, store, key, (_bar(2, 100),))
    session.commit()
    if failure == "unreadable":
        catalog.all_partitions(key)[0].file_path.unlink()
    elif failure == "row_count":
        session.execute(update(MarketPartition).values(row_count=2))
        session.commit()
    elif failure == "file_path":
        alternate = tmp_path / "alternate.parquet"
        alternate.write_bytes(catalog.all_partitions(key)[0].file_path.read_bytes())
        session.execute(update(MarketPartition).values(file_uri="alternate.parquet"))
        session.commit()
    else:
        session.execute(
            update(MarketPartition).values(
                coverage_end=_bar(2, 100).bar_end + timedelta(days=1)
            )
        )
        session.commit()
    with pytest.raises(MarketDataError, match="PARTITION_INTEGRITY_INVALID"):
        MarketDataService(catalog, store).query(
            SeriesQuery(
                "continuous",
                "jm",
                "1d",
                datetime(2025, 1, 1, 7, tzinfo=UTC),
                datetime(2025, 1, 2, 7, tzinfo=UTC),
            )
        )


def test_query_hot_path_has_no_digest_manifest_or_gap_dependency() -> None:
    source = "\n".join(inspect.getsource(method) for method in (
        MarketDataService.query,
        MarketDataService.query_page,
        MarketDataService._read_physical,
        MarketDataService._actual_dominant,
        MarketDataService._actual_dominant_page,
    ))
    assert "sha256" not in source.lower()
    assert "manifest" not in source.lower()
    assert "data_gap" not in source.lower()


@pytest.mark.parametrize("limit", [1, 500])
@pytest.mark.parametrize("frequency", ["1d", "60m", "1w"])
def test_newow_chart_window_uses_bounded_catalog_queries(session, tmp_path, limit, frequency):
    from sqlalchemy import event
    from guiyi_quant.newow.product_contracts import ProductFrequency
    from app.market_data.newow.product_reader import NewowProductReader

    start = date(2023, 1, 2)
    days = tuple(
        start + timedelta(days=i)
        for i in range(1344)
        if (start + timedelta(days=i)).weekday() < 5
    )
    session.execute(update(TradingSession).values(effective_from=start))
    session.add_all(
        TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True)
        for day in days
    )
    session.commit()

    class Coverage:
        def product_start(self, symbol):
            return start

        def latest_complete_day(self, products):
            return days[-1]

    as_of = datetime.combine(days[-1], time(7), UTC)
    mds = MarketDataService(
        MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
    )
    reader = NewowProductReader(
        mds, coverage=Coverage(), active_products=("jm",), now=lambda: as_of
    )
    selects = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        window = reader.resolve_chart_window("jm", ProductFrequency(frequency), limit, as_of)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    count_days = (limit + 3) // 4 if frequency == "60m" else limit
    if frequency == "1w":
        count_days *= 7
    assert (window.since, window.through) == (days[max(0, len(days) - count_days)], days[-1])
    print(f"{frequency=} {limit=} SELECTs={len(selects)}")
    assert len(selects) <= 8, f"960 trading days issued {len(selects)} SELECTs"


def test_completed_days_preserve_night_weekend_and_exact_close(session, tmp_path):
    friday, monday = date(2025, 1, 3), date(2025, 1, 6)
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=trading)
            for day, trading in [
                (date(2025, 1, 2), True),
                (friday, True),
                (date(2025, 1, 4), False),
                (monday, True),
            ]
        ]
    )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="night",
            start_time=time(21),
            end_time=time(2),
            crosses_midnight=True,
            effective_from=date(2025, 1, 1),
            is_active=True,
        )
    )
    session.commit()
    mds = MarketDataService(
        MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
    )
    start = datetime(2025, 1, 3, 0, tzinfo=UTC)
    friday_night = datetime(2025, 1, 3, 14, tzinfo=UTC)
    assert mds.trading_days_overlapping_window(
        symbol="jm", start=start, end=friday_night
    ) == (friday, monday)
    for cutoff, expected in [
        (friday_night, (friday,)),
        (datetime(2025, 1, 4, 4, tzinfo=UTC), (friday,)),
        (datetime(2025, 1, 6, 6, 59, tzinfo=UTC), (friday,)),
        (datetime(2025, 1, 6, 7, tzinfo=UTC), (friday, monday)),
    ]:
        assert (
            mds.completed_trading_days(
                symbol="jm", start=start, as_of=cutoff, latest=monday
            )
            == expected
        )


@pytest.mark.parametrize("fault", ["missing", "prior_missing", "expired"])
def test_completed_days_fail_closed_on_session_facts(session, tmp_path, fault):
    day = date(2025, 1, 3)
    session.add(
        TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True)
    )
    if fault == "missing":
        session.execute(update(TradingSession).values(is_active=False))
    elif fault == "expired":
        session.execute(update(TradingSession).values(effective_to=date(2025, 1, 2)))
    else:
        session.execute(
            update(TradingSession).values(start_time=time(21), end_time=time(23))
        )
    session.commit()
    mds = MarketDataService(
        MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path)
    )
    code = (
        "PREVIOUS_TRADING_DAY_MISSING"
        if fault == "prior_missing"
        else "TRADING_SESSION_MISSING"
    )
    with pytest.raises(MarketDataError, match=code):
        mds.completed_trading_days(
            symbol="jm",
            start=datetime(2025, 1, 3, tzinfo=UTC),
            as_of=datetime(2025, 1, 3, 8, tzinfo=UTC),
            latest=day,
        )


def test_session_batch_matches_authoritative_single_day_across_template_change(session):
    from app.market_data.session_clock import SessionWindowBatch, session_windows_for_trading_day

    days = (date(2025, 1, 3), date(2025, 1, 6))
    session.add_all(TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True)
                    for day in (date(2025, 1, 2), *days))
    session.execute(update(TradingSession).values(effective_to=days[0]))
    session.add(TradingSession(exchange_code="DCE", instrument_symbol="jm",
        session_name="short_day", start_time=time(9), end_time=time(11),
        effective_from=days[1], is_active=True))
    session.commit()
    batch = SessionWindowBatch(session, exchange="DCE", symbol="jm", trading_days=days)
    for day in days:
        assert batch.windows(day) == session_windows_for_trading_day(
            session, exchange="DCE", symbol="jm", trading_day=day)
    assert batch.windows(days[0])[-1].end == datetime(2025, 1, 3, 7, tzinfo=UTC)
    assert batch.windows(days[1])[-1].end == datetime(2025, 1, 6, 3, tzinfo=UTC)


def test_strict_completed_days_does_not_load_future_mapped_session(session, tmp_path):
    from app.models import MainContractMap
    day = date(2025, 1, 3)
    future = date(2025, 1, 6)
    session.add_all([
        TradingCalendar(exchange_code='DCE', trade_date=day, is_trading_day=True),
        TradingCalendar(exchange_code='DCE', trade_date=future, is_trading_day=True),
        MainContractMap(symbol='jm',trade_date=future,rank=1,contract_code='JM2505'),
    ])
    session.execute(update(TradingSession).values(effective_to=day))
    session.commit()
    mds=MarketDataService(MarketCatalog(session,tmp_path),CanonicalMonthlyStore(tmp_path))
    assert mds.completed_trading_days(symbol='jm',start=datetime(2025,1,3,tzinfo=UTC),as_of=datetime(2025,1,3,7,tzinfo=UTC),latest=day,calendar_since=day)==(day,)


def _listing_market(session, tmp_path, symbol, *, night=False):
    listing = date(2025, 11, 27)
    session.add_all([
        Exchange(code="GFEX", name="GFEX"),
        Instrument(symbol=symbol, name=symbol.upper(), exchange_code="GFEX"),
        *[TradingCalendar(exchange_code="GFEX", trade_date=date(2025, 11, day),
                          is_trading_day=True) for day in (26, 27, 28)],
        TradingSession(exchange_code="GFEX", instrument_symbol=symbol,
                       session_name="day", start_time=time(9), end_time=time(15),
                       effective_from=listing, is_active=True),
    ])
    if night:
        session.add(TradingSession(
            exchange_code="GFEX", instrument_symbol=symbol, session_name="night",
            start_time=time(21), end_time=time(23), effective_from=listing, is_active=True,
        ))
    session.commit()
    return MarketDataService(MarketCatalog(session, tmp_path), CanonicalMonthlyStore(tmp_path))


@pytest.mark.parametrize("symbol", ["pd", "pt"])
def test_reference_listing_lower_bound_does_not_require_prelisting_session(session, tmp_path, symbol):
    from types import SimpleNamespace
    from app.market_data.subing_reference import SubingReferenceQuery, SubingReferenceService

    market = _listing_market(session, tmp_path, symbol)
    service = SubingReferenceService(
        market, coverage=SimpleNamespace(product_start=lambda _: date(2025, 11, 27)),
        active_products=(symbol,),
    )
    assert service._window(
        SubingReferenceQuery(symbol), datetime(2025, 11, 28, 2, tzinfo=UTC)
    ) == (date(2025, 11, 27), date(2025, 11, 27), datetime(2025, 11, 27, 7, tzinfo=UTC))


def test_session_lower_bound_keeps_first_trading_days_prior_natural_night(session, tmp_path):
    market = _listing_market(session, tmp_path, "pd", night=True)
    listing = date(2025, 11, 27)
    windows = market.catalog.session_windows_overlapping_window(
        "pd", datetime(2025, 11, 26, 13, 30, tzinfo=UTC),
        datetime(2025, 11, 26, 14, tzinfo=UTC), earliest=listing, latest=listing,
    )
    assert len(windows) == 1 and windows[0][0] == listing
    assert windows[0][1][0].start == datetime(2025, 11, 26, 13, tzinfo=UTC)
    assert market.completed_trading_days(
        symbol="pd", start=datetime(2025, 11, 26, 13, 30, tzinfo=UTC),
        as_of=datetime(2025, 11, 26, 14, tzinfo=UTC), latest=listing, calendar_since=listing,
    ) == ()  # The first trading day has not closed yet.


@pytest.mark.parametrize("fault,code", [
    ("session", "TRADING_SESSION_MISSING"),
    ("calendar", "TRADING_CALENDAR_MISSING"),
    ("night_anchor", "PREVIOUS_TRADING_DAY_MISSING"),
])
def test_listing_lower_bound_still_rejects_required_missing_facts(session, tmp_path, fault, code):
    from sqlalchemy import delete

    market = _listing_market(session, tmp_path, "pt", night=fault == "night_anchor")
    if fault == "session":
        session.execute(update(TradingSession).where(
            TradingSession.instrument_symbol == "pt").values(is_active=False))
    else:
        day = date(2025, 11, 26 if fault == "night_anchor" else 27)
        session.execute(delete(TradingCalendar).where(
            TradingCalendar.exchange_code == "GFEX", TradingCalendar.trade_date == day))
    session.commit()
    with pytest.raises(MarketDataError, match=code):
        market.completed_trading_days(
            symbol="pt", start=datetime(2025, 11, 26, 0, tzinfo=UTC),
            as_of=datetime(2025, 11, 28, 2, tzinfo=UTC), latest=date(2025, 11, 28),
            calendar_since=date(2025, 11, 27),
        )


@pytest.mark.parametrize("quality_days", [(), (3,), (2, 3)])
def test_recovery_daily_readback_uses_real_catalog_parquet_and_calendar(
    session, tmp_path, quality_days,
):
    from types import SimpleNamespace
    from scripts.newow_weekly_recovery import _post_commit_readback

    session.scalar(select(TradingSession)).is_active = False
    session.add(Contract(
        contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 2), expired_date=date(2025, 9, 1), provider="rqdata",
    ))
    for day in (2, 3):
        session.add(TradingSession(
            exchange_code="DCE", instrument_symbol="jm", session_name="day",
            start_time=time(9), end_time=time(15), effective_from=date(2025, 1, day),
            effective_to=date(2025, 1, day), is_active=True, provider="rqdata",
        ))
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True,
        ))
    session.commit()
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    bars = tuple(_bar(day, 100) for day in (2, 3) if day not in quality_days)
    facts = tuple(PriceUnavailableFact(
        bar_end=_bar(day, 100).bar_end, trading_day=date(2025, 1, day),
        open=Decimal(0), high=Decimal(0), low=Decimal(0), close=Decimal(100),
        volume=Decimal(2), turnover=Decimal(200), open_interest=Decimal(10),
        request_sha256="a" * 64, response_sha256="b" * 64,
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    ) for day in quality_days)
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, bars, tuple(_bar(day, 100).bar_end for day in (2, 3)),
        price_unavailable=facts,
    )))
    session.commit()
    result = _post_commit_readback(SimpleNamespace(catalog=catalog, store=store), {
        "symbol": "jm", "contract": "JM2509", "frequency": "1d", "targets": [{
            "dataset": list(key.as_tuple()), "year": 2025, "month": 1,
            "expected_start": _bar(2, 100).bar_end.isoformat(),
            "expected_end": _bar(3, 100).bar_end.isoformat(), "expected_bar_count": 2,
        }],
    })
    partition = result["catalog_partitions"][0]
    assert partition["mds_endpoint_count"] == 2
    assert partition["mds_price_unavailable_count"] == len(quality_days)
    assert partition["physical_row_count"] == partition["mds_bar_count"] == 2 - len(quality_days)


@pytest.mark.parametrize("gap_days", [(3,), (4,), (2, 3, 4), ()])
def test_home_daily_quality_page_preserves_exact_endpoints(session, tmp_path, gap_days):
    market = _home_quality_market(session, tmp_path, gap_days=gap_days)
    bars, gaps = market.query_physical_daily_quality_as_of(
        symbol="jm", contract="JM2509", trading_day=date(2025, 1, 4), limit=3,
    )
    assert [bar.trading_day.day for bar in bars] == [d for d in (2, 3, 4) if d not in gap_days]
    assert [gap.trading_day.day for gap in gaps] == list(gap_days)
    if gap_days:
        with pytest.raises(MarketDataError, match="PRICE_UNAVAILABLE"):
            market.query_physical_bars_as_of(
                symbol="jm", contract="JM2509", frequency="1d",
                trading_day=date(2025, 1, 4), limit=3,
            )


@pytest.mark.parametrize("missing_day", [2, 3, 4])
def test_home_daily_quality_page_rejects_missing_prefix_interior_and_tail(
    session, tmp_path, missing_day,
):
    market = _home_quality_market(session, tmp_path, missing_day=missing_day)
    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        market.query_physical_daily_quality_as_of(
            symbol="jm", contract="JM2509", trading_day=date(2025, 1, 4), limit=3,
        )


def test_home_daily_quality_page_bounds_quality_to_requested_window(session, tmp_path):
    market = _home_quality_market(session, tmp_path, gap_days=(2, 4))
    bars, gaps = market.query_physical_daily_quality_as_of(
        symbol="jm", contract="JM2509", trading_day=date(2025, 1, 3), limit=1,
    )
    assert [bar.trading_day.day for bar in bars] == [3]
    assert gaps == ()


@pytest.mark.parametrize("corruption", ["duplicate", "overlap", "wrong_day"])
def test_home_daily_quality_page_rejects_conflicting_identities(
    session, tmp_path, monkeypatch, corruption,
):
    from dataclasses import replace
    market = _home_quality_market(session, tmp_path, gap_days=(3,))
    original = market.read_physical_daily_quality
    def corrupt(*args, **kwargs):
        bars, gaps = original(*args, **kwargs)
        if corruption == "duplicate":
            bars = (*bars, bars[0])
        elif corruption == "overlap":
            bars = (bars[0], _bar(3, 100), bars[-1])
        else:
            bars = (replace(bars[0], trading_day=date(2025, 1, 1)), bars[-1])
        return bars, gaps
    monkeypatch.setattr(market, "read_physical_daily_quality", corrupt)
    with pytest.raises(MarketDataError, match="BAR_IDENTITY_CONFLICT"):
        market.query_physical_daily_quality_as_of(
            symbol="jm", contract="JM2509", trading_day=date(2025, 1, 4), limit=3,
        )


def _home_quality_market(session, tmp_path, *, gap_days=(), missing_day=None):
    session.scalar(select(TradingSession)).is_active = False
    session.add_all(TradingSession(
        exchange_code="DCE", instrument_symbol="jm", session_name="day",
        start_time=time(9), end_time=time(15),
        effective_from=date(2025, 1, day), effective_to=date(2025, 1, day),
        is_active=True, provider="rqdata",
    ) for day in (2, 3, 4))
    session.add(Contract(
        contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 2), expired_date=date(2025, 12, 1), provider="rqdata",
    ))
    session.add_all(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True,
    ) for day in (2, 3, 4))
    bars = tuple(_bar(day, 100 + day) for day in (2, 3, 4)
                 if day not in gap_days and day != missing_day)
    gaps = tuple(PriceUnavailableFact(
        _bar(day, 100).bar_end, date(2025, 1, day), Decimal(0), Decimal(0), Decimal(0),
        Decimal(100), Decimal(2), Decimal(200), Decimal(10),
        "a" * 64, "b" * 64, datetime(2026, 9, 15, tzinfo=UTC),
    ) for day in gap_days)
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    catalog.register_partition(store.publish(PublishRequest(
        key, 2025, 1, bars,
        tuple(sorted([bar.bar_end for bar in bars] + [gap.bar_end for gap in gaps])),
        price_unavailable=gaps,
    )))
    session.commit()
    return MarketDataService(catalog, store)


def test_weekly_identity_conflict_is_not_classified_as_missing_history(session, tmp_path):
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    session.add_all(TradingCalendar(
        exchange_code='DCE', trade_date=date(2025, 1, day), is_trading_day=day < 4,
    ) for day in range(1, 6))
    market = MarketDataService(catalog, store)
    with pytest.raises(MarketDataError) as caught:
        market._validate_actual_endpoints(
            'jm', BarFrequency.W1,
            {date(2025, 1, 2): 'JM2509', date(2025, 1, 3): 'JM2509'},
            (_bar(2, 100),), datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 3, 7, tzinfo=UTC), missing_code='DATASET_OR_PARTITION_MISSING',
        )
    assert caught.value.code == 'DATASET_OR_PARTITION_MISSING'
    assert caught.value.reason == 'REPLAY_ENDPOINTS_EXTRA'
