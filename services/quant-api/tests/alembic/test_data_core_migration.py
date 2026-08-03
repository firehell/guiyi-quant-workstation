from __future__ import annotations

import os
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.db.migration_test_guard import (
    DatabaseIdentity,
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


LEGACY_PARENT_REVISION = "20260721_0025"
PARENT_REVISION = "20260730_0026"
REVISION = "20260730_0027"
LIVE_REVIEW_REVISION = "20260802_0028"
LIVE_IDENTITY_REVISION = "20260802_0029"
LIVE_IMMUTABLE_REVISION = "20260802_0030"
EOD_LINEAGE_REVISION = "20260802_0031"
HEAD_REVISION = "20260803_0032"
NEW_TABLES = {"market_datasets", "market_partitions", "data_gaps"}
CANONICAL_VIEW = "data_core_main_contract_map"
QUANT_API_ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 64
SHA_B = "b" * 64


def _isolated_postgres_url() -> str | None:
    configured_url = os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", "").strip()
    if not configured_url:
        return None
    try:
        return require_isolated_migration_database_url(
            os.environ,
            identity_probe=probe_database_identity,
        )
    except MigrationTestDatabaseSafetyError as exc:
        pytest.fail(str(exc))


def test_isolated_url_guard_compares_runtime_database_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_url = (
        "postgresql+psycopg://test:test@127.0.0.1:59999/"
        "guiyi_quant_isolated_test"
    )
    runtime_url = (
        "postgresql+psycopg://runtime:runtime@127.0.0.1:59998/"
        "guiyi_quant_runtime"
    )
    probed_urls: list[str] = []

    def fake_identity_probe(database_url: str) -> DatabaseIdentity:
        probed_urls.append(database_url)
        if database_url == isolated_url:
            return DatabaseIdentity(database="guiyi_quant_isolated_test", oid=101)
        if database_url == runtime_url:
            return DatabaseIdentity(database="guiyi_quant_runtime", oid=202)
        raise AssertionError(f"unexpected probe target: {database_url}")

    monkeypatch.setenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL", isolated_url)
    monkeypatch.setenv("DATABASE_URL", runtime_url)
    monkeypatch.setattr(
        f"{__name__}.probe_database_identity",
        fake_identity_probe,
    )

    assert _isolated_postgres_url() == isolated_url
    assert probed_urls == [isolated_url, runtime_url]


def test_contract_alignment_revision_precedes_live_review_loop_head() -> None:
    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(REVISION).down_revision == PARENT_REVISION
    assert scripts.get_revision(LIVE_REVIEW_REVISION).down_revision == REVISION
    assert scripts.get_revision(LIVE_IDENTITY_REVISION).down_revision == LIVE_REVIEW_REVISION
    assert scripts.get_revision(LIVE_IMMUTABLE_REVISION).down_revision == LIVE_IDENTITY_REVISION
    assert scripts.get_revision(EOD_LINEAGE_REVISION).down_revision == LIVE_IMMUTABLE_REVISION
    assert scripts.get_revision(HEAD_REVISION).down_revision == EOD_LINEAGE_REVISION


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_0032_offline_sql_replaces_frequency_check_with_fail_closed_guard(
    direction: str,
) -> None:
    output = StringIO()
    config = Config(
        str(QUANT_API_ROOT / "alembic.ini"),
        output_buffer=output,
    )
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))

    if direction == "upgrade":
        command.upgrade(
            config,
            f"{EOD_LINEAGE_REVISION}:{HEAD_REVISION}",
            sql=True,
        )
    else:
        command.downgrade(
            config,
            f"{HEAD_REVISION}:{EOD_LINEAGE_REVISION}",
            sql=True,
        )

    generated_sql = output.getvalue()
    assert "LOCK TABLE market_datasets IN ACCESS EXCLUSIVE MODE" in generated_sql
    assert "ck_market_datasets_frequency" in generated_sql
    assert "ck_market_datasets_actual_dominant_weekly" not in generated_sql
    if direction == "upgrade":
        assert "'5m', '15m', '30m', '60m'" in generated_sql
    else:
        assert "persisted aggregate market_datasets block 20260803_0032 downgrade" in generated_sql


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_contract_alignment_offline_sql_contains_lock_guard_and_schema_ddl(
    direction: str,
) -> None:
    output = StringIO()
    config = Config(
        str(QUANT_API_ROOT / "alembic.ini"),
        output_buffer=output,
    )
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))

    if direction == "upgrade":
        command.upgrade(
            config,
            f"{PARENT_REVISION}:{REVISION}",
            sql=True,
        )
        expected_ddl = "CREATE VIEW data_core_main_contract_map AS"
    else:
        command.downgrade(
            config,
            f"{REVISION}:{PARENT_REVISION}",
            sql=True,
        )
        expected_ddl = "DROP VIEW data_core_main_contract_map"

    generated_sql = output.getvalue()
    assert "LOCK TABLE market_datasets IN ACCESS EXCLUSIVE MODE" in generated_sql
    assert "DO $$" in generated_sql
    assert (
        f"market_datasets must be empty before {REVISION} {direction}"
        in generated_sql
    )
    assert expected_ddl in generated_sql


