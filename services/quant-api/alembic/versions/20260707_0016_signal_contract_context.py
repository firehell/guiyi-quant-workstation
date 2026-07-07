"""signal contract context columns

Revision ID: 20260707_0016
Revises: 20260707_0015
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260707_0016"
down_revision = "20260707_0015"
branch_labels = None
depends_on = None


STRATEGY_SIGNAL_COLUMNS = (
    sa.Column("product", sa.String(length=32), nullable=True),
    sa.Column("continuous_contract", sa.String(length=64), nullable=True),
    sa.Column("actual_contract", sa.String(length=64), nullable=True),
    sa.Column("dominant_mapping_date", sa.Date(), nullable=True),
    sa.Column("bar_start", sa.DateTime(timezone=True), nullable=True),
    sa.Column("bar_end", sa.DateTime(timezone=True), nullable=True),
    sa.Column("trigger_price", sa.Float(), nullable=True),
    sa.Column("provider", sa.String(length=32), nullable=True),
    sa.Column("source", sa.String(length=64), nullable=True),
    sa.Column("data_role", sa.String(length=32), nullable=False, server_default="primary"),
)

SIGNAL_EVENT_COLUMNS = (
    sa.Column("product", sa.String(length=32), nullable=True),
    sa.Column("continuous_contract", sa.String(length=64), nullable=True),
    sa.Column("actual_contract", sa.String(length=64), nullable=True),
    sa.Column("dominant_mapping_date", sa.Date(), nullable=True),
    sa.Column("bar_start", sa.DateTime(timezone=True), nullable=True),
    sa.Column("bar_end", sa.DateTime(timezone=True), nullable=True),
    sa.Column("trigger_price", sa.Float(), nullable=True),
    sa.Column("provider", sa.String(length=32), nullable=True),
    sa.Column("source", sa.String(length=64), nullable=True),
)

INDEXED_COLUMNS = ("product", "continuous_contract", "actual_contract", "provider", "source", "bar_end")


def upgrade() -> None:
    for column in STRATEGY_SIGNAL_COLUMNS:
        op.add_column("strategy_signals", column.copy())
    for column in SIGNAL_EVENT_COLUMNS:
        op.add_column("signal_events", column.copy())

    for column in INDEXED_COLUMNS:
        op.create_index(f"ix_strategy_signals_{column}", "strategy_signals", [column])
        op.create_index(f"ix_signal_events_{column}", "signal_events", [column])
    op.create_index("ix_strategy_signals_data_role", "strategy_signals", ["data_role"])


def downgrade() -> None:
    op.drop_index("ix_strategy_signals_data_role", table_name="strategy_signals")
    for column in reversed(INDEXED_COLUMNS):
        op.drop_index(f"ix_signal_events_{column}", table_name="signal_events")
        op.drop_index(f"ix_strategy_signals_{column}", table_name="strategy_signals")

    for column in reversed(SIGNAL_EVENT_COLUMNS):
        op.drop_column("signal_events", column.name)
    for column in reversed(STRATEGY_SIGNAL_COLUMNS):
        op.drop_column("strategy_signals", column.name)
