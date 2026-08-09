from __future__ import annotations

from datetime import date, datetime, time

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.session_clock import (
    SHANGHAI,
    resolved_session_windows_for_trading_day,
    session_windows_for_trading_day,
)
from app.models import Exchange, Instrument, TradingCalendar, TradingSession


def _now(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2025, 1, day, hour, minute, second, tzinfo=SHANGHAI)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            (
                Exchange(code="DCE", name="DCE"),
                Exchange(code="CZCE", name="CZCE"),
                Exchange(code="SHFE", name="SHFE"),
                Instrument(symbol="j", name="J", exchange_code="DCE", is_active=True),
                Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True),
                Instrument(symbol="ap", name="AP", exchange_code="CZCE", is_active=True),
                Instrument(symbol="ag", name="AG", exchange_code="SHFE", is_active=True),
            )
        )
        for exchange in ("DCE", "CZCE", "SHFE"):
            session.add_all(
                (
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 2),
                        is_trading_day=True,
                        has_night_session=True,
                    ),
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 3),
                        is_trading_day=True,
                        has_night_session=False,
                    ),
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 4),
                        is_trading_day=False,
                    ),
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 5),
                        is_trading_day=False,
                    ),
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 6),
                        is_trading_day=True,
                        has_night_session=True,
                    ),
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 7),
                        is_trading_day=True,
                        has_night_session=True,
                    ),
                    TradingCalendar(
                        exchange_code=exchange,
                        trade_date=date(2025, 1, 8),
                        is_trading_day=False,
                    ),
                )
            )
        for exchange, symbol in (("DCE", "j"), ("DCE", "jm"), ("CZCE", "ap"), ("SHFE", "ag")):
            session.add_all(
                (
                    TradingSession(
                        exchange_code=exchange,
                        instrument_symbol=symbol,
                        session_name="morning_1",
                        start_time=time(9),
                        end_time=time(10, 15),
                        effective_from=date(2025, 1, 1),
                        crosses_midnight=False,
                        is_active=True,
                    ),
                    TradingSession(
                        exchange_code=exchange,
                        instrument_symbol=symbol,
                        session_name="morning_2",
                        start_time=time(10, 30),
                        end_time=time(11, 30),
                        effective_from=date(2025, 1, 1),
                        crosses_midnight=False,
                        is_active=True,
                    ),
                    TradingSession(
                        exchange_code=exchange,
                        instrument_symbol=symbol,
                        session_name="afternoon",
                        start_time=time(13, 30),
                        end_time=time(15),
                        effective_from=date(2025, 1, 1),
                        crosses_midnight=False,
                        is_active=True,
                    ),
                )
            )
        session.add_all(
            (
                TradingSession(
                    exchange_code="DCE",
                    instrument_symbol="jm",
                    session_name="night",
                    start_time=time(21),
                    end_time=time(23),
                    effective_from=date(2025, 1, 1),
                    crosses_midnight=False,
                    is_active=True,
                ),
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol="ag",
                    session_name="night",
                    start_time=time(21),
                    end_time=time(2, 30),
                    effective_from=date(2025, 1, 1),
                    crosses_midnight=True,
                    is_active=True,
                ),
            )
        )
        session.commit()
        yield session


@pytest.mark.parametrize(
    ("now", "expected"),
    (
        (_now(6, 9), MarketPhase.TRADING),
        (_now(6, 10, 14, 59), MarketPhase.TRADING),
        (_now(6, 10, 15), MarketPhase.BREAK),
        (_now(6, 10, 20), MarketPhase.BREAK),
        (_now(6, 10, 29, 59), MarketPhase.BREAK),
        (_now(6, 10, 30), MarketPhase.TRADING),
        (_now(6, 11, 30), MarketPhase.BREAK),
        (_now(6, 13, 30), MarketPhase.TRADING),
        (_now(6, 15), MarketPhase.CLOSED),
    ),
)
def test_dce_phase_boundaries_are_fact_derived(
    session: Session,
    now: datetime,
    expected: MarketPhase,
) -> None:
    result = MarketPhaseResolver(session).resolve("j", now)

    assert result.phase is expected
    assert result.trading_day == date(2025, 1, 6)


@pytest.mark.parametrize("symbol", ("ap", "ag"))
def test_czce_and_shfe_use_their_own_date_scoped_session_facts(
    session: Session, symbol: str
) -> None:
    result = MarketPhaseResolver(session).resolve(symbol, _now(6, 10, 20))

    assert result.phase is MarketPhase.BREAK
    assert result.trading_day == date(2025, 1, 6)


def test_night_session_is_anchored_to_its_next_trading_day(session: Session) -> None:
    result = MarketPhaseResolver(session).resolve("jm", _now(3, 21))

    assert result.phase is MarketPhase.TRADING
    assert result.trading_day == date(2025, 1, 6)


def test_cross_midnight_session_keeps_the_same_trading_day_identity(session: Session) -> None:
    result = MarketPhaseResolver(session).resolve("ag", _now(4, 0, 30))

    assert result.phase is MarketPhase.TRADING
    assert result.trading_day == date(2025, 1, 6)


def test_resolved_session_metadata_projects_to_existing_windows(session: Session) -> None:
    resolved = resolved_session_windows_for_trading_day(
        session,
        exchange="SHFE",
        symbol="ag",
        trading_day=date(2025, 1, 6),
    )

    assert [(item.name, item.is_night) for item in resolved] == [
        ("night", True),
        ("morning_1", False),
        ("morning_2", False),
        ("afternoon", False),
    ]
    assert session_windows_for_trading_day(
        session,
        exchange="SHFE",
        symbol="ag",
        trading_day=date(2025, 1, 6),
    ) == tuple(item.window for item in resolved)


def test_weekend_and_exchange_holiday_are_closed(session: Session) -> None:
    resolver = MarketPhaseResolver(session)

    assert resolver.resolve("j", _now(4, 12)).phase is MarketPhase.CLOSED
    assert resolver.resolve("j", _now(8, 12)).phase is MarketPhase.CLOSED


def test_missing_calendar_facts_are_unknown(session: Session) -> None:
    session.execute(
        delete(TradingCalendar).where(TradingCalendar.exchange_code == "CZCE")
    )
    session.commit()

    assert MarketPhaseResolver(session).resolve("ap", _now(6, 10)).phase is MarketPhase.UNKNOWN


def test_missing_intermediate_calendar_fact_cannot_shift_friday_night_to_tuesday(
    session: Session,
) -> None:
    session.execute(
        delete(TradingCalendar).where(
            TradingCalendar.exchange_code == "DCE",
            TradingCalendar.trade_date == date(2025, 1, 6),
        )
    )
    session.commit()

    assert MarketPhaseResolver(session).resolve("jm", _now(3, 21)).phase is MarketPhase.UNKNOWN


def test_missing_session_facts_are_unknown(session: Session) -> None:
    session.execute(
        delete(TradingSession).where(TradingSession.instrument_symbol == "ap")
    )
    session.commit()

    assert MarketPhaseResolver(session).resolve("ap", _now(6, 10)).phase is MarketPhase.UNKNOWN


def test_missing_nearby_session_facts_are_not_hidden_by_current_trading_window(
    session: Session,
) -> None:
    for template in session.scalars(
        select(TradingSession).where(TradingSession.instrument_symbol == "ap")
    ):
        template.effective_to = date(2025, 1, 6)
    session.commit()

    assert MarketPhaseResolver(session).resolve("ap", _now(6, 10)).phase is MarketPhase.UNKNOWN