@pytest.fixture
def migration_context(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, Config, Engine]:
    url = _isolated_postgres_url()
    if url is None:
        pytest.skip(
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL with isolated PostgreSQL is required"
        )

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield url, config, engine
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def test_isolated_database_is_postgresql_16(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, _, engine = migration_context
    with engine.connect() as connection:
        server_version_num = int(
            connection.execute(text("SHOW server_version_num")).scalar_one()
        )
    assert 160000 <= server_version_num < 170000


def _insert_dataset(
    engine: Engine,
    *,
    provider: str = "rqdata",
    dataset_kind: str = "actual_dominant",
    symbol: str = "jm",
    contract_or_series: str = "JM2609",
    frequency: str = "1m",
    adjustment: str = "none",
    schema_version: str = "v1",
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO market_datasets (
                        provider,
                        dataset_kind,
                        symbol,
                        contract_or_series,
                        frequency,
                        adjustment,
                        schema_version,
                        created_at
                    )
                    VALUES (
                        :provider,
                        :dataset_kind,
                        :symbol,
                        :contract_or_series,
                        :frequency,
                        :adjustment,
                        :schema_version,
                        now()
                    )
                    RETURNING id
                    """
                ),
                {
                    "provider": provider,
                    "dataset_kind": dataset_kind,
                    "symbol": symbol,
                    "contract_or_series": contract_or_series,
                    "frequency": frequency,
                    "adjustment": adjustment,
                    "schema_version": schema_version,
                },
            ).scalar_one()
        )


def _insert_legacy_dataset(engine: Engine) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO market_datasets (
                        provider,
                        data_type,
                        instrument_symbol,
                        contract_code,
                        period,
                        created_at
                    )
                    VALUES (
                        'rqdata',
                        'future_bar',
                        'jm',
                        'JM2609',
                        '1m',
                        now()
                    )
                    RETURNING id
                    """
                )
            ).scalar_one()
        )


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )


