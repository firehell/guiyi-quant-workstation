from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey, SeriesQuery
from app.market_data.service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest, SourceMetadata
from app.models import (
    ContractSpec,
    DataGap,
    Exchange,
    Instrument,
    MainContractMap,
    MarketPartition,
    TradingCalendar,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        value.add(Exchange(code="DCE", name="Dalian Commodity Exchange"))
        value.add(
            Instrument(
                symbol="jm",
                name="焦煤",
                exchange_code="DCE",
                is_active=True,
            )
        )
        value.commit()
        yield value


def _bar(day: int, close: int, *, month: int = 1) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=datetime(2025, month, day, 7, tzinfo=UTC),
        trading_day=date(2025, month, day),
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=1,
        turnover=10,
        open_interest=20,
    )


def _publish(
    catalog: MarketCatalog,
    store: CanonicalMonthlyStore,
    key: DatasetKey,
    bars: tuple[CanonicalBar, ...],
) -> None:
    result = store.publish(
        PublishRequest(
            dataset=key,
            year=bars[0].trading_day.year,
            month=bars[0].trading_day.month,
            bars=bars,
            expected_bar_ends=tuple(item.bar_end for item in bars),
            source=SourceMetadata(source_kind="rqdata", source_digest="a" * 64),
        )
    )
    catalog.register_partition(result)


def test_catalog_keeps_one_current_partition_per_dataset_month(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")

    _publish(catalog, store, key, (_bar(2, 100),))
    _publish(catalog, store, key, (_bar(2, 101), _bar(3, 102)))
    session.commit()

    rows = list(session.scalars(select(MarketPartition)))
    assert len(rows) == 1
    assert rows[0].row_count == 2
    assert store.read_month(key, 2025, 1)[-1].close == Decimal("102")


def test_main_map_and_contract_specs_upsert_current_fact(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)

    catalog.upsert_main_contracts(
        (("jm", date(2025, 1, 2), "JM2505"),)
    )
    catalog.upsert_main_contracts(
        (("jm", date(2025, 1, 2), "JM2509"),)
    )
    catalog.upsert_contract_specs(
        (
            {
                "contract_code": "JM2509",
                "symbol": "jm",
                "exchange_code": "DCE",
                "trade_date": date(2025, 1, 2),
                "price_tick": Decimal("0.5"),
                "contract_multiplier": Decimal("60"),
                "fee_type": "by_amount",
            },
        )
    )
    catalog.upsert_contract_specs(
        (
            {
                "contract_code": "JM2509",
                "symbol": "jm",
                "exchange_code": "DCE",
                "trade_date": date(2025, 1, 2),
                "price_tick": Decimal("1"),
                "contract_multiplier": Decimal("60"),
                "fee_type": "by_amount",
            },
        )
    )
    session.commit()

    mapping = session.scalar(select(MainContractMap))
    spec = session.scalar(select(ContractSpec))
    assert mapping is not None and mapping.contract_code == "JM2509"
    assert spec is not None and spec.price_tick == Decimal("1")
    assert len(list(session.scalars(select(MainContractMap)))) == 1
    assert len(list(session.scalars(select(ContractSpec)))) == 1


def test_continuous_query_returns_partition_lineage(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(2, 100), _bar(3, 101)))
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            series_kind="continuous",
            symbol="jm",
            frequency="1d",
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 4, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("100"), Decimal("101")]
    assert result.request_identity["series_kind"] == "continuous"
    assert len(result.partition_digests) == 1
    assert result.resolved_contract_segments == ()


def test_query_rejects_manifest_digest_drift_even_when_payload_is_valid(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(2, 100),))
    session.commit()
    partition = catalog.all_partitions(key)[0]
    partition.manifest_path.write_text(
        partition.manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(MarketDataError, match="PARTITION_INTEGRITY_INVALID"):
        MarketDataService(catalog, store).query(SeriesQuery(
            "continuous",
            "jm",
            "1d",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 3, tzinfo=UTC),
        ))


def test_actual_dominant_stitches_rank1_contracts_and_returns_map_digest(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    first = DatasetKey("contract", "jm", "JM2505", "1d")
    second = DatasetKey("contract", "jm", "JM2509", "1d")
    _publish(catalog, store, first, (_bar(2, 100), _bar(3, 101)))
    _publish(catalog, store, second, (_bar(6, 200), _bar(7, 201)))
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 2), "JM2505"),
            ("jm", date(2025, 1, 3), "JM2505"),
            ("jm", date(2025, 1, 6), "JM2509"),
            ("jm", date(2025, 1, 7), "JM2509"),
        )
    )
    for day in (2, 3, 6, 7):
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
        ))
    session.commit()

    result = MarketDataService(catalog, store).query(
        SeriesQuery(
            series_kind="actual_dominant",
            symbol="jm",
            frequency="1d",
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 8, tzinfo=UTC),
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
    assert len(result.main_map_digest or "") == 64


def test_query_fails_closed_for_gap_or_missing_mapped_dataset(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    _publish(catalog, store, key, (_bar(2, 100),))
    catalog.add_gap(
        key,
        datetime(2025, 1, 2, tzinfo=UTC),
        datetime(2025, 1, 3, tzinfo=UTC),
        "COVERAGE_MISSING",
    )
    session.commit()

    service = MarketDataService(catalog, store)
    with pytest.raises(MarketDataError, match="DATA_GAP_INTERSECTS_QUERY"):
        service.query(
            SeriesQuery(
                "continuous",
                "jm",
                "1d",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 4, tzinfo=UTC),
            )
        )

    session.query(DataGap).delete()
    catalog.upsert_main_contracts((("jm", date(2025, 1, 2), "JM2509"),))
    session.add(TradingCalendar(
        exchange_code="DCE", trade_date=date(2025, 1, 2), is_trading_day=True
    ))
    session.commit()
    with pytest.raises(MarketDataError, match="MAPPED_CONTRACT_DATASET_MISSING"):
        service.query(
            SeriesQuery(
                "actual_dominant",
                "jm",
                "1d",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 3, tzinfo=UTC),
            )
        )


def test_actual_dominant_rejects_a_hole_in_daily_rank1_map(session, tmp_path) -> None:
    catalog = MarketCatalog(session, tmp_path)
    store = CanonicalMonthlyStore(tmp_path)
    key = DatasetKey("contract", "jm", "JM2509", "1d")
    _publish(catalog, store, key, (_bar(2, 100), _bar(3, 101)))
    for day in (2, 3):
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=date(2025, 1, day), is_trading_day=True
        ))
    catalog.upsert_main_contracts((("jm", date(2025, 1, 2), "JM2509"),))
    session.commit()

    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        MarketDataService(catalog, store).query(SeriesQuery(
            "actual_dominant",
            "jm",
            "1d",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 4, tzinfo=UTC),
        ))

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
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=True,
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
            datetime(2025, 1, 10, 23, tzinfo=UTC),
        )
    )

    assert [bar.close for bar in result.bars] == [Decimal("209")]
    assert result.resolved_contract_segments[0].contract == "JM2509"
