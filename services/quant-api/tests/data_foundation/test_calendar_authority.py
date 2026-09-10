from datetime import date, time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.metadata import _upsert_calendar
from app.models import TradingCalendar

DAY = date(2026, 9, 9)


def session_row(symbol, day=DAY, night=False):
    return dict(exchange_code="SHFE", instrument_symbol=symbol,
                effective_from=day, effective_to=day, start_time=time(21 if night else 9),
                crosses_midnight=False, is_active=True, provider="rqdata")


def calendar(value, products=()):
    return dict(exchange_code="SHFE", trade_date=DAY, is_trading_day=True,
                has_night_session=value, provider="rqdata", night_session_products=products)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize("existing", [False, True])
def test_subset_day_only_preserves_existing(db, existing):
    db.add(TradingCalendar(exchange_code="SHFE", trade_date=DAY,
                           is_trading_day=True, has_night_session=existing))
    db.flush()
    _upsert_calendar(db, calendar(None), (session_row("wr"),))
    assert db.scalar(select(TradingCalendar)).has_night_session is existing


def test_unknown_missing_calendar_fails(db):
    with pytest.raises(ValueError, match="CALENDAR_NIGHT_AUTHORITY_MISSING"):
        _upsert_calendar(db, calendar(None), (session_row("wr"),))


def test_other_day_night_cannot_prove_today(db):
    with pytest.raises(ValueError, match="CALENDAR_NIGHT_AUTHORITY_MISSING"):
        _upsert_calendar(db, calendar(True), (session_row("au", date(2026, 9, 8), True),))


def test_same_day_night_proves_exchange_positive(db):
    _upsert_calendar(db, calendar(True), (session_row("wr"), session_row("au", night=True)))
    assert db.scalar(select(TradingCalendar)).has_night_session is True


def test_full_exchange_day_coverage_proves_holiday_negative(db):
    _upsert_calendar(db, calendar(False, ("au", "wr")), (session_row("wr"), session_row("au")))
    assert db.scalar(select(TradingCalendar)).has_night_session is False


def test_partial_exchange_coverage_cannot_prove_negative(db):
    with pytest.raises(ValueError, match="CALENDAR_NIGHT_AUTHORITY_MISSING"):
        _upsert_calendar(db, calendar(False, ("au", "wr")), (session_row("wr"),))


@pytest.mark.parametrize("existing", [False, True])
def test_source_conflicts_require_explicit_correction(db, existing):
    db.add(TradingCalendar(exchange_code="SHFE", trade_date=DAY,
                           is_trading_day=True, has_night_session=existing))
    db.flush()
    with pytest.raises(ValueError, match="CALENDAR_SOURCE_CONFLICT"):
        _upsert_calendar(db, calendar(not existing, ("au",)), (session_row("au", night=not existing),))
    assert db.scalar(select(TradingCalendar)).has_night_session is existing


def test_universe_is_day_specific_and_requires_lifecycle():
    from app.market_data.rqdata_adapter import _exchange_day_products
    rows = [dict(exchange="SHFE", underlying_symbol="AU", order_book_id="AU2609", listed_date=date(2020, 1, 1),
                 de_listed_date=date(2026, 9, 9)),
            dict(exchange="SHFE", underlying_symbol="WR", order_book_id="WR2612", listed_date=date(2026, 9, 10),
                 de_listed_date=date(2027, 1, 1))]
    assert _exchange_day_products(rows, "SHFE", DAY) == ()
    assert _exchange_day_products(rows, "SHFE", date(2026, 9, 8)) == ("au",)
    assert _exchange_day_products(rows, "SHFE", date(2026, 9, 10)) == ("wr",)
    rows[1].pop("listed_date")
    assert _exchange_day_products(rows, "SHFE", DAY) == ()


@pytest.mark.parametrize('change', [dict(exchange=None), dict(exchange='UNKNOWN'),
                                 dict(de_listed_date=date(2020, 1, 1)), dict(underlying_symbol=None)])
def test_unclassified_raw_row_cannot_prove_complete_universe(change):
    from app.market_data.rqdata_adapter import _exchange_day_products
    rows = [dict(exchange='SHFE', underlying_symbol=s, order_book_id=s+'2612',
                 listed_date=date(2020, 1, 1), de_listed_date=date(2027, 1, 1)) for s in ('WR','AU')]
    rows[1].update(change)
    assert _exchange_day_products(rows, 'SHFE', DAY) == ()


def test_provider_synthetic_series_are_not_physical_lifecycle_holes():
    from app.market_data.rqdata_adapter import _exchange_day_products
    rows = [dict(exchange='SHFE', underlying_symbol='AU', order_book_id='AU2612',
                 listed_date=date(2020, 1, 1), de_listed_date=date(2027, 1, 1))]
    rows += [dict(exchange='SHFE', underlying_symbol='AU', order_book_id='AU'+suffix,
                  listed_date='0000-00-00', de_listed_date='0000-00-00')
             for suffix in ('88','99','888','889','88A2','88A3')]
    assert _exchange_day_products(rows, 'SHFE', DAY) == ('au',)


def test_source_supported_delivery_suffix_retains_product_coverage():
    from app.market_data.rqdata_adapter import _exchange_day_products
    rows = [dict(exchange='DCE', underlying_symbol='L_F', order_book_id='L2602F',
                 listed_date=date(2025, 10, 29), de_listed_date=date(2026, 1, 30))]
    assert _exchange_day_products(rows, 'DCE', date(2026, 1, 1)) == ('l_f',)


def test_holiday_negative_does_not_borrow_adjacent_night():
    from app.market_data.metadata import calendar_night_fact
    rows = (session_row("au"), session_row("au", date(2026, 9, 8), True))
    assert calendar_night_fact(calendar(False, ("au",)), rows) is False


def test_adapter_preserves_exchange_subset_and_holiday_boundaries():
    import pandas as pd
    from app.market_data.rqdata_adapter import RQDataClient

    previous = date(2026, 9, 8)

    class Api:
        @property
        def futures(self):
            return self

        def all_instruments(self, **kwargs):
            return pd.DataFrame([
                dict(underlying_symbol=symbol, exchange="SHFE", order_book_id=symbol + "2612",
                     listed_date=date(2026, 1, 1), de_listed_date=date(2026, 12, 31))
                for symbol in ("AU", "WR")
            ])

        def get_trading_dates(self, **kwargs):
            return (previous, DAY)

        def get_dominant(self, symbol, **kwargs):
            return pd.Series([symbol + "2612"] * 2, index=pd.to_datetime([previous, DAY]))

        def get_trading_periods(self, contracts, **kwargs):
            return pd.DataFrame([
                dict(order_book_id=contract, date=day,
                     trading_hours="21:01-23:00,09:01-15:00"
                     if contract.startswith("AU") and day == previous else "09:01-15:00")
                for contract in contracts for day in (previous, DAY)
            ])

    client = object.__new__(RQDataClient)
    client.api = Api()
    subset = client.metadata_snapshot(("wr",), DAY, {"wr": previous})
    assert next(row for row in subset.calendars if row["trade_date"] == DAY)["has_night_session"] is None
    complete = client.metadata_snapshot(("au", "wr"), DAY, {"au": previous, "wr": previous})
    rows = {row["trade_date"]: row for row in complete.calendars}
    assert rows[previous]["has_night_session"] is True
    assert rows[DAY]["has_night_session"] is False
    assert rows[DAY]["night_session_products"] == ("au", "wr")