def _dataset_schema_snapshot(engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    return {
        "columns": tuple(
            sorted(column["name"] for column in inspector.get_columns("market_datasets"))
        ),
        "constraints": _constraint_map(engine, "market_datasets"),
        "views": tuple(sorted(inspector.get_view_names())),
    }


def _clear_data_core_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM data_gaps"))
        connection.execute(text("DELETE FROM market_partitions"))
        connection.execute(text("DELETE FROM market_datasets"))


def _partition_values(
    dataset_id: int,
    *,
    coverage_start: str = "2026-07-30T01:00:00+00:00",
    coverage_end: str = "2026-07-30T02:00:00+00:00",
    manifest_version: str = "manifest-v1",
    manifest_uri: str = "manifest://jm2609/manifest-v1",
    manifest_digest: str = SHA_A,
    file_uri: str = "parquet://jm2609/part-v1.parquet",
    checksum: str = SHA_B,
    row_count: int = 60,
    overlap_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "manifest_version": manifest_version,
        "manifest_uri": manifest_uri,
        "manifest_digest": manifest_digest,
        "file_uri": file_uri,
        "checksum": checksum,
        "row_count": row_count,
        "overlap_reason": overlap_reason,
    }


def _insert_partition(engine: Engine, values: dict[str, Any]) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO market_partitions (
                        dataset_id,
                        coverage_start,
                        coverage_end,
                        manifest_version,
                        manifest_uri,
                        manifest_digest,
                        file_uri,
                        checksum,
                        row_count,
                        overlap_reason,
                        created_at
                    )
                    VALUES (
                        :dataset_id,
                        :coverage_start,
                        :coverage_end,
                        :manifest_version,
                        :manifest_uri,
                        :manifest_digest,
                        :file_uri,
                        :checksum,
                        :row_count,
                        :overlap_reason,
                        now()
                    )
                    RETURNING id
                    """
                ),
                values,
            ).scalar_one()
        )


def _constraint_map(engine: Engine, table_name: str) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT constraint_name, constraint_type
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
        return {str(name): str(kind) for name, kind in rows}


def test_0032_upgrade_accepts_seven_frequencies_and_rejects_unknown(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)

    for frequency in ("1m", "5m", "15m", "30m", "60m", "1d", "1w"):
        _insert_dataset(
            engine,
            dataset_kind="continuous",
            contract_or_series="JM.MAIN",
            frequency=frequency,
        )
    with pytest.raises(SQLAlchemyError):
        _insert_dataset(
            engine,
            dataset_kind="continuous",
            contract_or_series="JM.MAIN",
            frequency="2m",
        )
    with pytest.raises(SQLAlchemyError):
        _insert_dataset(engine, frequency="1w")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM market_datasets")
        ).scalar_one() == 7
    _clear_data_core_rows(engine)


def test_0032_downgrade_succeeds_when_no_aggregate_rows_exist(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)

    command.downgrade(config, EOD_LINEAGE_REVISION)

    assert _revision(engine) == EOD_LINEAGE_REVISION
    constraints = _constraint_map(engine, "market_datasets")
    assert "ck_market_datasets_frequency" not in constraints
    assert "ck_market_datasets_actual_dominant_weekly" not in constraints
    assert constraints["ck_market_datasets_direct_frequency"] == "CHECK"
    command.upgrade(config, "head")


def test_0032_upgrade_fails_closed_when_actual_weekly_row_preexists(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)
    command.downgrade(config, EOD_LINEAGE_REVISION)
    dataset_id = _insert_dataset(engine, frequency="1w")
    before = _dataset_schema_snapshot(engine)

    with pytest.raises(SQLAlchemyError):
        command.upgrade(config, "head")

    assert _revision(engine) == EOD_LINEAGE_REVISION
    assert _dataset_schema_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT frequency FROM market_datasets WHERE id = :dataset_id"),
            {"dataset_id": dataset_id},
        ).scalar_one() == "1w"
    _clear_data_core_rows(engine)
    command.upgrade(config, "head")


@pytest.mark.parametrize("frequency", ["5m", "15m", "30m", "60m"])
def test_0032_downgrade_fails_closed_when_aggregate_row_exists(
    migration_context: tuple[str, Config, Engine],
    frequency: str,
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)
    dataset_id = _insert_dataset(engine, frequency=frequency)
    before = _dataset_schema_snapshot(engine)

    with pytest.raises(
        SQLAlchemyError,
        match="persisted aggregate market_datasets block 20260803_0032 downgrade",
    ):
        command.downgrade(config, EOD_LINEAGE_REVISION)

    assert _revision(engine) == HEAD_REVISION
    assert _dataset_schema_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT frequency FROM market_datasets WHERE id = :dataset_id"),
            {"dataset_id": dataset_id},
        ).scalar_one() == frequency
    _clear_data_core_rows(engine)


def _snapshot_rows(engine: Engine, table_name: str, marker_column: str) -> list[tuple]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    f"""
                    SELECT *
                    FROM {table_name}
                    WHERE {marker_column} LIKE 'task2-migration-%'
                    ORDER BY id
                    """
                )
            )
        ]


def test_empty_database_roundtrip_preserves_worktree_sentinel(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    sentinel = QUANT_API_ROOT / ".task2-data-core-migration-sentinel"
    sentinel_bytes = b"schema-only migration must not touch filesystem assets\n"
    sentinel.write_bytes(sentinel_bytes)

    try:
        command.upgrade(config, "head")
        _clear_data_core_rows(engine)
        command.downgrade(config, "base")
        assert sentinel.read_bytes() == sentinel_bytes
        command.upgrade(config, "head")
        assert sentinel.read_bytes() == sentinel_bytes
        command.downgrade(config, LEGACY_PARENT_REVISION)
        assert sentinel.read_bytes() == sentinel_bytes
        parent_tables = set(inspect(engine).get_table_names())
        assert NEW_TABLES.isdisjoint(parent_tables)
        assert {
            "main_contract_map",
            "data_profiles",
            "profile_active_bindings",
        } <= parent_tables
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_proc
                        WHERE proname = 'reject_market_partition_fact_updates'
                        """
                    )
                ).scalar_one()
                == 0
            )
        command.upgrade(config, "head")
        assert sentinel.read_bytes() == sentinel_bytes
    finally:
        sentinel.unlink(missing_ok=True)


