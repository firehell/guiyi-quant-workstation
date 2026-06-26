"""signal scanner v0

Revision ID: 20260624_0003
Revises: 20260624_0002
Create Date: 2026-06-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260624_0003"
down_revision: Union[str, Sequence[str], None] = "20260624_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_scan_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_no", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("watchlist_code", sa.String(length=32), nullable=False),
        sa.Column("periods", sa.JSON(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("skipped_items", sa.Integer(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_signal_scan_tasks_task_no", "signal_scan_tasks", ["task_no"], unique=True)
    op.create_index("ix_signal_scan_tasks_status", "signal_scan_tasks", ["status"])
    op.create_index("ix_signal_scan_tasks_watchlist_code", "signal_scan_tasks", ["watchlist_code"])
    op.create_index("ix_signal_scan_tasks_created_at", "signal_scan_tasks", ["created_at"])

    op.create_table(
        "strategy_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_no", sa.String(length=64), nullable=True),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("watchlist_code", sa.String(length=32), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("signal_level", sa.Integer(), nullable=False),
        sa.Column("score_bucket", sa.Integer(), nullable=False),
        sa.Column("bucket_label", sa.String(length=32), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("stop_loss_price", sa.Float(), nullable=True),
        sa.Column("risk_reward_ratio", sa.Float(), nullable=True),
        sa.Column("open_volume", sa.Integer(), nullable=False),
        sa.Column("margin_required", sa.Float(), nullable=False),
        sa.Column("risk_amount", sa.Float(), nullable=False),
        sa.Column("account_equity", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("quality_status", sa.JSON(), nullable=False),
        sa.Column("research_contract", sa.Boolean(), nullable=False),
        sa.Column("spec_source", sa.String(length=64), nullable=True),
        sa.Column("alert_status", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_strategy_signals_dedupe_key"),
    )
    for name, columns, unique in [
        ("ix_strategy_signals_task_no", ["task_no"], False),
        ("ix_strategy_signals_dedupe_key", ["dedupe_key"], False),
        ("ix_strategy_signals_strategy_name", ["strategy_name"], False),
        ("ix_strategy_signals_strategy_version", ["strategy_version"], False),
        ("ix_strategy_signals_watchlist_code", ["watchlist_code"], False),
        ("ix_strategy_signals_symbol", ["symbol"], False),
        ("ix_strategy_signals_contract", ["contract"], False),
        ("ix_strategy_signals_exchange", ["exchange"], False),
        ("ix_strategy_signals_period", ["period"], False),
        ("ix_strategy_signals_signal_time", ["signal_time"], False),
        ("ix_strategy_signals_status", ["status"], False),
        ("ix_strategy_signals_direction", ["direction"], False),
        ("ix_strategy_signals_signal_level", ["signal_level"], False),
        ("ix_strategy_signals_score_bucket", ["score_bucket"], False),
        ("ix_strategy_signals_bucket_label", ["bucket_label"], False),
        ("ix_strategy_signals_research_contract", ["research_contract"], False),
        ("ix_strategy_signals_alert_status", ["alert_status"], False),
        ("ix_strategy_signals_is_active", ["is_active"], False),
        ("ix_strategy_signals_created_at", ["created_at"], False),
    ]:
        op.create_index(name, "strategy_signals", columns, unique=unique)

    op.create_table(
        "signal_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("task_no", sa.String(length=64), nullable=True),
        sa.Column("dedupe_key", sa.String(length=180), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_signal_notifications_dedupe_key"),
    )
    op.create_index("ix_signal_notifications_signal_id", "signal_notifications", ["signal_id"])
    op.create_index("ix_signal_notifications_task_no", "signal_notifications", ["task_no"])
    op.create_index("ix_signal_notifications_dedupe_key", "signal_notifications", ["dedupe_key"])
    op.create_index("ix_signal_notifications_event_type", "signal_notifications", ["event_type"])
    op.create_index("ix_signal_notifications_channel", "signal_notifications", ["channel"])
    op.create_index("ix_signal_notifications_status", "signal_notifications", ["status"])
    op.create_index("ix_signal_notifications_created_at", "signal_notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("signal_notifications")
    op.drop_table("strategy_signals")
    op.drop_table("signal_scan_tasks")
