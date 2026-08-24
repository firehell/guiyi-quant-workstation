from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.subing_daily_watch_calendar import (
    SubingDailyWatchCalendarError,
    resolve_expected_daily_watch_day,
    resolve_next_common_trading_day,
)
from app.models import Exchange, Instrument, TradingCalendar


SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        value.add_all(
            (
                Exchange(code="DCE", name="DCE", timezone="Asia/Shanghai"),
                Exchange(code="SHFE", name="SHFE", timezone="Asia/Shanghai"),
                Instrument(
                    symbol="jm",
                    name="JM",
                    exchange_code="DCE",
                    is_active=True,
                ),
                Instrument(
                    symbol="rb",
                    name="RB",
                    exchange_code="SHFE",
                    is_active=True,
                ),
            )
        )
        for exchange in ("DCE", "SHFE"):
            value.add_all(
                TradingCalendar(
                    exchange_code=exchange,
                    trade_date=trade_date,
                    is_trading_day=is_trading_day,
                )
                for trade_date, is_trading_day in (
                    (date(2026, 8, 28), True),
                    (date(2026, 8, 29), False),
                    (date(2026, 8, 30), False),
                    (date(2026, 8, 31), True),
                )
            )
        value.commit()
        yield value


def test_next_common_trading_day_resolves_friday_to_monday(
    session: Session,
) -> None:
    assert resolve_next_common_trading_day(
        session,
        products=("jm", "rb"),
        source_trading_day=date(2026, 8, 28),
    ) == date(2026, 8, 31)


def test_next_common_trading_day_normalizes_products(session: Session) -> None:
    assert resolve_next_common_trading_day(
        session,
        products=(" JM ", "RB"),
        source_trading_day=date(2026, 8, 28),
    ) == date(2026, 8, 31)


def test_next_common_trading_day_rejects_missing_product_exchange(
    session: Session,
) -> None:
    with pytest.raises(SubingDailyWatchCalendarError) as captured:
        resolve_next_common_trading_day(
            session,
            products=("jm", "missing"),
            source_trading_day=date(2026, 8, 28),
        )

    assert captured.value.code == "OPERATIONAL_PRODUCT_EXCHANGE_UNAVAILABLE"


def test_next_common_trading_day_rejects_missing_calendar_row(
    session: Session,
) -> None:
    session.execute(
        delete(TradingCalendar).where(
            TradingCalendar.exchange_code == "SHFE",
            TradingCalendar.trade_date == date(2026, 8, 31),
        )
    )
    session.commit()

    with pytest.raises(SubingDailyWatchCalendarError) as captured:
        resolve_next_common_trading_day(
            session,
            products=("jm", "rb"),
            source_trading_day=date(2026, 8, 28),
        )

    assert captured.value.code == "NEXT_TRADING_DAY_UNAVAILABLE"


def test_next_common_trading_day_rejects_different_exchange_dates(
    session: Session,
) -> None:
    session.add(
        TradingCalendar(
            exchange_code="SHFE",
            trade_date=date(2026, 9, 1),
            is_trading_day=True,
        )
    )
    session.execute(
        delete(TradingCalendar).where(
            TradingCalendar.exchange_code == "SHFE",
            TradingCalendar.trade_date == date(2026, 8, 31),
        )
    )
    session.commit()

    with pytest.raises(SubingDailyWatchCalendarError) as captured:
        resolve_next_common_trading_day(
            session,
            products=("jm", "rb"),
            source_trading_day=date(2026, 8, 28),
        )

    assert captured.value.code == "NEXT_TRADING_DAY_UNAVAILABLE"


@pytest.mark.parametrize(
    ("now", "expected"),
    (
        (datetime(2026, 8, 28, 18, 19, tzinfo=SHANGHAI), date(2026, 8, 28)),
        (datetime(2026, 8, 28, 18, 20, tzinfo=SHANGHAI), date(2026, 8, 31)),
        (datetime(2026, 8, 29, 8, 0, tzinfo=SHANGHAI), date(2026, 8, 31)),
        (datetime(2026, 8, 31, 8, 0, tzinfo=SHANGHAI), date(2026, 8, 31)),
    ),
)
def test_expected_daily_watch_day_obeys_shanghai_cutover(
    session: Session,
    now: datetime,
    expected: date,
) -> None:
    assert resolve_expected_daily_watch_day(
        session,
        products=("jm", "rb"),
        now=now,
    ) == expected


def test_expected_daily_watch_day_rejects_naive_datetime(session: Session) -> None:
    with pytest.raises(SubingDailyWatchCalendarError) as captured:
        resolve_expected_daily_watch_day(
            session,
            products=("jm", "rb"),
            now=datetime(2026, 8, 28, 18, 19),
        )

    assert captured.value.code == "EXPECTED_TRADING_DAY_UNAVAILABLE"
