"""Migrate the Alert application domain from V1 to V2.

Revision ID: 20260814_0038
Revises: 20260813_0037
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260814_0038"
down_revision: str | Sequence[str] | None = "20260813_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EVENT_IDENTITY_COLLISION_QUERY = """SELECT rule_id, symbol, bar_end, COUNT(*) AS n
FROM alert_events
GROUP BY rule_id, symbol, bar_end
HAVING COUNT(*) > 1
LIMIT 1"""


def upgrade() -> None:
    collision = op.get_bind().execute(
        sa.text(_EVENT_IDENTITY_COLLISION_QUERY)
    ).first()
    if collision is not None:
        raise RuntimeError("ALERT_V2_EVENT_IDENTITY_CONFLICT")

    op.drop_constraint(
        "ck_alert_rules_frequency",
        "alert_rules",
        type_="check",
    )
    op.drop_constraint(
        "ck_alert_rules_scope_mode",
        "alert_rules",
        type_="check",
    )
    op.drop_column("alert_rules", "indicator_code")
    op.drop_column("alert_rules", "frequency")
    op.drop_column("alert_rules", "scope_mode")

    op.drop_constraint(
        "ck_alert_events_observation_types",
        "alert_events",
        type_="check",
    )
    op.alter_column(
        "alert_events",
        "observation_types",
        new_column_name="result_codes",
    )
    op.alter_column(
        "alert_events",
        "notified_at",
        new_column_name="notification_attempted_at",
    )
    op.add_column(
        "alert_events",
        sa.Column("trading_day", sa.Date(), nullable=True),
    )
    op.add_column(
        "alert_events",
        sa.Column(
            "lower_tf_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.drop_constraint(
        "uq_alert_events_rule_symbol_frequency_bar_end",
        "alert_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_alert_events_rule_symbol_bar_end",
        "alert_events",
        ["rule_id", "symbol", "bar_end"],
    )
    op.create_check_constraint(
        "ck_alert_events_result_codes",
        "alert_events",
        "cardinality(result_codes) BETWEEN 1 AND 2 "
        "AND result_codes <@ ARRAY['buy','sell']::varchar[]",
    )

    rule_table = sa.table(
        "alert_rules",
        sa.column("rule_code", sa.String(64)),
        sa.column("enabled", sa.Boolean()),
        sa.column("scope_products", postgresql.ARRAY(sa.String(32))),
    )
    op.bulk_insert(
        rule_table,
        [
            {
                "rule_code": "subing_entry_signal_v1",
                "enabled": True,
                "scope_products": [],
            }
        ],
    )


def downgrade() -> None:
    raise RuntimeError("ALERT_V2_DOWNGRADE_UNSUPPORTED")
