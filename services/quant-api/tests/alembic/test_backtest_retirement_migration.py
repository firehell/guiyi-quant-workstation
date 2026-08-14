from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.db.migration_test_guard import (
    MigrationTestDatabaseSafetyError,
    probe_database_identity,
    require_isolated_migration_database_url,
)


PARENT_REVISION = "20260803_0032"
RETIREMENT_REVISION = "20260805_0033"
QUANT_API_ROOT = Path(__file__).resolve().parents[2]
RETIREMENT_SOURCE = (
    QUANT_API_ROOT / "alembic" / "versions" / "20260805_0033_retire_backtest.py"
)
TARGET_SIGNAL_KEYS = (
    "htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f",
    "htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5",
    "htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee",
)


def test_backtest_retirement_remains_on_linear_history_before_alert_v1() -> None:
    """Backtest retirement stays explicit while later revisions advance the head."""

    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    revision = scripts.get_revision(RETIREMENT_REVISION)
    assert revision is not None
    assert revision.down_revision == PARENT_REVISION
    assert scripts.get_revision("20260808_0034") is not None
    assert scripts.get_heads() == ["20260814_0038"]


def test_backtest_retirement_sql_deletes_only_scoped_legacy_rows() -> None:
    """Shared Task06 and non-backtest review/signal rows must survive the drop."""

    source = RETIREMENT_SOURCE.read_text(encoding="utf-8")

    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "source_type = 'backtest_trade'" in source
    assert "JOIN backtest_trades AS trade ON trade.id = review.source_id" in source
    assert "legacy S6 retirement logical dependency drift" in source
    for key in TARGET_SIGNAL_KEYS:
        assert key in source
    assert "enterprise_wechat:signal_event:4" in source
    assert "DELETE FROM signal_notifications;" not in source
    assert "DELETE FROM signal_events;" not in source
    assert "DELETE FROM strategy_signals;" not in source
    assert "SELECT count(*) INTO review_count FROM review_notes;" not in source
    assert "SELECT count(*) INTO signal_count FROM strategy_signals;" not in source
    assert "main_contract_maps" not in source
    assert "market_data_files" not in source


def test_backtest_retirement_sql_requires_exact_identity_before_delete() -> None:
    """The migration is fail-closed and deletes its targets in dependency order."""

    source = RETIREMENT_SOURCE.read_text(encoding="utf-8")

    assert "legacy S6 retirement identity mismatch" in source
    assert (
        "event.event_key = 'signal_created:' || signal.dedupe_key || chr(58) || 'created'"
        in source
    )
    assert "event.decision_id IS NULL" in source
    assert "event.source_mode = 'live_realtime_repainting'" in source
    assert "notification.event_id" in source
    assert "notification.signal_id" in source
    assert "review_count = 7 AND notification_count = 1 AND event_count = 3" in source
    assert "signal_count = 3 AND task_count = 23 AND report_count = 15" in source
    assert "trade_count = 4361 AND order_count = 4225" in source

    review_delete = source.index("DELETE FROM review_notes WHERE source_type = 'backtest_trade'")
    notification_delete = source.index("DELETE FROM signal_notifications")
    event_delete = source.index("DELETE FROM signal_events")
    signal_delete = source.index("DELETE FROM strategy_signals")
    task_delete = source.index("DELETE FROM backtest_tasks")
    assert review_delete < notification_delete < event_delete < signal_delete < task_delete

    assert source.index('op.drop_table("backtest_orders")') < source.index(
        'op.drop_table("backtest_trades")'
    ) < source.index('op.drop_table("backtest_reports")') < source.index(
        'op.drop_table("backtest_tasks")'
    )


@pytest.fixture
def isolated_postgres_engine() -> Engine:
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

    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def retirement_schema(isolated_postgres_engine: Engine) -> tuple[Engine, str]:
    schema = f"retirement_{uuid4().hex}"
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        _create_pre_retirement_schema(connection)
        _seed_shared_rows(connection)
    try:
        yield isolated_postgres_engine, schema
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_all_empty_installation_drops_only_backtest_tables(
    retirement_schema: tuple[Engine, str],
) -> None:
    engine, schema = retirement_schema

    _run_retirement_upgrade(engine, schema)

    assert not _backtest_tables(engine, schema)
    assert _shared_counts(engine, schema) == (1, 1, 1, 1, 1)


