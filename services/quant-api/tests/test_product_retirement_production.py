from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

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
)
from app.services.product_retirement_runtime_gate import RetirementRuntimeRequest


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
    assert calendar_count == 0
    assert not staging.exists()
