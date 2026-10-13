from datetime import datetime, date, UTC, timedelta
from types import SimpleNamespace

import pytest

from app.market_data.newow.product_reader import NewowProductReader, NewowProductReadError
from guiyi_quant.newow.product_contracts import ProductFrequency


def reader(published, days):
    value = NewowProductReader.__new__(NewowProductReader)
    value._market_data = SimpleNamespace(
        query_page=lambda query: SimpleNamespace(bars=(SimpleNamespace(
            trading_day=published, bar_end=datetime.combine(published, datetime.min.time(), UTC)),)),
        completed_trading_days=lambda **_: days)
    value.weekly_snapshot_candidates = lambda *_, **__: tuple((day, None) for day in reversed(days))
    return value


def test_daily_waits_only_current_unpublished_tail_then_uses_new_publication():
    today, previous = date(2026, 10, 13), date(2026, 10, 12)
    early = datetime(2026, 10, 13, 8, tzinfo=UTC)  # 16:00 Shanghai
    value = reader(previous, (previous, today))
    assert value._forward_published_through('rb', ProductFrequency.DAILY, today, early) == previous
    with pytest.raises(NewowProductReadError, match='CANONICAL_PUBLICATION_LAGGING'):
        value._forward_published_through('rb', ProductFrequency.DAILY, today, early + timedelta(hours=3))
    assert reader(today, (previous, today))._forward_published_through('rb', ProductFrequency.DAILY, today, early) == today


def test_old_unpublished_daily_gap_is_never_hidden_by_current_wait():
    value = reader(date(2026, 10, 9), (date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13)))
    with pytest.raises(NewowProductReadError, match='CANONICAL_PUBLICATION_LAGGING'):
        value._forward_published_through('rb', ProductFrequency.DAILY, date(2026, 10, 13), datetime(2026, 10, 13, 8, tzinfo=UTC))


def test_weekly_uses_completed_week_not_current_tuesday_and_missing_prior_week_blocks():
    previous = date(2026, 10, 9)
    at = datetime(2026, 10, 13, 8, tzinfo=UTC)
    assert reader(previous, (previous,))._forward_published_through('rb', ProductFrequency.WEEKLY, at.date(), at) == previous
    with pytest.raises(NewowProductReadError, match='CANONICAL_PUBLICATION_LAGGING'):
        reader(date(2026, 10, 2), (previous,))._forward_published_through('rb', ProductFrequency.WEEKLY, at.date(), at)


def test_missing_physical_or_owner_failure_is_not_publication_wait():
    from app.market_data.market_data_service import MarketDataError
    value = reader(date(2026, 10, 12), ())
    def missing(_query):
        raise MarketDataError('MAPPED_CONTRACT_DATASET_MISSING')
    value._market_data.query_page = missing
    with pytest.raises(MarketDataError, match='MAPPED_CONTRACT_DATASET_MISSING'):
        value._forward_published_through('rb', ProductFrequency.DAILY, date(2026, 10, 13), datetime(2026, 10, 13, 8, tzinfo=UTC))
