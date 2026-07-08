"""stage9 wechat notification delivery fields

Revision ID: 20260708_0018
Revises: 20260707_0017
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260708_0018"
down_revision = "20260707_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal_notifications", sa.Column("event_id", sa.Integer(), nullable=True))
    op.add_column("signal_notifications", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("signal_notifications", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("signal_notifications", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("signal_notifications", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("signal_notifications", sa.Column("last_error_type", sa.String(length=64), nullable=True))
    op.add_column("signal_notifications", sa.Column("response_status_code", sa.Integer(), nullable=True))

    op.create_index("ix_signal_notifications_event_id", "signal_notifications", ["event_id"])
    op.create_index("ix_signal_notifications_next_retry_at", "signal_notifications", ["next_retry_at"])
    op.create_index(
        "ix_signal_notifications_retry_lookup",
        "signal_notifications",
        ["channel", "status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_signal_notifications_retry_lookup", table_name="signal_notifications")
    op.drop_index("ix_signal_notifications_next_retry_at", table_name="signal_notifications")
    op.drop_index("ix_signal_notifications_event_id", table_name="signal_notifications")

    op.drop_column("signal_notifications", "response_status_code")
    op.drop_column("signal_notifications", "last_error_type")
    op.drop_column("signal_notifications", "next_retry_at")
    op.drop_column("signal_notifications", "last_attempt_at")
    op.drop_column("signal_notifications", "max_attempts")
    op.drop_column("signal_notifications", "attempt_count")
    op.drop_column("signal_notifications", "event_id")
