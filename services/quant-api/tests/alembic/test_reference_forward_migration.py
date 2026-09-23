from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.reference_trading.repository import ReferenceRepository


ROOT = Path(__file__).resolve().parents[2]


def _migration(name: str):
    path = ROOT / "alembic/versions" / name
    spec = importlib.util.spec_from_file_location(f"reference_migration_{uuid4().hex}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_forward_migration_follows_reference_tables() -> None:
    migration = _migration("20260923_0048_reference_forward.py")
    assert migration.revision == "20260923_0048"
    assert migration.down_revision == "20260919_0047"


@pytest.mark.isolated_postgresql
def test_forward_migration_adds_default_off_capture_schema(isolated_postgres_engine: Engine) -> None:
    schema = "reference_forward_" + uuid4().hex
    old = _migration("20260919_0047_reference_trading.py")
    new = _migration("20260923_0048_reference_forward.py")
    try:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            operations = Operations(MigrationContext.configure(connection))
            old.op = operations
            old.upgrade()
            new.op = operations
            new.upgrade()
        inspector = inspect(isolated_postgres_engine)
        assert {
            "reference_activation_receipts", "reference_capture_reconciliations",
        } <= set(inspector.get_table_names(schema=schema))
        stream_columns = {
            column["name"]: column
            for column in inspector.get_columns("reference_streams", schema=schema)
        }
        assert stream_columns["activation_generation"]["default"] in {"0", "'0'::bigint"}
        assert "recording_start" in stream_columns
        batch_columns = {
            column["name"] for column in inspector.get_columns("reference_batches", schema=schema)
        }
        assert "consumed_by_batch_id" in batch_columns
        checks = {
            item["name"]: item["sqltext"]
            for item in inspector.get_check_constraints("reference_batches", schema=schema)
        }
        assert "capture" in checks["ck_reference_batches_kind_seq"]
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            for stream_id, product, mode, enabled in (
                ("forward-lower", "rb", "forward_observation", True),
                ("forward-upper", "RB", "forward_observation", True),
                ("forward-disabled", "rb", "forward_observation", False),
                ("historical", "rb", "historical_replay", True),
            ):
                connection.execute(text("""
                    INSERT INTO reference_streams (
                        stream_id, identity_hash, strategy_code, formula_versions,
                        profile_id, reference_model_version, futures_adaptation_version,
                        product, frequency, series_kind, recording_mode,
                        observation_policy_version, enabled
                    ) VALUES (
                        :stream_id, :stream_id, 'test', CAST('["f1"]' AS jsonb),
                        'p1', 'r1', 'a1', :product, '60m', 'actual_dominant',
                        :mode, :policy, :enabled
                    )
                """), {
                    "stream_id": stream_id, "product": product, "mode": mode,
                    "policy": "o1" if mode == "forward_observation" else None,
                    "enabled": enabled,
                })
            repository = ReferenceRepository(lambda: Session(connection))
            assert repository.enabled_forward_routes("rb", "60m") == (
                "forward-lower", "forward-upper",
            )
            assert repository.enabled_forward_routes("cu", "60m") == ()
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
