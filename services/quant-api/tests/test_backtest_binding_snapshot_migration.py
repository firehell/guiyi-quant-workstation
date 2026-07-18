from __future__ import annotations

import os
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def _isolated_postgres_url() -> str | None:
    url = os.getenv("GUIYI_ISOLATED_MIGRATION_DATABASE_URL")
    if not url or "postgresql" not in url:
        return None
    database = (make_url(url).database or "").lower()
    if "test" not in database and "isolated" not in database:
        pytest.fail("GUIYI_ISOLATED_MIGRATION_DATABASE_URL must name an isolated/test database")
    return url


def _rows(engine: Any, table: str, columns: list[str], where: str) -> list[tuple[Any, ...]]:
    selected = ", ".join(f'"{column}"' for column in columns)
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(f'SELECT {selected} FROM "{table}" {where}'))]


@pytest.mark.skipif(
    _isolated_postgres_url() is None,
    reason="GUIYI_ISOLATED_MIGRATION_DATABASE_URL with isolated PostgreSQL is required",
)
def test_backtest_binding_snapshot_0023_head_0023_roundtrip_preserves_report_14() -> None:
    """Exercise the destructive roundtrip only against an explicitly isolated database."""

    url = _isolated_postgres_url()
    assert url is not None
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)

    try:
        command.downgrade(config, "20260712_0023")
        inspector = inspect(engine)
        report_columns = [column["name"] for column in inspector.get_columns("backtest_reports")]
        assert "binding_snapshot" not in report_columns
        before_report = _rows(engine, "backtest_reports", report_columns, "WHERE id = 14")
        before_trades = _rows(
            engine,
            "backtest_trades",
            [column["name"] for column in inspector.get_columns("backtest_trades")],
            "WHERE report_id = 14 ORDER BY id",
        )
        before_orders = _rows(
            engine,
            "backtest_orders",
            [column["name"] for column in inspector.get_columns("backtest_orders")],
            "WHERE report_id = 14 ORDER BY id",
        )

        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert "binding_snapshot" in {column["name"] for column in inspector.get_columns("backtest_reports")}
        assert "binding_snapshot" in {column["name"] for column in inspector.get_columns("backtest_tasks")}
        assert _rows(engine, "backtest_reports", report_columns, "WHERE id = 14") == before_report
        assert _rows(
            engine,
            "backtest_trades",
            [column["name"] for column in inspector.get_columns("backtest_trades")],
            "WHERE report_id = 14 ORDER BY id",
        ) == before_trades
        assert _rows(
            engine,
            "backtest_orders",
            [column["name"] for column in inspector.get_columns("backtest_orders")],
            "WHERE report_id = 14 ORDER BY id",
        ) == before_orders
        with engine.connect() as connection:
            if before_report:
                assert connection.execute(
                    text("SELECT binding_snapshot IS NULL FROM backtest_reports WHERE id = 14")
                ).scalar_one()

        command.downgrade(config, "20260712_0023")
        inspector = inspect(engine)
        assert "binding_snapshot" not in {column["name"] for column in inspector.get_columns("backtest_reports")}
        assert "binding_snapshot" not in {column["name"] for column in inspector.get_columns("backtest_tasks")}
    finally:
        command.upgrade(config, "head")
        engine.dispose()
