from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import LiveAggregatedBar, LiveMinuteBar, TradingCalendar, TradingSession
from app.services.live_multi_tf_aggregation import LiveAggregationConfig, LiveMultiTfAggregationService


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _seed_calendar_and_session(session, *, friday_is_trading: bool = True) -> list[date]:
    monday = date(2026, 7, 6)
    trading_days: list[date] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        is_trading = day.weekday() < 5 and (friday_is_trading or day.weekday() != 4)
        if is_trading:
            trading_days.append(day)
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=day,
                is_trading_day=is_trading,
                has_night_session=False,
                provider="fixture",
            )
        )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="fixture_day",
            start_time=time(9, 0),
            end_time=time(9, 5),
            crosses_midnight=False,
            is_active=True,
            provider="fixture",
        )
    )
    session.flush()
    return trading_days


def _add_day(session, trading_day: date, *, count: int = 5) -> None:
    for index in range(count):
        timestamp = datetime.combine(trading_day, time(9, index + 1))
        price = Decimal(100 + index)
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period="1m",
                bar_datetime=timestamp,
                trading_day=trading_day,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=Decimal("1"),
                open_interest=Decimal("10"),
                turnover=Decimal("100"),
                bar_status="confirmed",
                quality_status="passed",
                source_mode="poll_get_price_1m",
                first_seen_at=timestamp,
                last_seen_at=timestamp,
                confirmed_at=timestamp,
                revision=0,
                raw_payload={},
            )
        )
    session.flush()


def test_daily_and_weekly_only_confirm_after_calendar_close() -> None:
    with _session() as session:
        trading_days = _seed_calendar_and_session(session)
        for day in trading_days:
            _add_day(session, day)
        session.commit()

        before_close = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 10, 9, 5, 30)).aggregate_once(
            LiveAggregationConfig(contract="JM2609", symbol="jm", exchange="DCE", periods=("1d", "1w")),
            dry_run=True,
        )
        after_close = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 10, 9, 7)).aggregate_once(
            LiveAggregationConfig(contract="JM2609", symbol="jm", exchange="DCE", periods=("1d", "1w"))
        )
        session.commit()
        rows = list(session.scalars(select(LiveAggregatedBar).order_by(LiveAggregatedBar.period, LiveAggregatedBar.bar_datetime)))

    assert before_close.period_results["1w"]["candidate_count"] == 0
    assert after_close.period_results["1d"]["candidate_count"] == 5
    assert after_close.period_results["1w"]["candidate_count"] == 1
    weekly = next(row for row in rows if row.period == "1w")
    assert weekly.bar_datetime == datetime(2026, 7, 10)
    assert weekly.source_bar_count == 25
    assert weekly.expected_bar_count == 25
    assert weekly.quality_status == "passed"


def test_holiday_short_week_confirms_on_last_calendar_trading_day() -> None:
    with _session() as session:
        trading_days = _seed_calendar_and_session(session, friday_is_trading=False)
        for day in trading_days:
            _add_day(session, day)
        session.commit()

        result = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 9, 9, 7)).aggregate_once(
            LiveAggregationConfig(contract="JM2609", symbol="jm", exchange="DCE", periods=("1w",))
        )
        session.commit()
        weekly = session.scalar(select(LiveAggregatedBar).where(LiveAggregatedBar.period == "1w"))

    assert result.period_results["1w"]["candidate_count"] == 1
    assert weekly is not None
    assert weekly.bar_datetime == datetime(2026, 7, 9)
    assert weekly.quality_status == "passed"
