from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    QUANT_API_ROOT / "alembic/versions/20260902_0043_retire_subing.py"
)
PREVIOUS_MIGRATION_PATH = (
    QUANT_API_ROOT / "alembic/versions/20260826_0042_subing_strategy_alert.py"
)
SUPPORT_PATH = Path(__file__).with_name(
    "test_subing_strategy_alert_migration.py"
)


def test_migration_is_forward_only_from_exact_0042_parent() -> None:
    migration = _load_module(MIGRATION_PATH)
    assert migration.revision == "20260902_0043"
    assert migration.down_revision == "20260826_0042"
    with pytest.raises(
        RuntimeError,
        match="^SUBING_RETIREMENT_DOWNGRADE_UNSUPPORTED$",
    ):
        migration.downgrade()


def test_htdy_validators_accept_only_preservable_facts() -> None:
    migration = _load_module(MIGRATION_PATH)
    now = datetime(2026, 9, 2, tzinfo=UTC)
    rule = {
        "enabled": True,
        "scope_products": [],
        "scope_product_frequencies": {"jm": ["5m", "15m"]},
        "created_at": now,
        "updated_at": now,
    }
    event = {
        "symbol": "jm",
        "contract": "JM2609",
        "trading_day": date(2026, 9, 2),
        "frequency": "15m",
        "bar_end": now,
        "result_codes": ["buy"],
        "detected_at": now,
        "notification_attempted_at": None,
    }
    assert migration._valid_htdy_rule(rule) is True
    assert migration._valid_htdy_event(event) is True
    assert migration._valid_htdy_rule({
        **rule, "scope_product_frequencies": {"JM": ["15m"]}
    }) is False
    assert migration._valid_htdy_event({
        **event, "result_codes": ["close_long"]
    }) is False


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


@pytest.mark.isolated_postgresql
def test_upgrade_deletes_retired_facts_and_preserves_htdy_exactly(
    isolated_postgres_engine: Engine,
) -> None:
    support = _load_module(SUPPORT_PATH)
    schema = support._prepared_0041_schema(isolated_postgres_engine)
    try:
        with isolated_postgres_engine.begin() as connection:
            support._search_path(connection, schema)
            support._seed_realistic_0041_state(connection)
        support._run_upgrade(
            isolated_postgres_engine, schema, PREVIOUS_MIGRATION_PATH
        )
        with isolated_postgres_engine.begin() as connection:
            support._search_path(connection, schema)
            connection.execute(text(
                "UPDATE alembic_version SET version_num = '20260826_0042'"
            ))
            retired_id = connection.scalar(text(
                "SELECT id FROM alert_rules "
                "WHERE rule_code = 'subing_strategy_v1'"
            ))
            support._insert_strategy_event(connection, retired_id, "action-1")
            htdy_before = connection.execute(text(
                "SELECT id, rule_code, enabled, scope_product_frequencies, "
                "created_at, updated_at FROM alert_rules "
                "WHERE rule_code = 'htdy_original_15m'"
            )).mappings().one()
            htdy_events_before = support._htdy_rows(connection)

        migration = _load_module(MIGRATION_PATH)
        with isolated_postgres_engine.begin() as connection:
            support._search_path(connection, schema)
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            rules = connection.execute(text(
                "SELECT id, rule_code, enabled, scope_product_frequencies, "
                "created_at, updated_at FROM alert_rules"
            )).mappings().all()
            assert [dict(row) for row in rules] == [dict(htdy_before)]
            assert support._htdy_rows(connection) == htdy_events_before
            assert connection.scalar(text("SELECT COUNT(*) FROM alert_events")) == (
                len(htdy_events_before)
            )
            assert {
                column["name"]
                for column in sa_inspect(connection).get_columns("alert_rules")
            } == {
                "id", "rule_code", "enabled", "scope_product_frequencies",
                "created_at", "updated_at",
            }
            assert {
                column["name"]
                for column in sa_inspect(connection).get_columns("alert_events")
            } == {
                "id", "rule_id", "symbol", "contract", "trading_day",
                "frequency", "bar_end", "result_codes", "detected_at",
                "notification_attempted_at", "created_at",
            }
    finally:
        support._drop_schema(isolated_postgres_engine, schema)


def _load_module(path: Path) -> ModuleType:
    assert path.exists(), f"missing file: {path.name}"
    spec = importlib.util.spec_from_file_location(
        f"retirement_{path.stem}_{uuid4().hex}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
