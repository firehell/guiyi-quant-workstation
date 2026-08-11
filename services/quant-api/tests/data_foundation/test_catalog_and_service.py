from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey, SeriesQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import (
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


@pytest.mark.parametrize("failure", ("missing_partition", "unreadable", "row_count"))
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
    else:
        session.execute(update(MarketPartition).values(row_count=2))
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