def test_exact_production_baseline_cascades_and_preserves_shared_rows(
    retirement_schema: tuple[Engine, str],
) -> None:
    engine, schema = retirement_schema
    _seed_exact_production_baseline(engine, schema)

    _run_retirement_upgrade(engine, schema)

    assert not _backtest_tables(engine, schema)
    assert _shared_counts(engine, schema) == (1, 1, 1, 1, 1)
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        assert connection.execute(
            text("SELECT count(*) FROM review_notes WHERE source_type = 'backtest_trade'")
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT count(*) FROM strategy_signals "
                "WHERE strategy_name = 'htdy_original_realtime_first_seen'"
            )
        ).scalar_one() == 0


@pytest.mark.parametrize(
    ("drift_sql", "expected_error"),
    [
        ("INSERT INTO backtest_tasks VALUES (24)", "requires exact baseline"),
        (
            "UPDATE strategy_signals SET direction = 'short' WHERE id = 1",
            "legacy S6 retirement identity mismatch",
        ),
        (
            """
            INSERT INTO signal_events (
                id, event_key, event_type, signal_id, decision_id, source_mode,
                strategy_name, strategy_version, symbol, product, contract,
                actual_contract, dominant_mapping_date, exchange, period, source,
                signal_status
            )
            SELECT 100, 'extra-dependent-event', event_type, signal_id, decision_id,
                source_mode, strategy_name, strategy_version, symbol, product,
                contract, actual_contract, dominant_mapping_date, exchange, period,
                source, signal_status
            FROM signal_events WHERE id = 4
            """,
            "legacy S6 retirement logical dependency drift",
        ),
        (
            "UPDATE review_notes SET source_id = 999999 WHERE id = 1",
            "backtest retirement linked review data drift",
        ),
    ],
)
def test_drift_is_rejected_and_transaction_rolls_back(
    retirement_schema: tuple[Engine, str],
    drift_sql: str,
    expected_error: str,
) -> None:
    engine, schema = retirement_schema
    _seed_exact_production_baseline(engine, schema)
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        connection.exec_driver_sql(drift_sql)

    with pytest.raises(SQLAlchemyError, match=expected_error):
        _run_retirement_upgrade(engine, schema)

    assert _backtest_tables(engine, schema) == {
        "backtest_orders",
        "backtest_reports",
        "backtest_tasks",
        "backtest_trades",
    }
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        assert connection.execute(text("SELECT count(*) FROM strategy_signals")).scalar_one() == 4
        assert connection.execute(text("SELECT count(*) FROM review_notes")).scalar_one() == 8
        assert connection.execute(text("SELECT count(*) FROM shared_sentinel")).scalar_one() == 1


def test_extra_notification_targeting_retired_event_and_signal_blocks_unscoped_delete(
    retirement_schema: tuple[Engine, str],
) -> None:
    """A differently keyed notification must not be orphaned by scoped S6 deletion."""

    engine, schema = retirement_schema
    _seed_exact_production_baseline(engine, schema)
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        connection.execute(
            text(
                """
                INSERT INTO signal_notifications
                    (id, event_id, signal_id, dedupe_key, event_type, channel, status)
                VALUES
                    (100, 4, 1, 'external:signal-event:4',
                     'signal_created', 'websocket', 'pending')
                """
            )
        )

    with pytest.raises(
        SQLAlchemyError,
        match="legacy S6 retirement logical dependency drift",
    ):
        _run_retirement_upgrade(engine, schema)

    _assert_exact_baseline_preserved(
        engine,
        schema,
        expected_notification_count=3,
        expected_review_count=8,
    )
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        assert connection.execute(
            text("SELECT count(*) FROM signal_notifications WHERE id = 100")
        ).scalar_one() == 1


