from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.duplicate_active_supersede import build_duplicate_active_supersede_plan


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _add_file(
    session: Session,
    *,
    file_id: int,
    product: str,
    contract: str,
    period: str,
    end_time: datetime,
    data_version: str,
    start_time: datetime | None = None,
    data_role: str = "primary",
) -> None:
    session.add(
        MarketDataFile(
            id=file_id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol=product,
            contract_code=contract,
            period=period,
            start_time=start_time or datetime(2023, 1, 3, tzinfo=UTC),
            end_time=end_time,
            file_path=f"/tmp/{product}_{contract}_{period}_{data_version}.parquet",
            row_count=10,
            data_version=data_version,
            data_role=data_role,
            quality_status="passed",
        )
    )


def test_build_plan_marks_older_duplicate_as_superseded() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_file(session, file_id=1, product="jm", contract="jm.MAIN", period="15m", end_time=datetime(2026, 7, 7, tzinfo=UTC), data_version="old")
        _add_file(session, file_id=2, product="jm", contract="jm.MAIN", period="15m", end_time=datetime(2026, 7, 10, tzinfo=UTC), data_version="new")
        session.commit()
        result = build_duplicate_active_supersede_plan(session=session, apply=False)

    assert result["duplicate_group_count"] == 1
    assert result["rows_to_supersede"] == 1
    decisions = {row["market_data_file_id"]: row["decision"] for row in result["plan_rows"]}
    assert decisions[2] == "keep_primary"
    assert decisions[1] == "mark_superseded"


def test_apply_sets_superseded_role() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_file(session, file_id=1, product="a", contract="a.MAIN", period="1d", end_time=datetime(2026, 7, 7, tzinfo=UTC), data_version="v1")
        _add_file(session, file_id=2, product="a", contract="a.MAIN", period="1d", end_time=datetime(2026, 7, 10, tzinfo=UTC), data_version="v2")
        session.commit()
        result = build_duplicate_active_supersede_plan(session=session, apply=True, confirm=True)
        session.commit()
        roles = {row.id: row.data_role for row in session.scalars(select(MarketDataFile).order_by(MarketDataFile.id))}

    assert result["apply_result"]["superseded_count"] == 1
    assert roles[1] == "superseded"
    assert roles[2] == "primary"


def test_pick_current_prefers_widest_start_when_end_equal() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_file(
            session,
            file_id=1,
            product="a",
            contract="a.MAIN",
            period="1w",
            start_time=datetime(2023, 1, 6, tzinfo=UTC),
            end_time=datetime(2026, 7, 10, tzinfo=UTC),
            data_version="narrow",
            data_role="primary",
        )
        _add_file(
            session,
            file_id=2,
            product="a",
            contract="a.MAIN",
            period="1w",
            start_time=datetime(2002, 3, 15, tzinfo=UTC),
            end_time=datetime(2026, 7, 10, tzinfo=UTC),
            data_version="wide",
            data_role="superseded",
        )
        session.commit()
        result = build_duplicate_active_supersede_plan(session=session, apply=True, confirm=True)
        session.commit()
        roles = {row.id: row.data_role for row in session.scalars(select(MarketDataFile))}

    assert roles[2] == "primary"
    assert roles[1] == "superseded"
    assert result["apply_result"]["superseded_count"] == 1


def test_apply_blocked_without_confirm() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_file(session, file_id=1, product="bb", contract="bb.MAIN", period="1w", end_time=datetime(2026, 7, 7, tzinfo=UTC), data_version="v1")
        _add_file(session, file_id=2, product="bb", contract="bb.MAIN", period="1w", end_time=datetime(2026, 7, 10, tzinfo=UTC), data_version="v2")
        session.commit()
        result = build_duplicate_active_supersede_plan(session=session, apply=True, confirm=False)

    assert result["ready_to_apply"] is False
    assert "confirmation_required" in result["blocked_reasons"]
