"""交易日到实际历史 SessionWindow 的唯一转换逻辑。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.market_data.aggregation import SessionWindow
from app.models import TradingCalendar, TradingSession


SHANGHAI = ZoneInfo("Asia/Shanghai")


class SessionClockError(RuntimeError):
    """历史 Session 事实无法构成有效窗口。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def session_windows_for_trading_day(
    session: Session,
    *,
    exchange: str,
    symbol: str,
    trading_day: date,
) -> tuple[SessionWindow, ...]:
    """以交易日为身份解析日盘与锚定前一交易日的夜盘窗口。"""
    templates = tuple(
        session.scalars(
            select(TradingSession)
            .where(
                TradingSession.exchange_code == exchange,
                TradingSession.instrument_symbol == symbol.strip().lower(),
                TradingSession.is_active.is_(True),
                TradingSession.effective_from <= trading_day,
                (
                    TradingSession.effective_to.is_(None)
                    | (TradingSession.effective_to >= trading_day)
                ),
            )
            .order_by(TradingSession.start_time)
        )
    )
    if not templates:
        raise SessionClockError("TRADING_SESSION_MISSING")
    prior = session.scalar(
        select(func.max(TradingCalendar.trade_date)).where(
            TradingCalendar.exchange_code == exchange,
            TradingCalendar.trade_date < trading_day,
            TradingCalendar.is_trading_day.is_(True),
        )
    )
    windows: list[SessionWindow] = []
    for template in templates:
        is_night = template.start_time >= time(18)
        if is_night and prior is None:
            raise SessionClockError("PREVIOUS_TRADING_DAY_MISSING")
        base = prior if is_night else trading_day
        assert base is not None
        local_start = datetime.combine(base, template.start_time, tzinfo=SHANGHAI)
        end_day = base
        if template.crosses_midnight or template.end_time <= template.start_time:
            end_day += timedelta(days=1)
        local_end = datetime.combine(end_day, template.end_time, tzinfo=SHANGHAI)
        windows.append(SessionWindow(local_start, local_end))
    windows.sort(key=lambda item: item.start)
    return tuple(windows)
