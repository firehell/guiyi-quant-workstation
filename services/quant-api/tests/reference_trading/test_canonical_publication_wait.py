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


def subing_source(published, days):
    from app.market_data.subing_reference import SubingReferenceService
    source = SubingReferenceService.__new__(SubingReferenceService)
    source.market_data = reader(published, days)._market_data
    source.coverage = SimpleNamespace(product_start=lambda _: days[0])
    source.check_cancelled = lambda: None
    source.market_data.completed_calendar_week = lambda **kw: next(((day, None) for day in reversed(days)
        if day - timedelta(days=day.weekday()) == kw['week_monday']), None)
    source._weekly_through = lambda _symbol, through, _as_of: max(day for day in days if day <= through)
    calls = []
    def window(query):
        calls.append(query.through)
        through = query.through or days[-1]
        return days[0], through, datetime.combine(through, datetime.min.time(), UTC) + timedelta(hours=7), query.as_of
    source.resolve_read_window = window
    return source, calls


def test_subing_forward_waits_for_today_publication_without_changing_page_window():
    from app.market_data.subing_reference import SubingReferenceQuery
    previous, today = date(2026, 10, 26), date(2026, 10, 27)
    source, calls = subing_source(previous, (previous, today))
    query = SubingReferenceQuery('pd', frequency='1d', as_of=datetime(2026, 10, 27, 9, tzinfo=UTC))
    assert source.resolve_forward_read_window(query)[1] == previous
    assert calls == [None, previous]
    assert source.resolve_read_window(query)[1] == today


@pytest.mark.parametrize('old_gap,as_of', [
    (False, datetime(2026, 10, 27, 10, 5, tzinfo=UTC)),
    (True, datetime(2026, 10, 27, 9, tzinfo=UTC)),
])
def test_subing_unpublished_due_period_stays_blocked(old_gap, as_of):
    from app.market_data.subing_reference import SubingReferenceQuery, SubingReferenceError
    source, _ = subing_source(date(2026, 10, 23) if old_gap else date(2026, 10, 26),
        (date(2026, 10, 26), date(2026, 10, 27)))
    with pytest.raises(SubingReferenceError, match='CANONICAL_PUBLICATION_LAGGING'):
        source.resolve_forward_read_window(SubingReferenceQuery('pd', frequency='1d', as_of=as_of))


def test_subing_publication_does_not_hide_missing_physical_source():
    from app.market_data.subing_reference import SubingReferenceQuery
    from app.market_data.market_data_service import MarketDataError
    source, _ = subing_source(date(2026, 10, 26), (date(2026, 10, 26), date(2026, 10, 27)))
    def missing(_):
        raise MarketDataError('MAPPED_CONTRACT_DATASET_MISSING')
    source.market_data.query_page = missing
    with pytest.raises((MarketDataError, RuntimeError), match='MAPPED_CONTRACT_DATASET_MISSING|SUBING_REFERENCE_DATA_UNAVAILABLE'):
        source.resolve_forward_read_window(SubingReferenceQuery('pd', frequency='1d', as_of=datetime(2026, 10, 27, 9, tzinfo=UTC)))


def test_subing_capture_waits_without_requesting_today_unpublished_physical_range():
    from app.reference_trading.forward_inputs import capture_subing_canonical
    from tests.reference_trading.test_subing_six_period_capture import identity
    previous, today = date(2026, 10, 26), date(2026, 10, 27)
    source, _ = subing_source(previous, (previous, today))
    source.load_historical_inputs = lambda **_: pytest.fail('unpublished tail read')
    assert capture_subing_canonical(source, identity('1d'), revision_id='r', generation=1,
        after=datetime(2026, 10, 26, 7, tzinfo=UTC), recording_start=datetime(2026, 10, 26, 6, tzinfo=UTC),
        now=datetime(2026, 10, 27, 9, tzinfo=UTC)) is None


def test_subing_weekly_wait_is_only_today_completed_week_not_prior_week_gap():
    from app.market_data.subing_reference import SubingReferenceQuery, SubingReferenceError
    source, _ = subing_source(date(2026, 10, 23), (date(2026, 10, 23), date(2026, 10, 30)))
    query = SubingReferenceQuery('pd', frequency='1w', as_of=datetime(2026, 10, 30, 9, tzinfo=UTC))
    assert source.resolve_forward_read_window(query)[1] == date(2026, 10, 23)
    source, _ = subing_source(date(2026, 10, 16), (date(2026, 10, 16), date(2026, 10, 23)))
    with pytest.raises(SubingReferenceError, match='CANONICAL_PUBLICATION_LAGGING'):
        source.resolve_forward_read_window(SubingReferenceQuery('pd', frequency='1w', as_of=datetime(2026, 10, 27, 9, tzinfo=UTC)))
