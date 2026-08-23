from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    CanonicalBar,
    ContractTradingDayQuery,
    DatasetKey,
    SeriesQuery,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import (
    Contract,
    Exchange,
    Instrument,
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
            datetime(2025, 1, 3, 14, tzinfo=UTC),
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
    _publish(catalog, store, contract, (friday_night, monday_close, tuesday))
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

    assert result.bars == (friday_night, monday_close)
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
    _publish(catalog, store, contract, (friday_night, monday_day))
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
                end_time=time(23),
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

    assert result.bars == (friday_night, monday_day)
    assert result.request_identity["start"] == "2025-01-03T13:00:00+00:00"
    assert result.request_identity["end"] == "2025-01-06T07:00:00+00:00"
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
    source = inspect.getsource(MarketDataService)
    assert "sha256" not in source.lower()
    assert "manifest" not in source.lower()
    assert "data_gap" not in source.lower()
