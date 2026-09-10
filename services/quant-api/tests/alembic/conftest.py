from __future__ import annotations

from collections.abc import Iterator
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


@pytest.fixture
def isolated_postgres_engine() -> Iterator[Engine]:
    if not os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip():
        pytest.skip("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
