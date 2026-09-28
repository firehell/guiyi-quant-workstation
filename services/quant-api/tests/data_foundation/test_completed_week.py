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


def test_week_in_progress_and_weekend_use_the_same_last_session_cutoff():
    market = object.__new__(MarketDataService)
    monday = date(2026, 9, 14)
    friday_end = datetime(2026, 9, 18, 7, tzinfo=UTC)
    market._exact_calendar = MethodType(
        lambda _self, symbol, since, through: tuple(
            (monday + timedelta(days=index), index < 5) for index in range(7)
        ), market,
    )
    market.session_windows = MethodType(
        lambda _self, *, symbol, trading_day: (
            SessionWindow(friday_end - timedelta(hours=7), friday_end),
        ), market,
    )
    assert market.completed_calendar_week(
        symbol="rb", week_monday=monday,
        as_of=datetime(2026, 9, 17, 8, tzinfo=UTC),
    ) is None
    cutoff = friday_end + timedelta(microseconds=1)
    assert market.completed_calendar_week(
        symbol="rb", week_monday=monday, as_of=cutoff,
    ) == (date(2026, 9, 18), cutoff)
    assert market.completed_calendar_week(
        symbol="rb", week_monday=monday,
        as_of=datetime(2026, 9, 19, 8, tzinfo=UTC),
    ) == (date(2026, 9, 18), cutoff)


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


@pytest.mark.parametrize("as_of", [
    datetime(2026, 9, 28, 10, tzinfo=UTC),
    datetime(2026, 9, 29, 15, 59, tzinfo=UTC),
])
def test_incomplete_week_does_not_require_future_last_day_session(as_of):
    market = object.__new__(MarketDataService)
    monday = date(2026, 9, 28)
    market._exact_calendar = MethodType(
        lambda _self, symbol, since, through: tuple(
            (monday + timedelta(days=index), index < 3) for index in range(7)
        ), market,
    )

    def missing_session(_self, *, symbol, trading_day):
        raise MarketDataError("TRADING_SESSION_MISSING")

    market.session_windows = MethodType(missing_session, market)
    assert market.completed_calendar_week(
        symbol="rb", week_monday=monday, as_of=as_of,
    ) is None


@pytest.mark.parametrize("as_of", [
    datetime(2026, 9, 29, 16, tzinfo=UTC),  # Shanghai last trading day has begun.
    datetime(2026, 10, 1, 8, tzinfo=UTC),
])
def test_due_last_day_still_requires_authoritative_session(as_of):
    market = object.__new__(MarketDataService)
    monday = date(2026, 9, 28)
    market._exact_calendar = MethodType(
        lambda _self, symbol, since, through: tuple(
            (monday + timedelta(days=index), index < 3) for index in range(7)
        ), market,
    )

    def missing_session(_self, *, symbol, trading_day):
        raise MarketDataError("TRADING_SESSION_MISSING")

    market.session_windows = MethodType(missing_session, market)
    with pytest.raises(MarketDataError, match="TRADING_SESSION_MISSING"):
        market.completed_calendar_week(symbol="rb", week_monday=monday, as_of=as_of)


def test_weekly_reader_uses_completed_prior_week_without_future_sessions():
    from app.market_data.newow.product_reader import NewowProductReader

    market = object.__new__(MarketDataService)
    now = datetime(2026, 9, 28, 10, tzinfo=UTC)
    prior_end = datetime(2026, 9, 24, 7, tzinfo=UTC)
    market._exact_calendar = MethodType(
        lambda _self, symbol, since, through: tuple(
            (since + timedelta(days=index), index < (3 if since.day == 28 else 4))
            for index in range(7)
        ), market,
    )

    def sessions(_self, *, symbol, trading_day):
        if trading_day != date(2026, 9, 24):
            raise MarketDataError("TRADING_SESSION_MISSING")
        return (SessionWindow(prior_end - timedelta(hours=6), prior_end),)

    market.session_windows = MethodType(sessions, market)
    reader = NewowProductReader(
        market, coverage=SimpleNamespace(product_start=lambda symbol: date(2026, 9, 21)),
        active_products=("rb",), now=lambda: now,
    )
    assert reader.weekly_snapshot_candidates("rb", as_of=now) == (
        (date(2026, 9, 24), prior_end + timedelta(microseconds=1)),
    )


def test_incomplete_week_still_requires_exact_calendar():
    market = object.__new__(MarketDataService)

    def missing_calendar(_self, symbol, since, through):
        raise MarketDataError("TRADING_CALENDAR_MISSING")

    market._exact_calendar = MethodType(missing_calendar, market)
    with pytest.raises(MarketDataError, match="TRADING_CALENDAR_MISSING"):
        market.completed_calendar_week(
            symbol="rb", week_monday=date(2026, 9, 28),
            as_of=datetime(2026, 9, 28, 10, tzinfo=UTC),
        )
