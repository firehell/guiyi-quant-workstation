from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    QUANT_API_ROOT
    / "alembic/versions/20260819_0040_alert_notification_attempts.py"
)


def test_attempt_migration_is_additive_and_declares_the_next_revision() -> None:
    """A non-additive ledger migration could rewrite existing alert facts."""

    migration = _load_migration()

    assert migration.revision == "20260819_0040"
    assert migration.down_revision == "20260815_0039"
    recorder = _RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert recorder.created_tables == ["alert_notification_attempts"]
    assert recorder.created_indexes == [
        ("ix_alert_notification_attempts_event_id", ("event_id",)),
        (
            "ix_alert_notification_attempts_status_attempted_at",
            ("status", "attempted_at"),
        ),
    ]
    assert recorder.forbidden_operations == []


def test_attempt_migration_downgrade_drops_only_the_new_ledger() -> None:
    """A downgrade must not alter either pre-existing Alert application table."""

    migration = _load_migration()
    recorder = _RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    assert recorder.dropped_tables == ["alert_notification_attempts"]


@pytest.fixture
def isolated_migration_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Config, Engine]]:
    configured_url = os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip()
    if not configured_url:
        pytest.skip("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url, pool_pre_ping=True)
    _reset_public_schema(engine)
    try:
        yield config, engine
    finally:
        _reset_public_schema(engine)
        engine.dispose()


def test_upgrade_from_execution_review_to_head_creates_attempt_ledger(
    isolated_migration_context: tuple[Config, Engine],
) -> None:
    """The migration must preserve existing events and enforce recipient identity."""

    config, engine = isolated_migration_context
    command.upgrade(config, "20260815_0039")
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    with engine.begin() as connection:
        event_id = _seed_event(connection, now)

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "alert_notification_attempts" in inspector.get_table_names()
    assert "notification_attempted_at" in {
        column["name"] for column in inspector.get_columns("alert_events")
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("alert_notification_attempts")
    } == {"uq_alert_notification_attempts_event_alias_channel"}
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("alert_notification_attempts")
    } == {
        "ck_alert_notification_attempts_status",
        "ck_alert_notification_attempts_completion",
    }
    assert {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("alert_notification_attempts")
        if not index.get("duplicates_constraint")
    } == {
        "ix_alert_notification_attempts_event_id": ("event_id",),
        "ix_alert_notification_attempts_status_attempted_at": (
            "status",
            "attempted_at",
        ),
    }
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT count(*) FROM alert_notification_attempts WHERE event_id = :event_id"
            ),
            {"event_id": event_id},
        ).scalar_one() == 0

    _insert_attempt(
        engine,
        event_id,
        recipient_alias="owner-started",
        status="STARTED",
        now=now,
    )
    _insert_attempt(
        engine,
        event_id,
        recipient_alias="owner-accepted",
        status="PROVIDER_ACCEPTED",
        now=now,
        completed_at=now,
    )
    _insert_attempt(
        engine,
        event_id,
        recipient_alias="owner-failed",
        status="FAILED",
        now=now,
        completed_at=now,
        error_code="PROVIDER_TIMEOUT",
    )

    invalid_attempts = (
        {
            "recipient_alias": "unknown-status",
            "status": "RETRYING",
            "completed_at": None,
            "error_code": None,
            "constraint": "ck_alert_notification_attempts_status",
        },
        {
            "recipient_alias": "started-completed",
            "status": "STARTED",
            "completed_at": now,
            "error_code": None,
            "constraint": "ck_alert_notification_attempts_completion",
        },
        {
            "recipient_alias": "accepted-open",
            "status": "PROVIDER_ACCEPTED",
            "completed_at": None,
            "error_code": None,
            "constraint": "ck_alert_notification_attempts_completion",
        },
        {
            "recipient_alias": "failed-without-error",
            "status": "FAILED",
            "completed_at": now,
            "error_code": None,
            "constraint": "ck_alert_notification_attempts_completion",
        },
    )
    for attempt in invalid_attempts:
        with pytest.raises(IntegrityError) as exc_info:
            _insert_attempt(
                engine,
                event_id,
                recipient_alias=attempt["recipient_alias"],
                status=attempt["status"],
                now=now,
                completed_at=attempt["completed_at"],
                error_code=attempt["error_code"],
            )
        constraint_name = exc_info.value.orig.diag.constraint_name
        if attempt["constraint"] == "ck_alert_notification_attempts_status":
            assert constraint_name in {
                "ck_alert_notification_attempts_status",
                "ck_alert_notification_attempts_completion",
            }
        else:
            assert constraint_name == attempt["constraint"]

    with pytest.raises(IntegrityError) as exc_info:
        _insert_attempt(
            engine,
            event_id,
            recipient_alias="owner-started",
            status="STARTED",
            now=now,
        )
    assert (
        exc_info.value.orig.diag.constraint_name
        == "uq_alert_notification_attempts_event_alias_channel"
    )


def _load_migration() -> ModuleType:
    assert MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "alert_notification_attempts_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


class _RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_indexes: list[tuple[str, tuple[str, ...]]] = []
        self.dropped_tables: list[str] = []
        self.forbidden_operations: list[str] = []

    def create_table(self, table_name: str, *_: object) -> None:
        self.created_tables.append(table_name)

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
    ) -> None:
        assert table_name == "alert_notification_attempts"
        self.created_indexes.append((index_name, tuple(columns)))

    def bulk_insert(self, *_: object) -> None:
        self.forbidden_operations.append("bulk_insert")

    def add_column(self, *_: object) -> None:
        self.forbidden_operations.append("add_column")

    def alter_column(self, *_: object) -> None:
        self.forbidden_operations.append("alter_column")

    def create_check_constraint(self, *_: object) -> None:
        self.forbidden_operations.append("create_check_constraint")

    def create_unique_constraint(self, *_: object) -> None:
        self.forbidden_operations.append("create_unique_constraint")

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)


def _reset_public_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")


def _seed_event(connection: Any, now: datetime) -> int:
    rule_id = connection.execute(
        text(
            """
            INSERT INTO alert_rules (
                rule_code, enabled, scope_products, created_at, updated_at
            ) VALUES (
                'notification_attempt_migration_test', false, '{}', :now, :now
            ) RETURNING id
            """
        ),
        {"now": now},
    ).scalar_one()
    return connection.execute(
        text(
            """
            INSERT INTO alert_events (
                rule_id, symbol, contract, frequency, bar_end, result_codes,
                detected_at, notification_attempted_at, created_at,
                trading_day, lower_tf_confirmation
            ) VALUES (
                :rule_id, 'jm', 'JM2701', '15m', :now, ARRAY['buy'],
                :now, NULL, :now, DATE '2026-08-19', false
            ) RETURNING id
            """
        ),
        {"rule_id": rule_id, "now": now},
    ).scalar_one()


def _insert_attempt(
    engine: Engine,
    event_id: int,
    *,
    recipient_alias: str,
    status: str,
    now: datetime,
    completed_at: datetime | None = None,
    error_code: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO alert_notification_attempts (
                    event_id, recipient_alias, channel, status, attempted_at,
                    completed_at, error_code, created_at, updated_at
                ) VALUES (
                    :event_id, :recipient_alias, 'clawbot-openclaw-weixin',
                    :status, :now, :completed_at, :error_code, :now, :now
                )
                """
            ),
            {
                "event_id": event_id,
                "recipient_alias": recipient_alias,
                "status": status,
                "now": now,
                "completed_at": completed_at,
                "error_code": error_code,
            },
        )
