from __future__ import annotations

import importlib.util
import os
from datetime import date, time
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


QUANT_API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    QUANT_API_ROOT
    / "alembic/versions/20260903_0045_normalize_rqdata_session_anchor.py"
)
SUBING_MIGRATION_TEST_PATH = Path(__file__).with_name(
    "test_subing_ths_alert_migration.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("session_anchor_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_session_anchor_migration_is_forward_only_from_exact_0044_parent() -> None:
    migration = _load_migration()

    assert migration.revision == "20260903_0045"
    assert migration.down_revision == "20260902_0044"
    with pytest.raises(
        RuntimeError,
        match="^RQDATA_SESSION_ANCHOR_DOWNGRADE_UNSUPPORTED$",
    ):
        migration.downgrade()


@pytest.mark.parametrize(
    ("provider_label", "expected_boundary"),
    [
        (time(9, 1), time(9)),
        (time(10, 31), time(10, 30)),
        (time(13, 31), time(13, 30)),
        (time(21, 1), time(21)),
        (time(0), time(23, 59)),
    ],
)
def test_session_anchor_migration_normalizes_one_minute_with_midnight_wrap(
    provider_label: time,
    expected_boundary: time,
) -> None:
    migration = _load_migration()

    assert migration._exclusive_start(provider_label) == expected_boundary


def test_session_anchor_migration_preflight_rejects_normalized_overlap() -> None:
    migration = _load_migration()
    common = {
        "exchange_code": "DCE",
        "instrument_symbol": "jm",
        "effective_from": date(2026, 9, 1),
        "effective_to": date(2026, 9, 1),
        "provider": "rqdata",
    }
    rows = (
        {
            **common,
            "id": 1,
            "session_name": "first",
            "start_time": time(9, 1),
            "end_time": time(10, 15),
        },
        {
            **common,
            "id": 2,
            "session_name": "second",
            "start_time": time(10, 15),
            "end_time": time(11, 30),
        },
    )

    assert migration._valid_sessions(rows) is False


def test_session_anchor_migration_rejects_an_already_normalized_baseline() -> None:
    migration = _load_migration()
    row = {
        "id": 1,
        "exchange_code": "DCE",
        "instrument_symbol": "jm",
        "session_name": "day",
        "start_time": time(9),
        "end_time": time(10, 15),
        "effective_from": date(2026, 9, 1),
        "effective_to": date(2026, 9, 1),
        "provider": "rqdata",
    }

    assert migration._valid_sessions((row,)) is False


@pytest.mark.isolated_postgresql
def test_upgrade_normalizes_real_session_rows_and_preserves_alert_facts() -> None:
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
    engine = create_engine(url, pool_pre_ping=True)
    support = _load_external_module(SUBING_MIGRATION_TEST_PATH)
    _, schema = support._prepared_0043_schema(engine)
    try:
        support._run_loaded_upgrade(engine, schema, support._load_module(support.MIGRATION_PATH))
        with engine.begin() as connection:
            support._search_path(connection, schema)
            connection.execute(text(
                "UPDATE alembic_version SET version_num = '20260902_0044'"
            ))
            connection.execute(text("DELETE FROM trading_sessions"))
            identity = connection.execute(text(
                "SELECT exchange_code, symbol FROM instruments ORDER BY symbol LIMIT 1"
            )).mappings().one()
            for index, (label, end) in enumerate((
                ("21:01", "23:00"),
                ("09:01", "10:15"),
                ("10:31", "11:30"),
                ("13:31", "15:00"),
            )):
                connection.execute(text(
                    "INSERT INTO trading_sessions "
                    "(exchange_code, instrument_symbol, session_name, start_time, "
                    "end_time, effective_from, effective_to, crosses_midnight, "
                    "is_active, provider, created_at) VALUES "
                    "(:exchange, :symbol, :name, CAST(:start AS time), CAST(:end AS time), "
                    "DATE '2026-09-01', DATE '2026-09-01', false, true, 'rqdata', now())"
                ), {
                    "exchange": identity["exchange_code"],
                    "symbol": identity["symbol"],
                    "name": f"session-{index}",
                    "start": label,
                    "end": end,
                })
            rules_before = connection.execute(text(
                "SELECT id, rule_code, enabled, scope_product_frequencies, "
                "created_at, updated_at FROM alert_rules ORDER BY id"
            )).mappings().all()
            events_before = connection.execute(text(
                "SELECT * FROM alert_events ORDER BY id"
            )).mappings().all()

        migration = _load_migration()
        with engine.begin() as connection:
            support._search_path(connection, schema)
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            starts = tuple(connection.execute(text(
                "SELECT start_time FROM trading_sessions ORDER BY start_time"
            )).scalars())
            assert starts == (time(9), time(10, 30), time(13, 30), time(21))
            rules_after = connection.execute(text(
                "SELECT id, rule_code, enabled, scope_product_frequencies, "
                "created_at, updated_at FROM alert_rules ORDER BY id"
            )).mappings().all()
            events_after = connection.execute(text(
                "SELECT * FROM alert_events ORDER BY id"
            )).mappings().all()
            assert [dict(row) for row in rules_after] == [dict(row) for row in rules_before]
            assert [dict(row) for row in events_after] == [dict(row) for row in events_before]
    finally:
        support._drop_schema(engine, schema)
        engine.dispose()


def _load_external_module(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"session_anchor_support_{uuid4().hex}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
