from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.catalog import CatalogPartition
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest


def _bar(minute: int) -> CanonicalBar:
    end = datetime(2025, 1, 2, 1, minute, tzinfo=UTC)
    price = Decimal("100")
    return CanonicalBar(end, date(2025, 1, 2), price, price, price, price, 1, 10, 20)


def _service(tmp_path, *, missing_last: bool = False):
    bars = (_bar(1), _bar(2))
    key = DatasetKey("contract", "jm", "JM2501", "1m")
    store = CanonicalMonthlyStore(tmp_path)
    published = store.publish(PublishRequest(
        key, 2025, 1, bars, tuple(bar.bar_end for bar in bars),
    ))
    partition = CatalogPartition(
        key, 2025, 1, published.coverage_start, published.coverage_end,
        published.parquet_path, published.row_count,
    )
    catalog = SimpleNamespace(
        contract_fact=lambda symbol, contract: SimpleNamespace(
            listed_date=date(2025, 1, 2), expired_date=date(2025, 2, 1),
        ),
        all_partitions=lambda dataset: (partition,),
    )
    market = MarketDataService(catalog, store)
    market._trading_day_window = lambda **kwargs: (
        datetime(2025, 1, 2, 1, 0, tzinfo=UTC),
        datetime(2025, 1, 2, 1, 3, tzinfo=UTC),
    )
    market._exact_calendar = lambda *args: ((date(2025, 1, 2), True),)
    market.session_windows = lambda **kwargs: (
        SimpleNamespace(end=datetime(2025, 1, 2, 1, 3, tzinfo=UTC)),
    )
    expected = tuple((bar.bar_end, bar.trading_day) for bar in bars)
    if missing_last:
        expected += ((datetime(2025, 1, 2, 1, 3, tzinfo=UTC), date(2025, 1, 2)),)
    market.expected_contract_replay_endpoints = lambda **kwargs: expected
    return market, bars


def test_bounded_physical_replay_yields_verified_one_bar_chunks(tmp_path):
    market, bars = _service(tmp_path)
    chunks = tuple(market.iter_contract_replay_chunks(
        symbol="jm", contract="JM2501", frequency="1m",
        through=date(2025, 1, 2), cutoff=bars[-1].bar_end,
        max_rows=1,
    ))
    assert tuple(bar for chunk in chunks for bar in chunk.bars) == bars
    assert all(len(chunk.bars) <= 1 and not chunk.source_quality for chunk in chunks)


def test_bounded_physical_replay_requires_complete_exhaustion(tmp_path):
    market, bars = _service(tmp_path, missing_last=True)
    cursor = market.iter_contract_replay_chunks(
        symbol="jm", contract="JM2501", frequency="1m",
        through=date(2025, 1, 2), cutoff=bars[-1].bar_end,
        max_rows=1,
    )
    assert next(cursor).bars == (bars[0],)
    with pytest.raises(MarketDataError, match="CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"):
        tuple(cursor)


def test_weekly_boundary_context_does_not_duplicate_prior_month(tmp_path):
    market, bars = _service(tmp_path)
    current = bars[-1]
    prior = CanonicalBar(
        datetime(2024, 12, 31, 1, 0, tzinfo=UTC), date(2024, 12, 31),
        current.open, current.high, current.low, current.close,
        current.volume, current.turnover, current.open_interest,
    )
    market.expected_contract_replay_endpoints = lambda **kwargs: (
        (current.bar_end, current.trading_day),
    )
    market.query_contract_weekly_replay_quality = lambda **kwargs: ((prior, current), ())
    chunks = tuple(market.iter_contract_replay_chunks(
        symbol="jm", contract="JM2501", frequency="1w",
        through=date(2025, 1, 2), cutoff=current.bar_end,
    ))
    assert tuple(bar for chunk in chunks for bar in chunk.bars) == (current,)
