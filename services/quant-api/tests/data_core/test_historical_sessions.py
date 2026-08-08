from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.aggregation import AggregationSession
from app.data_core.contracts import (
    BarFrequency,
    ContractValidationError,
    DatasetKey,
    DatasetKind,
)
from app.data_core.historical_sessions import build_provider_sessions, product_sessions
from app.db.base import Base
from app.models.data_center import Instrument, TradingCalendar, TradingSession


def _dataset(frequency: BarFrequency) -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=frequency,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _orm_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_product_sessions_fail_closed_when_actual_exchange_templates_missing() -> None:
    with _orm_session() as session:
        session.add(
            Instrument(
                symbol="cj",
                name="红枣",
                exchange_code="CZCE",
                sector="agri",
                category="future",
                is_active=True,
            )
        )
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
                provider="fixture_cnfe",
            )
        )
        session.commit()

        with pytest.raises(ContractValidationError) as exc:
            product_sessions(
                session,
                symbol="cj",
                start=datetime(2026, 7, 7, 1, 0, tzinfo=UTC),
                end=datetime(2026, 7, 7, 8, 0, tzinfo=UTC),
            )

    assert exc.value.facts == {"field": "sessions", "reason": "missing"}


def test_product_sessions_use_actual_exchange_templates() -> None:
    with _orm_session() as session:
        session.add(
            Instrument(
                symbol="cj",
                name="红枣",
                exchange_code="CZCE",
                sector="agri",
                category="future",
                is_active=True,
            )
        )
        for offset in range(-1, 3):
            day = date(2026, 7, 7) + timedelta(days=offset)
            session.add(
                TradingCalendar(
                    exchange_code="CZCE",
                    trade_date=day,
                    is_trading_day=day.weekday() < 5,
                    has_night_session=False,
                    provider="fixture",
                )
            )
        session.add(
            TradingSession(
                exchange_code="CZCE",
                instrument_symbol="cj",
                session_name="day_am1",
                start_time=time(9, 0),
                end_time=time(10, 15),
                crosses_midnight=False,
                is_active=True,
                provider="fixture",
            )
        )
        session.commit()

        result = product_sessions(
            session,
            symbol="cj",
            start=datetime(2026, 7, 7, 1, 0, tzinfo=UTC),
            end=datetime(2026, 7, 7, 3, 0, tzinfo=UTC),
        )

    assert len(result) == 1
    assert result[0].name == "day_am1"
    assert result[0].trading_day == date(2026, 7, 7)


def test_minute_provider_sessions_emit_only_exact_bar_ends() -> None:
    session = AggregationSession(
        trading_day=date(2026, 7, 1),
        name="night",
        start=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
        end=datetime(2026, 6, 30, 13, 3, tzinfo=UTC),
    )

    result = build_provider_sessions(
        _dataset(BarFrequency.M1),
        start=datetime(2026, 6, 30, 13, 1, tzinfo=UTC),
        end=datetime(2026, 6, 30, 13, 3, tzinfo=UTC),
        sessions=(session,),
    )

    assert result[0].expected_bar_ends == (
        datetime(2026, 6, 30, 13, 2, tzinfo=UTC),
        datetime(2026, 6, 30, 13, 3, tzinfo=UTC),
    )


def test_daily_and_weekly_provider_sessions_use_utc_trading_day_labels() -> None:
    sessions = tuple(
        AggregationSession(
            trading_day=trading_day,
            name="day",
            start=datetime(2026, 6, day, 1, 0, tzinfo=UTC),
            end=datetime(2026, 6, day, 7, 0, tzinfo=UTC),
        )
        for day, trading_day in (
            (29, date(2026, 6, 29)),
            (30, date(2026, 6, 30)),
        )
    ) + (
        AggregationSession(
            trading_day=date(2026, 7, 1),
            name="day",
            start=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
            end=datetime(2026, 7, 1, 7, 0, tzinfo=UTC),
        ),
    )
    start = datetime(2026, 6, 28, tzinfo=UTC)
    end = datetime(2026, 7, 1, tzinfo=UTC)

    daily = build_provider_sessions(
        _dataset(BarFrequency.D1),
        start=start,
        end=end,
        sessions=sessions,
    )
    weekly = build_provider_sessions(
        _dataset(BarFrequency.W1),
        start=start,
        end=end,
        sessions=sessions,
    )

    assert [item.expected_bar_ends[0] for item in daily] == [
        datetime(2026, 6, 29, tzinfo=UTC),
        datetime(2026, 6, 30, tzinfo=UTC),
        datetime(2026, 7, 1, tzinfo=UTC),
    ]
    assert [item.expected_bar_ends[0] for item in weekly] == [
        datetime(2026, 7, 1, tzinfo=UTC)
    ]
