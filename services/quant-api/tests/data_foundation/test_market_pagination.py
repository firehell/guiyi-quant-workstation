from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey, SeriesPageQuery
from app.market_data.service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Exchange, Instrument, TradingCalendar, TradingSession


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


def _bar(day: int, close: int, *, month: int = 1) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=datetime(2025, month, day, 7, tzinfo=UTC),
        trading_day=date(2025, month, day),
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal(1),
        turnover=Decimal(10),
        open_interest=Decimal(20),
    )


def _publish(
    catalog: MarketCatalog,
    store: CanonicalMonthlyStore,
    key: DatasetKey,
    bars: tuple[CanonicalBar, ...],
) -> None:
    partition = store.publish(
        PublishRequest(
            dataset=key,
            year=bars[0].trading_day.year,
            month=bars[0].trading_day.month,
            bars=bars,
            expected_bar_ends=tuple(bar.bar_end for bar in bars),
        )
    )
    catalog.register_partition(partition)


def _service(session: Session, tmp_path) -> tuple[MarketCatalog, MarketDataService, CanonicalMonthlyStore]:
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(session, tmp_path)
    return catalog, MarketDataService(catalog, store), store


def _calendar_and_map(
    session: Session,
    catalog: MarketCatalog,
    rows: tuple[tuple[int, str], ...],
    *,
    month: int = 1,
) -> None:
    for day, contract in rows:
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, month, day),
                is_trading_day=True,
            )
        )
        catalog.upsert_main_contracts((("jm", date(2025, month, day), contract),))


def test_query_page_returns_latest_physical_bars_ascending(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(
        catalog,
        store,
        DatasetKey("continuous", "jm", "MAIN", "1d"),
        (_bar(2, 100), _bar(3, 101), _bar(4, 102)),
    )
    session.commit()

    result = service.query_page(
        SeriesPageQuery("continuous", "jm", "1d", limit=2)
    )

    assert [bar.close for bar in result.bars] == [Decimal("101"), Decimal("102")]
    assert result.has_more_before is True
    assert result.next_before == result.bars[0].bar_end
    assert result.canonical_coverage == (result.bars[0].bar_end, result.bars[-1].bar_end)


def test_query_page_cursor_is_exclusive(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(
        catalog,
        store,
        DatasetKey("continuous", "jm", "MAIN", "1d"),
        (_bar(2, 100), _bar(3, 101), _bar(4, 102)),
    )
    session.commit()

    result = service.query_page(
        SeriesPageQuery(
            "continuous",
            "jm",
            "1d",
            before=datetime(2025, 1, 4, 7, tzinfo=UTC),
            limit=2,
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("100"), Decimal("101")]
    assert all(bar.bar_end < datetime(2025, 1, 4, 7, tzinfo=UTC) for bar in result.bars)


def test_query_page_crosses_month_partitions_and_stops_at_history_start(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(31, 100),))
    _publish(catalog, store, key, (_bar(1, 101, month=2), _bar(2, 102, month=2)))
    session.commit()

    result = service.query_page(SeriesPageQuery("continuous", "jm", "1d", limit=3))

    assert [bar.close for bar in result.bars] == [Decimal("100"), Decimal("101"), Decimal("102")]
    assert result.has_more_before is False
    assert result.next_before is None


def test_query_page_rejects_an_internal_missing_month_before_returning_older_bars(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(31, 100),))
    _publish(catalog, store, key, (_bar(1, 102, month=3),))
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        service.query_page(SeriesPageQuery("continuous", "jm", "1d", limit=2))


def test_query_page_rejects_cursor_beyond_newest_catalog_coverage(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(
        catalog,
        store,
        DatasetKey("continuous", "jm", "MAIN", "1d"),
        (_bar(2, 100),),
    )
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        service.query_page(
            SeriesPageQuery(
                "continuous",
                "jm",
                "1d",
                before=datetime(2025, 1, 3, 7, tzinfo=UTC),
            )
        )


def test_query_page_rejects_adjacent_partition_coverage_gap(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(2, 100),))
    _publish(catalog, store, key, (_bar(1, 101, month=2),))
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        service.query_page(SeriesPageQuery("continuous", "jm", "1d", limit=2))


def test_query_page_rejects_short_coverage_gap_with_a_formal_trading_day(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(31, 100),))
    _publish(catalog, store, key, (_bar(3, 101, month=2),))
    session.add_all(
        (
            TradingCalendar(exchange_code="DCE", trade_date=date(2025, 2, 1), is_trading_day=True),
            TradingCalendar(exchange_code="DCE", trade_date=date(2025, 2, 2), is_trading_day=False),
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
        service.query_page(SeriesPageQuery("continuous", "jm", "1d", limit=2))


def test_query_page_allows_long_coverage_interval_without_formal_trading_days(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(31, 100),))
    _publish(catalog, store, key, (_bar(20, 101, month=2),))
    session.add_all(
        tuple(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 2, day),
                is_trading_day=False,
            )
            for day in range(1, 20)
        )
    )
    session.commit()

    result = service.query_page(SeriesPageQuery("continuous", "jm", "1d", limit=2))

    assert [bar.close for bar in result.bars] == [Decimal("100"), Decimal("101")]