def test_strategy_signal_review_targeting_retired_signal_blocks_unscoped_delete(
    retirement_schema: tuple[Engine, str],
) -> None:
    """A strategy-signal review must not survive with its target silently deleted."""

    engine, schema = retirement_schema
    _seed_exact_production_baseline(engine, schema)
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        connection.execute(
            text(
                "INSERT INTO review_notes (id, source_type, source_id) "
                "VALUES (100, 'strategy_signal', 1)"
            )
        )

    with pytest.raises(
        SQLAlchemyError,
        match="legacy S6 retirement logical dependency drift",
    ):
        _run_retirement_upgrade(engine, schema)

    _assert_exact_baseline_preserved(
        engine,
        schema,
        expected_notification_count=2,
        expected_review_count=9,
    )
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        assert connection.execute(
            text("SELECT count(*) FROM review_notes WHERE id = 100")
        ).scalar_one() == 1


def test_signal_event_review_targeting_retired_event_blocks_unscoped_delete(
    retirement_schema: tuple[Engine, str],
) -> None:
    """A signal-event review must not survive with its target silently deleted."""

    engine, schema = retirement_schema
    _seed_exact_production_baseline(engine, schema)
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        connection.execute(
            text(
                "INSERT INTO review_notes (id, source_type, source_id) "
                "VALUES (100, 'signal_event', 4)"
            )
        )

    with pytest.raises(
        SQLAlchemyError,
        match="legacy S6 retirement logical dependency drift",
    ):
        _run_retirement_upgrade(engine, schema)

    _assert_exact_baseline_preserved(
        engine,
        schema,
        expected_notification_count=2,
        expected_review_count=9,
    )
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        assert connection.execute(
            text("SELECT count(*) FROM review_notes WHERE id = 100")
        ).scalar_one() == 1


def test_drop_failure_after_successful_dml_and_first_ddl_rolls_back_everything(
    retirement_schema: tuple[Engine, str],
) -> None:
    """A late FK failure must restore deleted rows and the already-dropped orders table."""

    engine, schema = retirement_schema
    _seed_exact_production_baseline(engine, schema)
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        connection.execute(
            text(
                """
                CREATE TABLE external_trade_ref (
                    id bigint PRIMARY KEY,
                    trade_id bigint REFERENCES backtest_trades(id)
                )
                """
            )
        )

    with pytest.raises(SQLAlchemyError, match="cannot drop table backtest_trades"):
        _run_retirement_upgrade(engine, schema)

    _assert_exact_baseline_preserved(
        engine,
        schema,
        expected_notification_count=2,
        expected_review_count=8,
    )
    assert "external_trade_ref" in inspect(engine).get_table_names(schema=schema)


def _load_retirement_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"retirement_migration_{uuid4().hex}",
        RETIREMENT_SOURCE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_retirement_upgrade(engine: Engine, schema: str) -> None:
    module = _load_retirement_module()
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()


def _set_search_path(connection: Connection, schema: str) -> None:
    connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')


def _backtest_tables(engine: Engine, schema: str) -> set[str]:
    return {
        table
        for table in inspect(engine).get_table_names(schema=schema)
        if table.startswith("backtest_")
    }


def _shared_counts(engine: Engine, schema: str) -> tuple[int, int, int, int, int]:
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        return tuple(
            int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in (
                "strategy_signals",
                "signal_events",
                "signal_notifications",
                "review_notes",
                "shared_sentinel",
            )
        )


def _assert_exact_baseline_preserved(
    engine: Engine,
    schema: str,
    *,
    expected_notification_count: int,
    expected_review_count: int,
) -> None:
    assert _backtest_tables(engine, schema) == {
        "backtest_orders",
        "backtest_reports",
        "backtest_tasks",
        "backtest_trades",
    }
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        assert tuple(
            int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in (
                "backtest_tasks",
                "backtest_reports",
                "backtest_trades",
                "backtest_orders",
            )
        ) == (23, 15, 4361, 4225)
        assert connection.execute(
            text("SELECT count(*) FROM review_notes WHERE source_type = 'backtest_trade'")
        ).scalar_one() == 7
        assert tuple(
            int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in (
                "strategy_signals",
                "signal_events",
                "signal_notifications",
                "review_notes",
                "shared_sentinel",
            )
        ) == (4, 4, expected_notification_count, expected_review_count, 1)
        assert connection.execute(
            text("SELECT count(*) FROM strategy_signals WHERE id BETWEEN 1 AND 3")
        ).scalar_one() == 3
        assert connection.execute(
            text("SELECT count(*) FROM signal_events WHERE id BETWEEN 4 AND 6")
        ).scalar_one() == 3
        assert connection.execute(
            text(
                "SELECT count(*) FROM signal_notifications "
                "WHERE dedupe_key = 'enterprise_wechat:signal_event:4'"
            )
        ).scalar_one() == 1


