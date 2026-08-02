from __future__ import annotations

import os
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)
from app.models.live_review_loop import SignalDecision


REVISION = "20260802_0028"
PARENT_REVISION = "20260730_0027"
IDENTITY_REVISION = "20260802_0029"
IMMUTABLE_REVISION = "20260802_0030"
HEAD_REVISION = "20260802_0031"
QUANT_API_ROOT = Path(__file__).resolve().parents[2]
NEW_TABLES = {
    "live_observation_bars",
    "signal_decisions",
    "signal_decision_reconciliations",
    "research_samples",
    "retention_runs",
}


def test_live_review_loop_revisions_form_the_declared_head() -> None:
    config = Config("services/quant-api/alembic.ini")
    config.set_main_option("script_location", "services/quant-api/alembic")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(REVISION).down_revision == PARENT_REVISION
    assert scripts.get_revision(IDENTITY_REVISION).down_revision == REVISION
    assert scripts.get_revision(IMMUTABLE_REVISION).down_revision == IDENTITY_REVISION
    assert scripts.get_revision(HEAD_REVISION).down_revision == IMMUTABLE_REVISION


def test_live_review_loop_offline_sql_contains_additive_schema_and_downgrade_guard() -> None:
    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.upgrade(config, f"{PARENT_REVISION}:{REVISION}", sql=True)
    sql = output.getvalue()

    assert "CREATE TABLE live_observation_bars" in sql
    assert "CREATE TABLE signal_decisions" in sql
    assert "ADD COLUMN decision_id" in sql

    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.downgrade(config, f"{REVISION}:{PARENT_REVISION}", sql=True)
    assert "Task 06 clean-start tables must be empty before downgrade" in output.getvalue()


def test_live_identity_revision_offline_sql_replaces_unique_constraint_with_guard() -> None:
    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.upgrade(config, f"{REVISION}:{IDENTITY_REVISION}", sql=True)
    sql = output.getvalue()

    assert "revision, confirmed" in sql

    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.downgrade(config, f"{IDENTITY_REVISION}:{REVISION}", sql=True)
    assert "live observation revisions must be collapsed" in output.getvalue()


def test_signal_decision_immutable_trigger_is_in_offline_sql() -> None:
    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.upgrade(config, f"{IDENTITY_REVISION}:{IMMUTABLE_REVISION}", sql=True)

    sql = output.getvalue()
    assert "CREATE TRIGGER trg_signal_decisions_immutable" in sql
    assert "SIGNAL_DECISION_IMMUTABLE" in sql


def test_provider_final_lineage_columns_and_downgrade_guard_are_in_offline_sql() -> None:
    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.upgrade(config, f"{IMMUTABLE_REVISION}:{HEAD_REVISION}", sql=True)
    sql = output.getvalue()
    assert "provider_data_version" in sql
    assert "provider_request_digest" in sql

    output = StringIO()
    config = Config(str(QUANT_API_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    command.downgrade(config, f"{HEAD_REVISION}:{IMMUTABLE_REVISION}", sql=True)
    assert "signal decision reconciliations must be empty" in output.getvalue()


def test_isolated_postgres_upgrade_downgrade_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip()
    if not configured:
        pytest.skip("GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required")
    try:
        url = require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert NEW_TABLES <= set(inspector.get_table_names())
        assert "decision_id" in {column["name"] for column in inspector.get_columns("signal_events")}
        reconciliation_columns = {
            column["name"]
            for column in inspector.get_columns("signal_decision_reconciliations")
        }
        assert {"provider_data_version", "provider_request_digest"} <= reconciliation_columns
        with engine.connect() as connection:
            trigger_count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM pg_trigger WHERE tgname = 'trg_signal_decisions_immutable'"
            ).scalar_one()
        assert trigger_count == 1
        with engine.begin() as connection:
            decision_id = connection.execute(
                SignalDecision.__table__.insert()
                .values(
                    decision_key="1" * 64,
                    decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
                    trading_day=date(2026, 8, 3),
                    bar_end=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
                    provider="rqdata",
                    source_mode="session_aggregate_15m_v2",
                    actual_contract="JM2609",
                    strategy_code="task06_causal_test_observation",
                    strategy_version="v1.0",
                    policy_id="task06_causal_confirmed_close_test_v1",
                    parameter_digest="2" * 64,
                    input_schema_version="strategy_input_v1",
                    input_window_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
                    input_window_end=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
                    dataset_key={"provider": "rqdata"},
                    manifest_digest="3" * 64,
                    input_snapshot={},
                    input_digest="4" * 64,
                    fingerprint_recipe_version="strategy_fingerprint_v1",
                    fingerprint="5" * 64,
                    result_kind="no_signal",
                    direction=None,
                    result_payload={},
                    result_digest="6" * 64,
                    created_at=datetime.now(UTC),
                )
                .returning(SignalDecision.id)
            ).scalar_one()
        try:
            with pytest.raises(DBAPIError, match="SIGNAL_DECISION_IMMUTABLE"):
                with engine.begin() as connection:
                    connection.execute(
                        text("UPDATE signal_decisions SET result_kind = 'signal' WHERE id = :id"),
                        {"id": decision_id},
                    )
        finally:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM signal_decisions WHERE id = :id"),
                    {"id": decision_id},
                )

        command.downgrade(config, PARENT_REVISION)
        inspector.clear_cache()
        assert not (NEW_TABLES & set(inspector.get_table_names()))

        command.upgrade(config, "head")
        inspector.clear_cache()
        assert NEW_TABLES <= set(inspector.get_table_names())
    finally:
        command.upgrade(config, "head")
        engine.dispose()
