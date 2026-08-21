"""Read-only prospective-calendar gate for the frozen JDJ validation."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument, TradingCalendar


_EXPECTED_CALENDAR = {
    date(2026, 8, 21): True,
    date(2026, 8, 22): False,
    date(2026, 8, 23): False,
    date(2026, 8, 24): True,
}


class JdjProspectiveCalendarError(ValueError):
    code = "JDJ_PROSPECTIVE_CALENDAR_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


def assert_jdj_prospective_calendar(session: Session) -> None:
    """Assert the exact jm embargo/weekend/first-OOS calendar facts."""

    instruments = session.scalars(
        select(Instrument).where(
            Instrument.symbol == "jm",
            Instrument.is_active.is_(True),
        )
    ).all()
    if len(instruments) != 1:
        raise JdjProspectiveCalendarError()
    exchange_code = instruments[0].exchange_code
    if type(exchange_code) is not str or not exchange_code:
        raise JdjProspectiveCalendarError()

    calendars = session.scalars(
        select(TradingCalendar).where(
            TradingCalendar.exchange_code == exchange_code,
            TradingCalendar.trade_date.in_(tuple(_EXPECTED_CALENDAR)),
        )
    ).all()
    if len(calendars) != len(_EXPECTED_CALENDAR):
        raise JdjProspectiveCalendarError()

    observed: dict[date, bool] = {}
    for row in calendars:
        if (
            type(row.trade_date) is not date
            or type(row.is_trading_day) is not bool
            or row.trade_date in observed
        ):
            raise JdjProspectiveCalendarError()
        observed[row.trade_date] = row.is_trading_day
    if observed != _EXPECTED_CALENDAR:
        raise JdjProspectiveCalendarError()
