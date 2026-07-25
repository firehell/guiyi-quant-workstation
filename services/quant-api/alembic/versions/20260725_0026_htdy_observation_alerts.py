"""add HTDY original realtime observation alerts

Revision ID: 20260725_0026
Revises: 20260721_0025
Create Date: 2026-07-25

The migration is additive and performs no alert or notification backfill.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260725_0026"
down_revision = "20260721_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "htdy_observation_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_key", sa.String(length=240), nullable=False),
        sa.Column("alert_policy", sa.String(length=64), nullable=False),
        sa.Column("indicator_code", sa.String(length=64), nullable=False),
        sa.Column("indicator_version", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("continuous_contract", sa.String(length=64), nullable=False),
        sa.Column("actual_contract", sa.String(length=64), nullable=False),
        sa.Column("dominant_mapping_date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger_price", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("source_mode", sa.String(length=48), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_role", sa.String(length=32), nullable=False),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("market_data_file_id", sa.Integer(), nullable=False),
        sa.Column("live_bar_id", sa.Integer(), nullable=False),
        sa.Column("live_bar_revision", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("future_looking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("repainting_risk", sa.String(length=32), nullable=False, server_default="known"),
        sa.Column("alert_status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("notification_status", sa.String(length=32), nullable=False, server_default="not_sent"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("alert_key", name="uq_htdy_observation_alerts_alert_key"),
    )
    for column in (
        "alert_key",
        "alert_policy",
        "indicator_code",
        "indicator_version",
        "strategy_name",
        "strategy_version",
        "symbol",
        "continuous_contract",
        "actual_contract",
        "dominant_mapping_date",
        "period",
        "bar_end",
        "direction",
        "source_mode",
        "provider",
        "data_role",
        "quality_status",
        "profile_id",
        "market_data_file_id",
        "live_bar_id",
        "alert_status",
        "notification_status",
        "created_at",
    ):
        op.create_index(
            f"ix_htdy_observation_alerts_{column}",
            "htdy_observation_alerts",
            [column],
        )

    op.add_column(
        "signal_notifications",
        sa.Column("observation_alert_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "signal_notifications",
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default="signal_event",
        ),
    )
    op.create_index(
        "ix_signal_notifications_observation_alert_id",
        "signal_notifications",
        ["observation_alert_id"],
    )
    op.create_index(
        "ix_signal_notifications_source_kind",
        "signal_notifications",
        ["source_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_signal_notifications_source_kind", table_name="signal_notifications")
    op.drop_index(
        "ix_signal_notifications_observation_alert_id",
        table_name="signal_notifications",
    )
    op.drop_column("signal_notifications", "source_kind")
    op.drop_column("signal_notifications", "observation_alert_id")
    op.drop_table("htdy_observation_alerts")
