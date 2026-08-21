"""Read-only prospective-calendar gate for the frozen JDJ validation."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument, TradingCalendar

from .jdj_candidate_validation_policy import (
    JdjCandidateValidationProtocolError,
    load_jdj_candidate_validation_protocol,
)


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

    try:
        evidence = (
            load_jdj_candidate_validation_protocol().prospective_calendar_evidence
        )
    except JdjCandidateValidationProtocolError:
        raise JdjProspectiveCalendarError() from None

    instruments = session.scalars(
        select(Instrument).where(
            Instrument.symbol == "jm",
            Instrument.is_active.is_(True),
        )
    ).all()
    if len(instruments) != 1:
        raise JdjProspectiveCalendarError()
    exchange_code = instruments[0].exchange_code
    if (
        type(exchange_code) is not str
        or exchange_code != evidence.exchange_code
    ):
        raise JdjProspectiveCalendarError()

    calendars = session.scalars(
        select(TradingCalendar).where(
            TradingCalendar.exchange_code == exchange_code,
            TradingCalendar.trade_date.in_(tuple(_EXPECTED_CALENDAR)),
        )
    ).all()
    observed: dict[date, bool] = {}
    for row in calendars:
        if (
            type(row.trade_date) is not date
            or type(row.is_trading_day) is not bool
            or row.trade_date in observed
        ):
            raise JdjProspectiveCalendarError()
        observed[row.trade_date] = row.is_trading_day
    required_catalog = {
        trade_date: is_trading_day
        for trade_date, is_trading_day in _EXPECTED_CALENDAR.items()
        if trade_date < evidence.query_through
    }
    if any(observed.get(day) != value for day, value in required_catalog.items()):
        raise JdjProspectiveCalendarError()
    future_value = observed.get(evidence.query_through)
    if future_value is not None and future_value is not True:
        raise JdjProspectiveCalendarError()