def test_empty_0027_upgrade_downgrade_upgrade_roundtrip(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)
    command.downgrade(config, PARENT_REVISION)

    parent_snapshot = _dataset_schema_snapshot(engine)
    assert _revision(engine) == PARENT_REVISION
    assert CANONICAL_VIEW not in parent_snapshot["views"]

    command.upgrade(config, "head")
    assert _revision(engine) == HEAD_REVISION
    assert CANONICAL_VIEW in inspect(engine).get_view_names()

    command.downgrade(config, PARENT_REVISION)
    assert _revision(engine) == PARENT_REVISION
    assert _dataset_schema_snapshot(engine) == parent_snapshot

    command.upgrade(config, "head")
    assert _revision(engine) == HEAD_REVISION


def test_0027_upgrade_fails_closed_without_partial_schema_change_when_nonempty(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)
    command.downgrade(config, PARENT_REVISION)
    _insert_legacy_dataset(engine)
    before = _dataset_schema_snapshot(engine)

    with pytest.raises(
        SQLAlchemyError,
        match="market_datasets must be empty before 20260730_0027 upgrade",
    ):
        command.upgrade(config, "head")

    assert _revision(engine) == PARENT_REVISION
    assert _dataset_schema_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM market_datasets")
        ).scalar_one() == 1

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM market_datasets"))
    command.upgrade(config, "head")


def test_0027_downgrade_fails_closed_without_partial_schema_change_when_nonempty(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)
    dataset_id = _insert_dataset(engine)
    before = _dataset_schema_snapshot(engine)

    with pytest.raises(
        SQLAlchemyError,
        match="market_datasets must be empty before 20260730_0027 downgrade",
    ):
        command.downgrade(config, PARENT_REVISION)

    assert _revision(engine) == HEAD_REVISION
    assert _dataset_schema_snapshot(engine) == before
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                """
                SELECT
                    provider,
                    dataset_kind,
                    symbol,
                    contract_or_series,
                    frequency,
                    adjustment,
                    schema_version
                FROM market_datasets
                WHERE id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id},
        ).one()
    assert tuple(stored) == (
        "rqdata",
        "actual_dominant",
        "jm",
        "JM2609",
        "1m",
        "none",
        "v1",
    )
    _clear_data_core_rows(engine)


def test_current_parent_upgrade_preserves_legacy_metadata_rows(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    _clear_data_core_rows(engine)
    command.downgrade(config, PARENT_REVISION)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM profile_active_bindings
                WHERE profile_id = 'task2-migration-profile'
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM data_profiles
                WHERE profile_id = 'task2-migration-profile'
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM main_contract_map
                WHERE data_version LIKE 'task2-migration-%'
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO main_contract_map (
                    instrument_symbol,
                    trade_date,
                    rank,
                    contract_code,
                    rule,
                    provider,
                    data_version,
                    raw_payload,
                    created_at,
                    updated_at
                )
                VALUES
                    (
                        'jm', DATE '2026-07-30', 1, 'jm2609',
                        'volume_open_interest', 'rqdata', 'task2-migration-rank-1',
                        '{"formal": true}', now(), now()
                    ),
                    (
                        'jm', DATE '2026-07-30', 2, 'jm2611',
                        'volume_open_interest', 'rqdata', 'task2-migration-rank-2',
                        '{"formal": true}', now(), now()
                    )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO data_profiles (
                    profile_id,
                    label,
                    description,
                    contract_roles,
                    periods,
                    quality_policy,
                    provider,
                    is_active,
                    config_path,
                    created_at,
                    updated_at
                )
                VALUES (
                    'task2-migration-profile',
                    'Task 2 migration profile',
                    'representative pre-existing row',
                    '["dominant_main"]',
                    '["1m"]',
                    'passed_only',
                    'rqdata',
                    true,
                    'task2-migration-profile.json',
                    now(),
                    now()
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO profile_active_bindings (
                    profile_id,
                    instrument_symbol,
                    contract_code,
                    contract_role,
                    period,
                    data_version,
                    market_data_file_id,
                    binding_status,
                    activated_at,
                    superseded_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    'task2-migration-profile',
                    'jm',
                    'jm2609',
                    'dominant_main',
                    '1m',
                    'task2-migration-binding-v1',
                    NULL,
                    'active',
                    now(),
                    NULL,
                    now(),
                    now()
                )
                """
            )
        )

    before = {
        "main_contract_map": _snapshot_rows(
            engine, "main_contract_map", "data_version"
        ),
        "data_profiles": _snapshot_rows(engine, "data_profiles", "profile_id"),
        "profile_active_bindings": _snapshot_rows(
            engine, "profile_active_bindings", "profile_id"
        ),
    }
    assert len(before["main_contract_map"]) == 2
    assert len(before["data_profiles"]) == 1
    assert len(before["profile_active_bindings"]) == 1

    command.upgrade(config, "head")

    assert _snapshot_rows(engine, "main_contract_map", "data_version") == before[
        "main_contract_map"
    ]
    assert _snapshot_rows(engine, "data_profiles", "profile_id") == before[
        "data_profiles"
    ]
    assert _snapshot_rows(
        engine, "profile_active_bindings", "profile_id"
    ) == before["profile_active_bindings"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM market_datasets")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM market_partitions")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM data_gaps")).scalar_one() == 0