def _create_pre_retirement_schema(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE review_notes (
            id bigint PRIMARY KEY, source_type text NOT NULL, source_id bigint
        );
        CREATE TABLE review_attachments (
            id bigint PRIMARY KEY, review_id bigint NOT NULL
        );
        CREATE TABLE research_samples (
            id bigint PRIMARY KEY, review_id bigint NOT NULL
        );
        CREATE TABLE strategy_signals (
            id bigint PRIMARY KEY,
            dedupe_key text NOT NULL UNIQUE,
            strategy_name text,
            strategy_version text,
            symbol text,
            product text,
            contract text,
            actual_contract text,
            exchange text,
            period text,
            provider text,
            source text,
            status text,
            spec_source text,
            dominant_mapping_date date,
            direction text
        );
        CREATE TABLE signal_events (
            id bigint PRIMARY KEY,
            event_key text NOT NULL UNIQUE,
            event_type text,
            signal_id bigint,
            decision_id bigint,
            source_mode text,
            strategy_name text,
            strategy_version text,
            symbol text,
            product text,
            contract text,
            actual_contract text,
            dominant_mapping_date date,
            exchange text,
            period text,
            source text,
            signal_status text
        );
        CREATE TABLE signal_notifications (
            id bigint PRIMARY KEY,
            event_id bigint,
            signal_id bigint,
            dedupe_key text NOT NULL UNIQUE,
            event_type text,
            channel text,
            status text
        );
        CREATE TABLE backtest_tasks (id bigint PRIMARY KEY);
        CREATE TABLE backtest_reports (
            id bigint PRIMARY KEY,
            task_id bigint NOT NULL REFERENCES backtest_tasks(id) ON DELETE CASCADE
        );
        CREATE TABLE backtest_trades (
            id bigint PRIMARY KEY,
            report_id bigint NOT NULL REFERENCES backtest_reports(id) ON DELETE CASCADE
        );
        CREATE TABLE backtest_orders (
            id bigint PRIMARY KEY,
            report_id bigint NOT NULL REFERENCES backtest_reports(id) ON DELETE CASCADE
        );
        CREATE TABLE shared_sentinel (id bigint PRIMARY KEY);
        """
    )


def _seed_shared_rows(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        INSERT INTO strategy_signals (
            id, dedupe_key, strategy_name, strategy_version, symbol, product,
            contract, actual_contract, exchange, period, provider, source, status,
            spec_source, dominant_mapping_date, direction
        ) VALUES (
            99, 'shared-signal', 'task06_shared', 'v1', 'rb', 'rb', 'RB2610',
            'RB2610', 'SHFE', '15m', 'rqdata', 'task06', 'recorded',
            'task06', DATE '2026-08-05', 'long'
        );
        INSERT INTO signal_events (
            id, event_key, event_type, signal_id, decision_id, source_mode,
            strategy_name, strategy_version, symbol, product, contract,
            actual_contract, dominant_mapping_date, exchange, period, source,
            signal_status
        ) VALUES (
            99, 'shared-event', 'signal_created', 99, 42, 'historical_confirmed',
            'task06_shared', 'v1', 'rb', 'rb', 'RB2610', 'RB2610',
            DATE '2026-08-05', 'SHFE', '15m', 'task06', 'recorded'
        );
        INSERT INTO signal_notifications
            (id, event_id, signal_id, dedupe_key, event_type, channel, status)
        VALUES (99, 99, 99, 'shared-notification', 'signal_created', 'websocket', 'pending');
        INSERT INTO review_notes (id, source_type, source_id)
        VALUES (99, 'strategy_signal', 99);
        INSERT INTO shared_sentinel VALUES (1);
        """
    )


