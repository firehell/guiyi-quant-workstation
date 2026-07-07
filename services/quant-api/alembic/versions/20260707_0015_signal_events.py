"""signal events append-only table

Revision ID: 20260707_0015
Revises: 20260707_0014
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260707_0015"
down_revision = "20260707_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(length=240), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("task_no", sa.String(length=64), nullable=True),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("watchlist_code", sa.String(length=32), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("signal_status", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("score_bucket", sa.Integer(), nullable=False),
        sa.Column("data_role", sa.String(length=32), nullable=False),
        sa.Column("quality_status", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_key", name="uq_signal_events_event_key"),
    )
    for column in (
        "event_key",
        "event_type",
        "signal_id",
        "task_no",
        "source_mode",
        "strategy_name",
        "strategy_version",
        "watchlist_code",
        "symbol",
        "contract",
        "exchange",
        "period",
        "signal_time",
        "direction",
        "signal_status",
        "lifecycle_status",
        "score_bucket",
        "data_role",
        "created_at",
    ):
        op.create_index(f"ix_signal_events_{column}", "signal_events", [column])
    op.create_index("ix_signal_events_symbol_period_time", "signal_events", ["symbol", "period", "signal_time"])
    op.create_index("ix_signal_events_type_source_time", "signal_events", ["event_type", "source_mode", "created_at"])


def downgrade() -> None:
    op.drop_table("signal_events")
