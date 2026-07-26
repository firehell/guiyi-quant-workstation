from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


class MigrationTestDatabaseSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseIdentity:
    database: str
    oid: int


def probe_database_identity(database_url: str) -> DatabaseIdentity:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT current_database(), oid
                    FROM pg_database
                    WHERE datname = current_database()
                    """
                )
            ).one()
        return DatabaseIdentity(database=str(row[0]), oid=int(row[1]))
    finally:
        engine.dispose()


def _is_isolated_name(database: str) -> bool:
    lowered = database.lower()
    return "test" in lowered or "isolated" in lowered


def require_isolated_migration_database_url(
    environment: Mapping[str, str],
    *,
    identity_probe: Callable[[str], DatabaseIdentity],
) -> str:
    target_url = environment.get("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip()
    if not target_url:
        raise MigrationTestDatabaseSafetyError(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required"
        )

    parsed_target = make_url(target_url)
    if not parsed_target.drivername.startswith("postgresql"):
        raise MigrationTestDatabaseSafetyError(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL must use PostgreSQL"
        )
    target_name = parsed_target.database or ""
    if not _is_isolated_name(target_name):
        raise MigrationTestDatabaseSafetyError(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL must name an isolated/test database"
        )

    runtime_url = environment.get("DATABASE_URL", "").strip()
    if runtime_url and make_url(runtime_url) == parsed_target:
        raise MigrationTestDatabaseSafetyError(
            "isolated migration URL must not equal DATABASE_URL"
        )

    target_identity = identity_probe(target_url)
    if not _is_isolated_name(target_identity.database):
        raise MigrationTestDatabaseSafetyError(
            "connected database must be an isolated/test database"
        )

    if runtime_url:
        runtime_identity = identity_probe(runtime_url)
        if target_identity.oid == runtime_identity.oid:
            raise MigrationTestDatabaseSafetyError(
                "isolated migration target has the same PostgreSQL database OID as DATABASE_URL"
            )
        if target_identity.database == runtime_identity.database:
            raise MigrationTestDatabaseSafetyError(
                "isolated migration target resolves to the DATABASE_URL database"
            )

    return target_url
