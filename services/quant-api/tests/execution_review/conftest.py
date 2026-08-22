from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


@pytest.fixture
def postgres_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip():
        pytest.fail("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url, pool_pre_ping=True)
    config = Config()
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    _reset_postgres(engine)
    alembic_command.upgrade(config, "20260815_0039")
    try:
        yield engine
    finally:
        _reset_postgres(engine)
        engine.dispose()


def _reset_postgres(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
