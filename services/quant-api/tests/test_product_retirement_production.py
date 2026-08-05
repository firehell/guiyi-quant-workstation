from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.data_center import (
    Exchange,
    Instrument,
    TradingCalendar,
    TradingSession,
)
from app.services.product_retirement_production import (
    EXPECTED_DATABASE_REVISION,
    ProductionRetainedUniverseRefresher,
    build_rqdata_aggregation_sessions,
)
from app.services.product_retirement_runtime_gate import RetirementRuntimeRequest


def test_rqdata_periods_become_break_aware_aggregation_sessions() -> None:
    provider_days = (
        date(2026, 7, 31),
        date(2026, 8, 3),
        date(2026, 8, 4),
    )
    sessions = build_rqdata_aggregation_sessions(
        product="a",
        rows=(
            {
                "order_book_id": "A88",
                "date": date(2026, 8, 3),
                "trading_hours": ("21:01-23:00,09:01-10:15,10:31-11:30,13:31-15:00"),
            },
        ),
        trading_days=(date(2026, 8, 3),),
        provider_days=provider_days,
    )

    assert [(item.name, item.start, item.end) for item in sessions] == [
        (
            "rqdata_01",
            datetime(2026, 7, 31, 13, 0, tzinfo=UTC),
            datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
        ),
        (
            "rqdata_02",
            datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
            datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
        ),
        (
            "rqdata_03",
            datetime(2026, 8, 3, 2, 30, tzinfo=UTC),
            datetime(2026, 8, 3, 3, 30, tzinfo=UTC),
        ),
        (
            "rqdata_04",
            datetime(2026, 8, 3, 5, 30, tzinfo=UTC),
            datetime(2026, 8, 3, 7, 0, tzinfo=UTC),
        ),
    ]


def test_rqdata_periods_keep_cross_midnight_night_session() -> None:
    sessions = build_rqdata_aggregation_sessions(
        product="au",
        rows=(
            {
                "order_book_id": "AU88",
                "date": date(2026, 8, 3),
                "trading_hours": "21:01-02:30,09:01-10:15",
            },
        ),
        trading_days=(date(2026, 8, 3),),
        provider_days=(date(2026, 7, 31), date(2026, 8, 3)),
    )

    assert sessions[0].start == datetime(2026, 7, 31, 13, 0, tzinfo=UTC)
    assert sessions[0].end == datetime(2026, 7, 31, 18, 30, tzinfo=UTC)
    assert sessions[0].trading_day == date(2026, 8, 3)


def test_production_preflight_checks_rqdata_without_writing_calendar_or_staging(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Exchange.__table__,
            Instrument.__table__,
            TradingCalendar.__table__,
            TradingSession.__table__,
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        )
        connection.execute(
            text("INSERT INTO alembic_version(version_num) VALUES (:revision)"),
            {"revision": EXPECTED_DATABASE_REVISION},
        )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    products = tuple(f"keep_{index:02d}" for index in range(69))
    with session_factory() as session, session.begin():
        session.add(Exchange(code="DCE", name="DCE"))
        session.add_all(
            Instrument(
                symbol=product,
                name=product,
                exchange_code="DCE",
                is_active=True,
            )
            for product in products
        )
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol=None,
                session_name="day",
                start_time=time(9),
                end_time=time(15),
                crosses_midnight=False,
                is_active=True,
                provider="rqdata",
            )
        )
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    roots = {
        "raw": tmp_path / "raw",
        "canonical": canonical,
        "processed": tmp_path / "processed",
    }
    runtime = tmp_path / "runtime"
    protected = tmp_path / "protected"
    for path in (roots["raw"], roots["processed"], runtime, protected):
        path.mkdir()
    active_products = tmp_path / "active_products.txt"
    active_products.write_text("\n".join(products) + "\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-test",
        rollback_tag="runtime-rollback-test",
        runtime_root=runtime,
        protected_root=protected,
        active_products_path=active_products,
        roots=roots,
    )
    calls: list[tuple[date, date]] = []
    readiness_calls: list[tuple[date, tuple[str, ...]]] = []
    period_calls: list[tuple[tuple[str, ...], date, date]] = []

    class Client:
        def trading_dates(self, start_date: date, end_date: date):
            calls.append((start_date, end_date))
            return [end_date - timedelta(days=offset) for offset in range(20)]

        def market_data_readiness(self, *, expected_date, categories):
            readiness_calls.append((expected_date, tuple(categories)))
            return {
                category: {
                    "latest_date": expected_date.isoformat(),
                    "ready": True,
                }
                for category in categories
            }

        def contract_trading_periods(
            self, contracts, *, start_date: date, end_date: date
        ):
            period_calls.append((tuple(contracts), start_date, end_date))
            return pd.DataFrame(
                [
                    {
                        "order_book_id": contract,
                        "date": end_date,
                        "trading_hours": "09:01-10:15",
                    }
                    for contract in contracts
                ]
            )

    staging = tmp_path / "staging"
    refresher = ProductionRetainedUniverseRefresher(
        session_factory=session_factory,
        rqdata_client=Client(),
        canonical_root=canonical,
        staging_root=staging,
        database_revision=EXPECTED_DATABASE_REVISION,
        now=lambda: datetime(2026, 8, 5, 12, tzinfo=UTC),
        min_free_bytes=0,
    )

    result = refresher.preflight(request)

    with session_factory() as session:
        calendar_count = session.scalar(select(func.count(TradingCalendar.id)))
    assert result["status"] == "passed"
    assert result["active_product_count"] == 69
    assert len(calls) == 1
    assert readiness_calls == [(date(2026, 8, 5), ("future_minbar", "future_daybar"))]
    assert len(period_calls) == 1
    assert len(period_calls[0][0]) == 69
    assert result["provider_session_product_count"] == 69
    assert calendar_count == 0
    assert not staging.exists()
