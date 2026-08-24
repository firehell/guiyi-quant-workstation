"""Resolve the common trading day for the SuBing Daily Watch."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.session_clock import SHANGHAI
from app.models import Instrument, TradingCalendar


class SubingDailyWatchCalendarError(RuntimeError):
    """Stable fail-closed error for Daily Watch calendar resolution."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def resolve_next_common_trading_day(
    session: Session,
    *,
    products: tuple[str, ...],
    source_trading_day: date,
) -> date:
    """Resolve the first identical trading day after ``source_trading_day``."""
    exchanges = _resolve_product_exchanges(session, products)
    return _resolve_next_day_for_exchanges(
        session,
        exchanges=exchanges,
        source_trading_day=source_trading_day,
    )


def resolve_expected_daily_watch_day(
    session: Session,
    *,
    products: tuple[str, ...],
    now: datetime,
    cutover: time = time(18, 20),
) -> date:
    """Resolve the Daily Watch day expected at an aware point in time."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise SubingDailyWatchCalendarError("EXPECTED_TRADING_DAY_UNAVAILABLE")

    exchanges = _resolve_product_exchanges(session, products)
    local_now = now.astimezone(SHANGHAI)
    current_day = local_now.date()
    current_states: list[bool] = []
    for exchange in exchanges:
        rows = tuple(
            session.scalars(
                select(TradingCalendar.is_trading_day).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date == current_day,
                )
            )
        )
        if len(rows) != 1:
            raise SubingDailyWatchCalendarError("EXPECTED_TRADING_DAY_UNAVAILABLE")
        current_states.append(rows[0])

    if len(set(current_states)) != 1:
        raise SubingDailyWatchCalendarError("EXPECTED_TRADING_DAY_UNAVAILABLE")
    local_time = local_now.timetz().replace(tzinfo=None)
    if current_states[0] and local_time < cutover:
        return current_day

    try:
        return _resolve_next_day_for_exchanges(
            session,
            exchanges=exchanges,
            source_trading_day=current_day,
        )
    except SubingDailyWatchCalendarError as exc:
        if exc.code != "NEXT_TRADING_DAY_UNAVAILABLE":
            raise
        raise SubingDailyWatchCalendarError(
            "EXPECTED_TRADING_DAY_UNAVAILABLE"
        ) from exc


def _resolve_product_exchanges(
    session: Session,
    products: tuple[str, ...],
) -> tuple[str, ...]:
    normalized = tuple(product.strip().lower() for product in products)
    if not normalized or any(not product for product in normalized):
        raise SubingDailyWatchCalendarError(
            "OPERATIONAL_PRODUCT_EXCHANGE_UNAVAILABLE"
        )
    if len(set(normalized)) != len(normalized):
        raise SubingDailyWatchCalendarError(
            "OPERATIONAL_PRODUCT_EXCHANGE_UNAVAILABLE"
        )

    product_exchanges: list[str] = []
    for product in normalized:
        rows = tuple(
            session.scalars(
                select(Instrument.exchange_code).where(
                    Instrument.symbol == product,
                    Instrument.is_active.is_(True),
                )
            )
        )
        if len(rows) != 1 or not rows[0].strip():
            raise SubingDailyWatchCalendarError(
                "OPERATIONAL_PRODUCT_EXCHANGE_UNAVAILABLE"
            )
        product_exchanges.append(rows[0].strip().upper())
    return tuple(sorted(set(product_exchanges)))


def _resolve_next_day_for_exchanges(
    session: Session,
    *,
    exchanges: tuple[str, ...],
    source_trading_day: date,
) -> date:
    next_days: list[date] = []
    for exchange in exchanges:
        next_day = session.scalar(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date > source_trading_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date)
            .limit(1)
        )
        if next_day is None:
            raise SubingDailyWatchCalendarError("NEXT_TRADING_DAY_UNAVAILABLE")
        next_days.append(next_day)
    if len(set(next_days)) != 1:
        raise SubingDailyWatchCalendarError("NEXT_TRADING_DAY_UNAVAILABLE")
    return next_days[0]
