"""Add Alert V1 application-domain tables.

Revision ID: 20260813_0037
Revises: 20260808_0036
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260813_0037"
down_revision: str | Sequence[str] | None = "20260808_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_code", sa.String(64), nullable=False, unique=True),
        sa.Column("indicator_code", sa.String(64), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("scope_mode", sa.String(32), nullable=False),
        sa.Column(
            "scope_products",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "frequency IN ('1m','5m','15m','30m','60m','1d','1w')",
            name="ck_alert_rules_frequency",
        ),
        sa.CheckConstraint(
            "scope_mode IN ('watchlist','operational_all')",
            name="ck_alert_rules_scope_mode",
        ),
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("alert_rules.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("contract", sa.String(64), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "observation_types",
            postgresql.ARRAY(sa.String(8)),
            nullable=False,
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "rule_id",
            "symbol",
            "frequency",
            "bar_end",
            name="uq_alert_events_rule_symbol_frequency_bar_end",
        ),
        sa.CheckConstraint(
            "frequency IN ('1m','5m','15m','30m','60m','1d','1w')",
            name="ck_alert_events_frequency",
        ),
        sa.CheckConstraint(
            "cardinality(observation_types) BETWEEN 1 AND 2 "
            "AND observation_types <@ ARRAY['buy','sell']::varchar[]",
            name="ck_alert_events_observation_types",
        ),
    )
    op.create_index(
        "ix_alert_events_symbol_bar_end",
        "alert_events",
        ["symbol", "bar_end"],
    )

    rule_table = sa.table(
        "alert_rules",
        sa.column("rule_code", sa.String(64)),
        sa.column("indicator_code", sa.String(64)),
        sa.column("frequency", sa.String(8)),
        sa.column("enabled", sa.Boolean()),
        sa.column("scope_mode", sa.String(32)),
        sa.column("scope_products", postgresql.ARRAY(sa.String(32))),
    )
    op.bulk_insert(
        rule_table,
        [
            {
                "rule_code": "htdy_original_15m",
                "indicator_code": "huotian_dayou_original_v0",
                "frequency": "15m",
                "enabled": True,
                "scope_mode": "watchlist",
                "scope_products": [],
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