def test_canonical_main_contract_view_filters_rows_and_rejects_all_dml(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM main_contract_map
                WHERE data_version LIKE 'task2-migration-view-%'
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO main_contract_map (
                    instrument_symbol,
                    trade_date,
                    rank,
                    contract_code,
                    rule,
                    provider,
                    data_version,
                    raw_payload,
                    created_at,
                    updated_at
                )
                VALUES
                    (
                        'jm', DATE '2026-07-30', 1, 'JM2609',
                        'volume_open_interest', 'rqdata',
                        'task2-migration-view-canonical', '{}', now(), now()
                    ),
                    (
                        'jm', DATE '2026-07-30', 2, 'JM2611',
                        'volume_open_interest', 'rqdata',
                        'task2-migration-view-rank2', '{}', now(), now()
                    ),
                    (
                        'jm', DATE '2026-07-30', 1, 'JM2607',
                        'volume_open_interest', 'other',
                        'task2-migration-view-provider', '{}', now(), now()
                    ),
                    (
                        'jm', DATE '2026-07-30', 1, 'JM2605',
                        'other', 'rqdata',
                        'task2-migration-view-rule', '{}', now(), now()
                    )
                """
            )
        )

    before = _snapshot_rows(engine, "main_contract_map", "data_version")
    with engine.connect() as connection:
        view_rows = connection.execute(
            text(
                """
                SELECT
                    provider,
                    rank,
                    rule,
                    symbol,
                    trading_day,
                    actual_contract,
                    data_version
                FROM data_core_main_contract_map
                WHERE data_version LIKE 'task2-migration-view-%'
                """
            )
        ).all()
    assert [tuple(row) for row in view_rows] == [
        (
            "rqdata",
            1,
            "volume_open_interest",
            "jm",
            datetime(2026, 7, 30).date(),
            "JM2609",
            "task2-migration-view-canonical",
        )
    ]

    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO data_core_main_contract_map (
                        symbol,
                        trading_day,
                        actual_contract,
                        provider,
                        rank,
                        rule,
                        data_version,
                        created_at
                    )
                    VALUES (
                        'jm',
                        DATE '2026-07-31',
                        'JM2609',
                        'rqdata',
                        1,
                        'volume_open_interest',
                        'task2-migration-view-insert',
                        now()
                    )
                    """
                )
            )
    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE data_core_main_contract_map
                    SET actual_contract = 'JM2611'
                    WHERE data_version = 'task2-migration-view-canonical'
                    """
                )
            )
    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM data_core_main_contract_map
                    WHERE data_version = 'task2-migration-view-canonical'
                    """
                )
            )

    assert _snapshot_rows(engine, "main_contract_map", "data_version") == before


