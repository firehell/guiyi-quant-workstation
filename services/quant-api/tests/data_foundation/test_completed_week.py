"""Calendar and Session, including short weeks, own W1 completion."""

from datetime import UTC, date, datetime, timedelta
from types import MethodType

from app.market_data.aggregation import SessionWindow
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_data_service import MarketDataError
import pytest
from types import SimpleNamespace


def test_short_week_uses_last_authoritative_session_not_friday():
    market = object.__new__(MarketDataService)
    monday = date(2026, 9, 28)
    last_end = datetime(2026, 9, 30, 7, tzinfo=UTC)
    calendar = tuple(
        (monday + timedelta(days=index), index < 3)
        for index in range(7)
    )
    market._exact_calendar = MethodType(
        lambda _self, symbol, since, through: calendar, market,
    )
    market.session_windows = MethodType(
        lambda _self, *, symbol, trading_day: (
            SessionWindow(
                datetime.combine(trading_day, datetime.min.time(), UTC),
                last_end if trading_day == date(2026, 9, 30)
                else datetime.combine(trading_day, datetime.min.time(), UTC)
                + timedelta(hours=7),
            ),
        ), market,
    )

    assert market.completed_calendar_week(
        symbol="rb", week_monday=monday, as_of=last_end,
    ) is None
    assert market.completed_calendar_week(
        symbol="rb", week_monday=monday,
        as_of=last_end + timedelta(microseconds=1),
    ) == (date(2026, 9, 30), last_end + timedelta(microseconds=1))


def test_weekly_tail_fallback_requires_whole_week_unpublished():
    market = object.__new__(MarketDataService)
    monday = date(2026, 9, 14)
    market._exact_calendar = MethodType(
        lambda _self, symbol, since, through: tuple(
            (monday + timedelta(days=index), index < 5) for index in range(7)
        ), market,
    )
    mappings = []
    market.catalog = SimpleNamespace(main_map=lambda symbol, start, end: tuple(mappings))
    assert market.weekly_tail_unpublished(symbol="rb", week_end=date(2026, 9, 18))
    mappings.append(SimpleNamespace(trade_date=monday))
    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        market.weekly_tail_unpublished(symbol="rb", week_end=date(2026, 9, 18))
    mappings[:] = [SimpleNamespace(trade_date=monday + timedelta(days=index)) for index in range(5)]
    assert not market.weekly_tail_unpublished(symbol="rb", week_end=date(2026, 9, 18))
