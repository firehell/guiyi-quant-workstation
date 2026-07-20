from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import TradingCalendar, TradingSession
from app.services.trading_session_clock import TradingSessionClock


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _seed(session) -> None:
    start = date(2026, 6, 29)
    for offset in range(14):
        day = start + timedelta(days=offset)
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=day,
                is_trading_day=day.weekday() < 5,
                has_night_session=day.weekday() < 5,
                provider="fixture",
            )
        )
    for name, start_time, end_time in (
        ("night", time(21, 0), time(23, 0)),
        ("day_am", time(9, 0), time(11, 30)),
        ("day_pm", time(13, 30), time(15, 0)),
    ):
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name=name,
                start_time=start_time,
                end_time=end_time,
                crosses_midnight=False,
                is_active=True,
                provider="fixture",
            )
        )
    session.commit()


def test_night_session_is_anchored_to_previous_trading_day() -> None:
    with _session() as session:
        _seed(session)
        clock = TradingSessionClock(session)

        friday_night = clock.decision(product="jm", exchange="DCE", now=datetime(2026, 7, 3, 21, 30))
        sunday_night = clock.decision(product="jm", exchange="DCE", now=datetime(2026, 7, 5, 21, 30))
        monday_night = clock.decision(product="jm", exchange="DCE", now=datetime(2026, 7, 6, 21, 30))

    assert friday_night.is_trading_time is True
    assert friday_night.trading_day == date(2026, 7, 6)
    assert sunday_night.should_poll is False
    assert monday_night.trading_day == date(2026, 7, 7)


def test_midday_break_and_close_grace_are_distinct() -> None:
    with _session() as session:
        _seed(session)
        clock = TradingSessionClock(session, close_grace_seconds=90)

        break_time = clock.decision(product="jm", exchange="DCE", now=datetime(2026, 7, 7, 11, 45))
        grace = clock.decision(product="jm", exchange="DCE", now=datetime(2026, 7, 7, 15, 1))
        closed = clock.decision(product="jm", exchange="DCE", now=datetime(2026, 7, 7, 15, 2))

    assert break_time.should_poll is False
    assert break_time.next_open_at == datetime(2026, 7, 7, 13, 30)
    assert grace.phase == "close_grace"
    assert grace.should_poll is True
    assert closed.should_poll is False


def test_expected_minutes_and_week_calendar_coverage() -> None:
    with _session() as session:
        _seed(session)
        clock = TradingSessionClock(session)

        expected = clock.expected_minute_count(date(2026, 7, 7), product="jm", exchange="DCE")
        week_days, complete = clock.week_trading_days(date(2026, 7, 7), exchange="DCE")

    assert expected == 360
    assert week_days == [date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)]
    assert complete is True


def test_batch_windows_match_single_day_semantics() -> None:
    with _session() as session:
        _seed(session)
        clock = TradingSessionClock(session)
        days = [date(2026, 7, 6), date(2026, 7, 7)]

        batch = clock.windows_for_trading_days(days, product="jm", exchange="DCE")
        singles = [
            window
            for trading_day in days
            for window in clock.windows_for_trading_day(trading_day, product="jm", exchange="DCE")
        ]

    assert batch == sorted(singles, key=lambda item: item.start)


def test_single_and_batch_windows_both_skip_night_when_calendar_disables_it() -> None:
    with _session() as session:
        _seed(session)
        trading_day = date(2026, 7, 7)
        calendar = session.query(TradingCalendar).filter_by(
            exchange_code="DCE",
            trade_date=trading_day,
        ).one()
        calendar.has_night_session = False
        session.commit()
        clock = TradingSessionClock(session)

        single = clock.windows_for_trading_day(trading_day, product="jm", exchange="DCE")
        batch = clock.windows_for_trading_days([trading_day], product="jm", exchange="DCE")

    assert [item.name for item in single] == ["day_am", "day_pm"]
    assert single == batch


def test_trading_day_range_requires_complete_natural_date_calendar() -> None:
    with _session() as session:
        _seed(session)
        clock = TradingSessionClock(session)
        days, complete = clock.trading_days_between(
            date(2026, 7, 6),
            date(2026, 7, 10),
            exchange="DCE",
        )
        missing = session.query(TradingCalendar).filter_by(
            exchange_code="DCE",
            trade_date=date(2026, 7, 8),
        ).one()
        session.delete(missing)
        session.commit()
        _, incomplete = clock.trading_days_between(
            date(2026, 7, 6),
            date(2026, 7, 10),
            exchange="DCE",
        )

    assert days == [
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
    ]
    assert complete is True
    assert incomplete is False


def test_latest_completed_trading_day_uses_final_session_close() -> None:
    with _session() as session:
        _seed(session)
        clock = TradingSessionClock(session, close_grace_seconds=90)

        during_day = clock.latest_completed_trading_day(
            product="jm",
            exchange="DCE",
            now=datetime(2026, 7, 7, 14, 0),
        )
        after_close = clock.latest_completed_trading_day(
            product="jm",
            exchange="DCE",
            now=datetime(2026, 7, 7, 15, 2),
        )

    assert during_day == date(2026, 7, 6)
    assert after_close == date(2026, 7, 7)


def test_latest_completed_trading_day_fails_closed_on_calendar_gap() -> None:
    with _session() as session:
        _seed(session)
        session.delete(
            session.query(TradingCalendar).filter_by(
                exchange_code="DCE",
                trade_date=date(2026, 7, 7),
            ).one()
        )
        session.commit()

        clock = TradingSessionClock(session)
        try:
            clock.latest_completed_trading_day(
                product="jm",
                exchange="DCE",
                now=datetime(2026, 7, 7, 14, 0),
            )
        except RuntimeError as exc:
            assert str(exc) == "trading_calendar_stale"
        else:
            raise AssertionError("calendar gap must fail closed")
