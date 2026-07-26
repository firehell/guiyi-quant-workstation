from __future__ import annotations

import pytest

from app.db.migration_test_guard import (
    DatabaseIdentity,
    MigrationTestDatabaseSafetyError,
    require_isolated_migration_database_url,
)


def test_requires_explicit_isolated_migration_database_url() -> None:
    with pytest.raises(
        MigrationTestDatabaseSafetyError,
        match="GUIYI_ISOLATED_MIGRATION_DATABASE_URL",
    ):
        require_isolated_migration_database_url(
            {
                "DATABASE_URL": "postgresql+psycopg://user:secret@db.example/guiyi_quant",
            },
            identity_probe=lambda _url: DatabaseIdentity(database="unused", oid=0),
        )


def test_rejects_isolated_url_without_test_database_name() -> None:
    with pytest.raises(MigrationTestDatabaseSafetyError, match="isolated/test database"):
        require_isolated_migration_database_url(
            {
                "GUIYI_ISOLATED_MIGRATION_DATABASE_URL": (
                    "postgresql+psycopg://user:secret@db.example/guiyi_quant"
                ),
            },
            identity_probe=lambda _url: DatabaseIdentity(database="guiyi_quant", oid=16384),
        )


def test_rejects_runtime_database_even_when_url_uses_test_alias() -> None:
    identities = iter(
        (
            DatabaseIdentity(database="guiyi_quant_test", oid=16384),
            DatabaseIdentity(database="guiyi_quant", oid=16384),
        )
    )

    with pytest.raises(MigrationTestDatabaseSafetyError, match="same PostgreSQL database OID"):
        require_isolated_migration_database_url(
            {
                "GUIYI_ISOLATED_MIGRATION_DATABASE_URL": (
                    "postgresql+psycopg://user:secret@db.example/guiyi_quant_test"
                ),
                "DATABASE_URL": "postgresql+psycopg://user:secret@db.example/guiyi_quant",
            },
            identity_probe=lambda _url: next(identities),
        )


def test_accepts_distinct_isolated_database_identity() -> None:
    target = "postgresql+psycopg://user:secret@db.example/guiyi_quant_test"
    identities = iter(
        (
            DatabaseIdentity(database="guiyi_quant_test", oid=24576),
            DatabaseIdentity(database="guiyi_quant", oid=16384),
        )
    )

    assert (
        require_isolated_migration_database_url(
            {
                "GUIYI_ISOLATED_MIGRATION_DATABASE_URL": target,
                "DATABASE_URL": "postgresql+psycopg://user:secret@db.example/guiyi_quant",
            },
            identity_probe=lambda _url: next(identities),
        )
        == target
    )
