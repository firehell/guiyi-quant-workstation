from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20261008_0049_subing_signal_alignment.py"
    )
    spec = importlib.util.spec_from_file_location("subing_multiperiod_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "enabled,scope",
    [(True, {"jm": ["15m"], "rb": ["15m"]}), (False, {}), (True, {"jm": [["15m"]]})],
)
def test_isolated_postgres_upgrade_preserves_events_and_other_rule(
    isolated_postgres_engine, enabled, scope
):
    engine = isolated_postgres_engine
    schema = "subing_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(
            sa.text(
                "CREATE TABLE alert_rules (id integer PRIMARY KEY, rule_code text, enabled boolean, scope_product_frequencies json)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE alert_events (id integer PRIMARY KEY, rule_id integer REFERENCES alert_rules(id), fact text)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO alert_rules VALUES (1, 'subing_ths_alert_15m_v1', :enabled, CAST(:scope AS json)), (2, 'htdy_original_15m', true, '{\"jm\":[\"15m\"]}')"
            ),
            {"enabled": enabled, "scope": json.dumps(scope)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO alert_events VALUES (100, 1, 'legacy'), (101, 2, 'htdy')"
            )
        )
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
                module = migration()
                module.op = Operations(MigrationContext.configure(connection))
                if scope == {"jm": [["15m"]]}:
                    with pytest.raises(RuntimeError, match="PREFLIGHT_FAILED"):
                        module.upgrade()
                else:
                    module.upgrade()
                stored = connection.execute(
                    sa.text(
                        "SELECT scope_product_frequencies FROM alert_rules WHERE id=1"
                    )
                ).scalar_one()
                assert stored == (
                    {symbol: module.FREQUENCIES for symbol in scope}
                    if enabled and scope != {"jm": [["15m"]]}
                    else scope
                )
                assert connection.execute(
                    sa.text(
                        "SELECT scope_product_frequencies FROM alert_rules WHERE id=2"
                    )
                ).scalar_one() == {"jm": ["15m"]}
                assert connection.execute(
                    sa.text("SELECT id, fact FROM alert_events ORDER BY id")
                ).all() == [(100, "legacy"), (101, "htdy")]
                if scope != {"jm": [["15m"]]}:
                    connection.execute(
                        sa.text(
                            "INSERT INTO subing_signal_alignments VALUES (100, 'subing_ema21_alignment_v1', 'PASS', '{}')"
                        )
                    )
                    assert (
                        connection.execute(
                            sa.text("SELECT event_id FROM subing_signal_alignments")
                        ).scalar_one()
                        == 100
                    )
                    with pytest.raises(RuntimeError, match="DOWNGRADE_UNSUPPORTED"):
                        module.downgrade()
                else:
                    assert (
                        connection.execute(
                            sa.text("SELECT to_regclass('subing_signal_alignments')")
                        ).scalar_one()
                        is None
                    )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.parametrize("enabled", [True, False])
def test_upgrade_source_only_expands_existing_enabled_products(enabled):
    from types import SimpleNamespace

    statements, changes = [], []
    rule = {"id": 8, "enabled": enabled, "scope_product_frequencies": {"jm": ["15m"]}}

    class Bind:
        def execute(self, statement, params=None):
            statements.append((str(statement), params))
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: rule)
            )

    bind = Bind()
    module = migration()
    module.op = SimpleNamespace(
        execute=lambda statement: statements.append((statement, None)),
        get_bind=lambda: bind,
        create_table=lambda name, *args: changes.append(name),
        create_index=lambda *args: changes.append(args[1]),
    )
    module.upgrade()
    assert changes == ["subing_signal_alignments", "subing_signal_alignments"]
    updates = [
        params for statement, params in statements if statement.startswith("UPDATE")
    ]
    if enabled:
        assert len(updates) == 1
        assert updates[0]["id"] == 8
        assert json.loads(updates[0]["scope"]) == {"jm": module.FREQUENCIES}
    else:
        assert updates == []
    assert all("DELETE" not in statement for statement, _ in statements)