def test_query_page_actual_dominant_filters_by_formal_owner(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1d"), (_bar(2, 100),))
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1d"), (_bar(2, 200),))
    _calendar_and_map(session, catalog, ((2, "JM2509"),))
    session.commit()

    result = service.query_page(SeriesPageQuery("actual_dominant", "jm", "1d"))

    assert [bar.close for bar in result.bars] == [Decimal("200")]
    assert [segment.contract for segment in result.resolved_contract_segments] == ["JM2509"]


def test_query_page_actual_dominant_crosses_contract_switch(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1d"), (_bar(2, 100),))
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1d"), (_bar(3, 200),))
    _calendar_and_map(session, catalog, ((2, "JM2505"), (3, "JM2509")))
    session.commit()

    result = service.query_page(SeriesPageQuery("actual_dominant", "jm", "1d"))

    assert [bar.close for bar in result.bars] == [Decimal("100"), Decimal("200")]
    assert [segment.contract for segment in result.resolved_contract_segments] == ["JM2505", "JM2509"]


def test_query_page_actual_dominant_rejects_newer_mapped_contract_without_bar(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1d"), (_bar(2, 100),))
    _calendar_and_map(session, catalog, ((2, "JM2505"), (3, "JM2509")))
    session.commit()

    with pytest.raises(MarketDataError, match="MAPPED_CONTRACT_DATASET_MISSING"):
        service.query_page(SeriesPageQuery("actual_dominant", "jm", "1d", limit=2))


def test_query_page_actual_dominant_ignores_old_same_month_bar_outside_page_boundary(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1d"), (_bar(2, 100),))
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1d"), (_bar(10, 200),))
    _calendar_and_map(session, catalog, ((10, "JM2509"),))
    session.commit()

    result = service.query_page(SeriesPageQuery("actual_dominant", "jm", "1d", limit=1))

    assert [bar.close for bar in result.bars] == [Decimal("200")]
    assert result.has_more_before is False


def test_query_page_actual_dominant_week_uses_complete_week_owner(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1w"), (_bar(10, 105),))
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1w"), (_bar(10, 209),))
    _calendar_and_map(
        session,
        catalog,
        tuple((day, "JM2505" if day < 8 else "JM2509") for day in range(6, 11)),
    )
    session.commit()

    result = service.query_page(
        SeriesPageQuery(
            "actual_dominant",
            "jm",
            "1w",
            before=datetime(2025, 1, 11, 7, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("209")]
    assert result.resolved_contract_segments[0].contract == "JM2509"


def test_query_page_actual_dominant_week_rejects_newer_complete_week_owner_without_bar(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1w"), (_bar(10, 105),))
    _calendar_and_map(
        session,
        catalog,
        tuple((day, "JM2505") for day in range(6, 11))
        + tuple((day, "JM2509") for day in range(13, 18)),
    )
    session.commit()

    with pytest.raises(MarketDataError, match="MAPPED_CONTRACT_DATASET_MISSING"):
        service.query_page(SeriesPageQuery("actual_dominant", "jm", "1w", limit=1))


def test_query_page_actual_dominant_week_rejects_missing_weekday_owner_fact(session, tmp_path) -> None:
    catalog, service, store = _service(session, tmp_path)
    _publish(catalog, store, DatasetKey("contract", "jm", "JM2509", "1w"), (_bar(10, 209),))
    for day in (6, 7, 9, 10):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=True,
            )
        )
        catalog.upsert_main_contracts((("jm", date(2025, 1, day), "JM2509"),))
    session.add(
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2025, 1, 8),
            is_trading_day=True,
        )
    )
    session.commit()

    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        service.query_page(
            SeriesPageQuery(
                "actual_dominant",
                "jm",
                "1w",
                before=datetime(2025, 1, 11, 7, tzinfo=UTC),
            )
        )


@pytest.mark.parametrize("failure", ("missing_map", "mapped_partition"))
def test_query_page_actual_dominant_remains_fail_closed(session, tmp_path, failure: str) -> None:
    catalog, service, store = _service(session, tmp_path)
    if failure == "missing_map":
        _publish(catalog, store, DatasetKey("contract", "jm", "JM2505", "1d"), (_bar(2, 100),))
        session.add(TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 2), is_trading_day=True))
        expected = "MAIN_CONTRACT_MAP_MISSING"
    else:
        _calendar_and_map(session, catalog, ((2, "JM2505"),))
        expected = "MAPPED_CONTRACT_DATASET_MISSING"
    session.commit()

    with pytest.raises(MarketDataError, match=expected):
        service.query_page(SeriesPageQuery("actual_dominant", "jm", "1d"))
