from __future__ import annotations

import importlib.util
import os
from datetime import date, time
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema, DropSchema

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


def test_session_anchor_migration_rejects_zero_length_after_normalization() -> None:
    migration = _load_migration()
    row = {
        "id": 1,
        "exchange_code": "DCE",
        "instrument_symbol": "jm",
        "session_name": "invalid",
        "start_time": time(9, 1),
        "end_time": time(9),
        "effective_from": date(2026, 9, 1),
        "effective_to": date(2026, 9, 1),
        "provider": "rqdata",
    }

    assert migration._valid_sessions((row,)) is False


@pytest.mark.isolated_postgresql
def test_upgrade_normalizes_real_session_rows_and_preserves_alert_facts(
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
    base_engine = create_engine(url, pool_pre_ping=True)
    schema = f"session_anchor_migration_{uuid4().hex}"
    sentinel_table = f"session_anchor_sentinel_{uuid4().hex}"
    with base_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        connection.exec_driver_sql(
            f'CREATE TABLE public."{sentinel_table}" (id integer PRIMARY KEY)'
        )
    engine: Engine | None = None
    try:
        monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
        engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        config = Config()
        config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        monkeypatch.setenv("DATABASE_URL", url)
        command.upgrade(config, "20260902_0044")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO exchanges "
                "(code, name, country, timezone, is_active, created_at, updated_at) "
                "VALUES ('DCE', 'Dalian Commodity Exchange', 'CN', "
                "'Asia/Shanghai', true, now(), now())"
            ))
            connection.execute(text(
                "INSERT INTO instruments "
                "(symbol, name, exchange_code, is_active, created_at, updated_at) "
                "VALUES ('jm', 'Coking Coal', 'DCE', true, now(), now())"
            ))
            connection.execute(text(
                "INSERT INTO alert_events "
                "(rule_id, symbol, contract, trading_day, frequency, bar_end, "
                "result_codes, detected_at, notification_attempted_at) "
                "VALUES ((SELECT id FROM alert_rules "
                "WHERE rule_code = 'htdy_original_15m'), 'jm', 'JM2701', "
                "DATE '2026-09-01', '15m', "
                "TIMESTAMPTZ '2026-09-01 02:30:00+00', "
                "ARRAY['buy']::varchar[], "
                "TIMESTAMPTZ '2026-09-01 02:30:01+00', "
                "TIMESTAMPTZ '2026-09-01 02:30:02+00')"
            ))
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
                    "exchange": "DCE",
                    "symbol": "jm",
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
            assert len(events_before) == 1

        command.upgrade(config, "20260903_0045")
        with engine.begin() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "20260903_0045"
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
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass(:qualified_name)"),
                {"qualified_name": f"public.{sentinel_table}"},
            ) == f"public.{sentinel_table}"
    finally:
        if engine is not None:
            engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.exec_driver_sql(
                f'DROP TABLE IF EXISTS public."{sentinel_table}"'
            )
        base_engine.dispose()