def _seed_exact_production_baseline(engine: Engine, schema: str) -> None:
    with engine.begin() as connection:
        _set_search_path(connection, schema)
        connection.exec_driver_sql(
            """
            INSERT INTO backtest_tasks SELECT generate_series(1, 23);
            INSERT INTO backtest_reports
            SELECT report_id, report_id FROM generate_series(1, 15) AS report_id;
            INSERT INTO backtest_trades
            SELECT trade_id, ((trade_id - 1) %% 15) + 1
            FROM generate_series(1, 4361) AS trade_id;
            INSERT INTO backtest_orders
            SELECT order_id, ((order_id - 1) %% 15) + 1
            FROM generate_series(1, 4225) AS order_id;
            INSERT INTO review_notes
            SELECT review_id, 'backtest_trade', review_id
            FROM generate_series(1, 7) AS review_id;

            INSERT INTO strategy_signals (
                id, dedupe_key, strategy_name, strategy_version, symbol, product,
                contract, actual_contract, exchange, period, provider, source,
                status, spec_source, dominant_mapping_date, direction
            ) VALUES
                (1, 'htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f',
                 'htdy_original_realtime_first_seen', 'v1.0', 'jm', 'jm', 'JM2609',
                 'JM2609', 'DCE', '15m', 'rqdata', 'htdy_realtime_snapshot',
                 'entry_signal', 'htdy_original_xma_15m_first_seen_v1', DATE '2026-07-28', 'long'),
                (2, 'htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5',
                 'htdy_original_realtime_first_seen', 'v1.1', 'jm', 'jm', 'JM2609',
                 'JM2609', 'DCE', '15m', 'rqdata', 'htdy_realtime_snapshot',
                 'entry_signal', 'htdy_original_xma_15m_close_first_seen_v1', DATE '2026-07-29', 'long'),
                (3, 'htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee',
                 'htdy_original_realtime_first_seen', 'v1.1', 'jm', 'jm', 'JM2609',
                 'JM2609', 'DCE', '15m', 'rqdata', 'htdy_realtime_snapshot',
                 'entry_signal', 'htdy_original_xma_15m_close_first_seen_v1', DATE '2026-07-29', 'short');

            INSERT INTO signal_events (
                id, event_key, event_type, signal_id, decision_id, source_mode,
                strategy_name, strategy_version, symbol, product, contract,
                actual_contract, dominant_mapping_date, exchange, period, source,
                signal_status
            ) VALUES
                (4, 'signal_created:htdy-first-seen:15d699aaeaf52f28ed2098e82d0cf23574f150af32a82fe213fc032ed397619f:created',
                 'signal_created', 1, NULL, 'live_realtime_repainting',
                 'htdy_original_realtime_first_seen', 'v1.0', 'jm', 'jm', 'JM2609',
                 'JM2609', DATE '2026-07-28', 'DCE', '15m', 'htdy_realtime_snapshot', 'entry_signal'),
                (5, 'signal_created:htdy-first-seen:b153ac90ad2de288eac5d31de352cada0e3adfdc1d72eaee6ad6315b452e88f5:created',
                 'signal_created', 2, NULL, 'live_realtime_repainting',
                 'htdy_original_realtime_first_seen', 'v1.1', 'jm', 'jm', 'JM2609',
                 'JM2609', DATE '2026-07-29', 'DCE', '15m', 'htdy_realtime_snapshot', 'entry_signal'),
                (6, 'signal_created:htdy-first-seen:7baac25bf5fecd8af83fa7ff798f7da64c6c479e50cda3fca259148e3520acee:created',
                 'signal_created', 3, NULL, 'live_realtime_repainting',
                 'htdy_original_realtime_first_seen', 'v1.1', 'jm', 'jm', 'JM2609',
                 'JM2609', DATE '2026-07-29', 'DCE', '15m', 'htdy_realtime_snapshot', 'entry_signal');

            INSERT INTO signal_notifications
                (id, event_id, signal_id, dedupe_key, event_type, channel, status)
            VALUES (4, 4, 1, 'enterprise_wechat:signal_event:4',
                    'signal_created', 'enterprise_wechat', 'sent');
            """
        )