def test_schema_introspection_has_named_constraints_trigger_and_function(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert NEW_TABLES <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("market_datasets")} == {
        "id",
        "provider",
        "dataset_kind",
        "symbol",
        "contract_or_series",
        "frequency",
        "adjustment",
        "schema_version",
        "created_at",
    }
    assert {
        column["name"] for column in inspector.get_columns("market_partitions")
    } == {
        "id",
        "dataset_id",
        "coverage_start",
        "coverage_end",
        "manifest_version",
        "manifest_uri",
        "manifest_digest",
        "file_uri",
        "checksum",
        "row_count",
        "overlap_reason",
        "created_at",
    }
    assert {column["name"] for column in inspector.get_columns("data_gaps")} == {
        "id",
        "dataset_id",
        "gap_start",
        "gap_end",
        "reason_code",
        "details",
        "observed_at",
    }
    for table_name, column_name in (
        ("market_datasets", "created_at"),
        ("market_partitions", "created_at"),
        ("data_gaps", "details"),
        ("data_gaps", "observed_at"),
    ):
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        assert columns[column_name]["default"] is None

    assert _constraint_map(engine, "market_datasets")[
        "uq_market_datasets_dataset_key"
    ] == "UNIQUE"
    dataset_constraints = _constraint_map(engine, "market_datasets")
    assert dataset_constraints["ck_market_datasets_provider_rqdata"] == "CHECK"
    assert dataset_constraints["ck_market_datasets_kind"] == "CHECK"
    assert dataset_constraints["ck_market_datasets_frequency"] == "CHECK"
    assert "ck_market_datasets_actual_dominant_weekly" not in dataset_constraints
    assert dataset_constraints["ck_market_datasets_identity_nonempty"] == "CHECK"
    assert dataset_constraints["ck_market_datasets_identity_canonical"] == "CHECK"
    partition_constraints = _constraint_map(engine, "market_partitions")
    assert partition_constraints["uq_market_partitions_exact_identity"] == "UNIQUE"
    assert partition_constraints[
        "ck_market_partitions_half_open_window"
    ] == "CHECK"
    assert partition_constraints[
        "ck_market_partitions_row_count_nonnegative"
    ] == "CHECK"
    assert partition_constraints[
        "ck_market_partitions_manifest_digest_sha256"
    ] == "CHECK"
    assert partition_constraints["ck_market_partitions_checksum_sha256"] == "CHECK"
    assert partition_constraints["ck_market_partitions_overlap_reason"] == "CHECK"
    assert partition_constraints[
        "fk_market_partitions_dataset_id_market_datasets"
    ] == "FOREIGN KEY"
    gap_constraints = _constraint_map(engine, "data_gaps")
    assert gap_constraints["uq_data_gaps_exact_window"] == "UNIQUE"
    assert gap_constraints["ck_data_gaps_half_open_window"] == "CHECK"
    assert gap_constraints["fk_data_gaps_dataset_id_market_datasets"] == "FOREIGN KEY"

    with engine.connect() as connection:
        exclusion_definition = connection.execute(
            text(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname = 'ex_market_partitions_unexplained_coverage'
                  AND contype = 'x'
                """
            )
        ).scalar_one()
        assert (
            "int4range(dataset_id, dataset_id, '[]'::text) WITH =" in exclusion_definition
        )
        assert (
            "tstzrange(coverage_start, coverage_end, '[)'::text) WITH &&"
            in exclusion_definition
        )
        assert "WHERE ((overlap_reason IS NULL))" in exclusion_definition

        trigger = connection.execute(
            text(
                """
                SELECT t.tgname, p.proname
                FROM pg_trigger AS t
                JOIN pg_proc AS p ON p.oid = t.tgfoid
                WHERE t.tgrelid = 'market_partitions'::regclass
                  AND NOT t.tgisinternal
                """
            )
        ).one()
        assert tuple(trigger) == (
            "trg_market_partitions_immutable",
            "reject_market_partition_fact_updates",
        )

        view_definition = connection.execute(
            text(
                """
                SELECT pg_get_viewdef(CAST(:view_name AS regclass), true)
                """
            ),
            {"view_name": CANONICAL_VIEW},
        ).scalar_one()
        assert "SELECT DISTINCT" in view_definition
        assert "trade_date AS trading_day" in view_definition
        assert "contract_code AS actual_contract" in view_definition


def test_dataset_key_and_gap_window_uniqueness_are_enforced(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    dataset_id = _insert_dataset(engine)

    with pytest.raises(SQLAlchemyError):
        _insert_dataset(engine)

    for overrides in (
        {"dataset_kind": "continuous"},
        {"frequency": "1d"},
        {"adjustment": "pre"},
        {"schema_version": "v2"},
    ):
        assert _insert_dataset(engine, **overrides) != dataset_id

    gap = {
        "dataset_id": dataset_id,
        "gap_start": "2026-07-30T01:00:00+00:00",
        "gap_end": "2026-07-30T02:00:00+00:00",
        "reason_code": "missing_provider_bar",
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO data_gaps (
                    dataset_id,
                    gap_start,
                    gap_end,
                    reason_code,
                    details,
                    observed_at
                )
                VALUES (
                    :dataset_id,
                    :gap_start,
                    :gap_end,
                    :reason_code,
                    '{}',
                    now()
                )
                """
            ),
            gap,
        )
    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO data_gaps (
                        dataset_id,
                        gap_start,
                        gap_end,
                        reason_code,
                        details,
                        observed_at
                    )
                    VALUES (
                        :dataset_id,
                        :gap_start,
                        :gap_end,
                        :reason_code,
                        '{}',
                        now()
                    )
                    """
                ),
                gap,
            )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("provider", "other"),
        ("dataset_kind", "synthetic"),
        ("frequency", "2m"),
        ("symbol", " "),
        ("symbol", "JM"),
        ("contract_or_series", ""),
        ("contract_or_series", "jm2609"),
        ("adjustment", " "),
        ("adjustment", "NONE"),
        ("schema_version", ""),
        ("schema_version", " v1"),
    ],
)
def test_dataset_rejects_noncanonical_identity(
    migration_context: tuple[str, Config, Engine],
    field: str,
    invalid_value: str,
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    values = {
        "provider": "rqdata",
        "dataset_kind": "actual_dominant",
        "symbol": f"jm-{field}",
        "contract_or_series": f"JM-{field}",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "v1",
    }
    values[field] = invalid_value

    with pytest.raises(SQLAlchemyError):
        _insert_dataset(engine, **values)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("manifest_digest", "A" * 64),
        ("manifest_digest", "a" * 63),
        ("manifest_digest", ("a" * 63) + "g"),
        ("checksum", "B" * 64),
        ("checksum", "b" * 63),
        ("checksum", ("b" * 63) + "g"),
        ("row_count", -1),
        ("overlap_reason", "manual_override"),
    ],
)
def test_partition_rejects_invalid_values(
    migration_context: tuple[str, Config, Engine],
    field: str,
    invalid_value: str | int,
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    invalid_text = str(invalid_value)
    dataset_id = _insert_dataset(
        engine,
        contract_or_series=(
            f"JM-{field.upper()}-{len(invalid_text)}-"
            f"{invalid_text[:1]}-{invalid_text[-1:]}"
        ).upper(),
    )
    values = _partition_values(dataset_id)
    values[field] = invalid_value

    with pytest.raises(SQLAlchemyError):
        _insert_partition(engine, values)


def test_partition_and_gap_reject_empty_or_reversed_windows(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    dataset_id = _insert_dataset(engine, contract_or_series="JM-WINDOW-CHECKS")

    for start, end in (
        ("2026-07-30T01:00:00+00:00", "2026-07-30T01:00:00+00:00"),
        ("2026-07-30T02:00:00+00:00", "2026-07-30T01:00:00+00:00"),
    ):
        with pytest.raises(SQLAlchemyError):
            _insert_partition(
                engine,
                _partition_values(
                    dataset_id,
                    coverage_start=start,
                    coverage_end=end,
                ),
            )
        with pytest.raises(SQLAlchemyError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO data_gaps (
                            dataset_id,
                            gap_start,
                            gap_end,
                            reason_code,
                            details,
                            observed_at
                        )
                        VALUES (
                            :dataset_id,
                            :gap_start,
                            :gap_end,
                            'invalid-window',
                            '{}',
                            now()
                        )
                        """
                    ),
                    {
                        "dataset_id": dataset_id,
                        "gap_start": start,
                        "gap_end": end,
                    },
                )


