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


def _seed_historical_jm_calendar(session, start: date, end: date) -> None:
    current = start
    while current <= end:
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=current,
                is_trading_day=current.weekday() < 5,
                # Production history before 2023 did not populate this flag.
                has_night_session=False,
                provider="fixture",
            )
        )
        current += timedelta(days=1)
    for name, start_time, end_time in (
        ("night", time(21, 0), time(23, 0)),
        ("day_am_1", time(9, 0), time(10, 15)),
        ("day_am_2", time(10, 30), time(11, 30)),
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


def test_historical_jm_night_session_uses_effective_dated_regimes() -> None:
    with _session() as session:
        _seed_historical_jm_calendar(
            session,
            date(2014, 12, 22),
            date(2020, 5, 8),
        )
        clock = TradingSessionClock(session)

        before_launch = clock.windows_for_trading_day(
            date(2014, 12, 26), product="jm", exchange="DCE"
        )
        initial_long = clock.windows_for_trading_day(
            date(2014, 12, 29), product="jm", exchange="DCE"
        )
        shortened_2330 = clock.windows_for_trading_day(
            date(2015, 5, 11), product="jm", exchange="DCE"
        )
        shortened_2300 = clock.windows_for_trading_day(
            date(2019, 4, 1), product="jm", exchange="DCE"
        )
        covid_suspended = clock.windows_for_trading_day(
            date(2020, 2, 4), product="jm", exchange="DCE"
        )
        covid_resumed = clock.windows_for_trading_day(
            date(2020, 5, 7), product="jm", exchange="DCE"
        )

    def night(windows):
        return next((item for item in windows if item.name == "night"), None)

    assert night(before_launch) is None
    assert (night(initial_long).start, night(initial_long).end) == (
        datetime(2014, 12, 26, 21, 0),
        datetime(2014, 12, 27, 2, 30),
    )
    assert (night(shortened_2330).start, night(shortened_2330).end) == (
        datetime(2015, 5, 8, 21, 0),
        datetime(2015, 5, 8, 23, 30),
    )
    assert (night(shortened_2300).start, night(shortened_2300).end) == (
        datetime(2019, 3, 29, 21, 0),
        datetime(2019, 3, 29, 23, 0),
    )
    assert night(covid_suspended) is None
    assert (night(covid_resumed).start, night(covid_resumed).end) == (
        datetime(2020, 5, 6, 21, 0),
        datetime(2020, 5, 6, 23, 0),
    )


def test_historical_jm_first_trading_day_after_holiday_has_no_night() -> None:
    with _session() as session:
        _seed_historical_jm_calendar(
            session,
            date(2019, 9, 27),
            date(2019, 10, 10),
        )
        for current in (
            date(2019, 9, 30),
            date(2019, 10, 1),
            date(2019, 10, 2),
            date(2019, 10, 3),
            date(2019, 10, 4),
            date(2019, 10, 7),
        ):
            calendar = session.query(TradingCalendar).filter_by(
                exchange_code="DCE",
                trade_date=current,
            ).one()
            calendar.is_trading_day = False
        session.commit()

        windows = TradingSessionClock(session).windows_for_trading_day(
            date(2019, 10, 8), product="jm", exchange="DCE"
        )

    assert [item.name for item in windows] == [
        "day_am_1",
        "day_am_2",
        "day_pm",
    ]


def test_czce_ignores_cnfe_product_continuous_day_and_uses_builtin_segments() -> None:
    """Wrong CNFE continuous 09:00-15:00 must not drive CZCE/cj expected coverage."""
    with _session() as session:
        trading_day = date(2026, 7, 7)
        session.add(
            TradingCalendar(
                exchange_code="CZCE",
                trade_date=trading_day,
                is_trading_day=True,
                has_night_session=False,
                provider="fixture",
            )
        )
        session.add(
            TradingSession(
                exchange_code="CNFE",
                instrument_symbol="cj",
                session_name="regular",
                start_time=time(9, 0),
                end_time=time(15, 0),
                crosses_midnight=False,
                is_active=True,
                provider="fixture_bad_cnfe",
            )
        )
        session.commit()

        clock = TradingSessionClock(session)
        windows = clock.windows_for_trading_day(trading_day, product="cj", exchange="CZCE")
        expected_minutes = clock.expected_minute_count(trading_day, product="cj", exchange="CZCE")

    assert [item.name for item in windows] == ["day_am1", "day_am2", "day_pm"]
    assert [(item.start.time(), item.end.time()) for item in windows] == [
        (time(9, 0), time(10, 15)),
        (time(10, 30), time(11, 30)),
        (time(13, 30), time(15, 0)),
    ]
    # 75 + 60 + 90 = 225 minutes → 15 bars at 15m
    assert expected_minutes == 225
    assert expected_minutes // 15 == 15
