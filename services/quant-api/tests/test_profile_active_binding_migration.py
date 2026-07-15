from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import ProfileActiveBinding


def _postgres_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url or "postgresql" not in url:
        return None
    return url


@pytest.mark.skipif(_postgres_url() is None, reason="DATABASE_URL with PostgreSQL is required")
def test_profile_active_binding_partial_unique_index_on_postgresql() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("services/quant-api/alembic.ini")
    config.set_main_option("script_location", "services/quant-api/alembic")
    config.set_main_option("sqlalchemy.url", _postgres_url() or "")

    try:
        command.upgrade(config, "head")
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL migration upgrade unavailable: {exc}")

    engine = create_engine(_postgres_url() or "")
    inspector = inspect(engine)
    indexes = {item["name"]: item for item in inspector.get_indexes("profile_active_bindings")}
    assert "uq_profile_active_binding_active_identity" in indexes
    index = indexes["uq_profile_active_binding_active_identity"]
    assert index["unique"] is True
    assert set(index["column_names"]) == {"profile_id", "instrument_symbol", "contract_code", "period"}


def test_sqlite_partial_unique_index_allows_multiple_superseded_rows() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as session:
        for data_version in ("v1", "v2"):
            session.add(
                ProfileActiveBinding(
                    profile_id="intraday_research_v1",
                    instrument_symbol="jm",
                    contract_code="jm.MAIN",
                    contract_role="dominant_main",
                    period="1d",
                    data_version=data_version,
                    market_data_file_id=None,
                    binding_status="superseded",
                )
            )
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="v3",
                market_data_file_id=None,
                binding_status="active",
            )
        )
        session.commit()

        bindings = session.query(ProfileActiveBinding).all()
        assert len(bindings) == 3
        assert sum(1 for item in bindings if item.binding_status == "superseded") == 2

        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="v4",
                market_data_file_id=None,
                binding_status="active",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.skipif(_postgres_url() is None, reason="DATABASE_URL with PostgreSQL is required")
def test_migration_0022_upgrade_and_downgrade_roundtrip() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("services/quant-api/alembic.ini")
    config.set_main_option("script_location", "services/quant-api/alembic")
    config.set_main_option("sqlalchemy.url", _postgres_url() or "")

    try:
        command.downgrade(config, "20260712_0021")
        command.upgrade(config, "20260712_0022")
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL migration roundtrip unavailable: {exc}")

    engine = create_engine(_postgres_url() or "")
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'profile_active_bindings'
                  AND indexname = 'uq_profile_active_binding_active_identity'
                """
            )
        ).fetchall()
        assert len(result) == 1

    try:
        command.downgrade(config, "20260712_0021")
        command.upgrade(config, "20260712_0022")
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL migration downgrade unavailable: {exc}")