def test_partition_overlap_policy_allows_touching_and_controlled_exceptions(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    dataset_id = _insert_dataset(
        engine,
        contract_or_series="JM-OVERLAP-POLICY",
    )
    _insert_partition(engine, _partition_values(dataset_id))

    _insert_partition(
        engine,
        _partition_values(
            dataset_id,
            coverage_start="2026-07-30T02:00:00+00:00",
            coverage_end="2026-07-30T03:00:00+00:00",
            manifest_version="manifest-touching",
            manifest_uri="manifest://jm/touching",
            file_uri="parquet://jm/touching.parquet",
        ),
    )

    with pytest.raises(SQLAlchemyError):
        _insert_partition(
            engine,
            _partition_values(
                dataset_id,
                coverage_start="2026-07-30T01:30:00+00:00",
                coverage_end="2026-07-30T02:30:00+00:00",
                manifest_version="manifest-unexplained-overlap",
                manifest_uri="manifest://jm/unexplained",
                file_uri="parquet://jm/unexplained.parquet",
            ),
        )

    for index, reason in enumerate(
        ("version_replacement", "repair_overlay", "rollover_transition"),
        start=1,
    ):
        _insert_partition(
            engine,
            _partition_values(
                dataset_id,
                coverage_start=f"2026-07-30T01:{index}0:00+00:00",
                coverage_end=f"2026-07-30T02:{index}0:00+00:00",
                manifest_version=f"manifest-{reason}",
                manifest_uri=f"manifest://jm/{reason}",
                file_uri=f"parquet://jm/{reason}.parquet",
                overlap_reason=reason,
            ),
        )


def test_partition_create_only_facts_are_immutable(
    migration_context: tuple[str, Config, Engine],
) -> None:
    _, config, engine = migration_context
    command.upgrade(config, "head")
    dataset_id = _insert_dataset(engine, contract_or_series="JM-IMMUTABLE-A")
    replacement_dataset_id = _insert_dataset(
        engine,
        contract_or_series="JM-IMMUTABLE-B",
    )
    partition_id = _insert_partition(engine, _partition_values(dataset_id))
    replacements: dict[str, Any] = {
        "dataset_id": replacement_dataset_id,
        "coverage_start": "2026-07-30T00:30:00+00:00",
        "coverage_end": "2026-07-30T02:30:00+00:00",
        "manifest_version": "manifest-v2",
        "manifest_uri": "manifest://jm/manifest-v2",
        "manifest_digest": "c" * 64,
        "file_uri": "parquet://jm/part-v2.parquet",
        "checksum": "d" * 64,
        "row_count": 61,
        "overlap_reason": "repair_overlay",
    }

    for column, replacement in replacements.items():
        with pytest.raises(SQLAlchemyError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"""
                        UPDATE market_partitions
                        SET {column} = :replacement
                        WHERE id = :partition_id
                        """
                    ),
                    {
                        "replacement": replacement,
                        "partition_id": partition_id,
                    },
                )

    with engine.connect() as connection:
        stored = connection.execute(
            text(
                """
                SELECT
                    dataset_id,
                    coverage_start,
                    coverage_end,
                    manifest_version,
                    manifest_uri,
                    manifest_digest,
                    file_uri,
                    checksum,
                    row_count,
                    overlap_reason
                FROM market_partitions
                WHERE id = :partition_id
                """
            ),
            {"partition_id": partition_id},
        ).one()
    assert tuple(stored) == (
        dataset_id,
        datetime(2026, 7, 30, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 30, 2, 0, tzinfo=UTC),
        "manifest-v1",
        "manifest://jm2609/manifest-v1",
        SHA_A,
        "parquet://jm2609/part-v1.parquet",
        SHA_B,
        60,
        None,
    )
