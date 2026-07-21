"""add independent after-market scheduler checkpoint

Revision ID: 20260721_0025
Revises: 20260718_0024
Create Date: 2026-07-21

The migration is additive and intentionally performs no backfill. The first
approved S6-07 run seeds its watermark from a verified S6-06 receipt.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260721_0025"
down_revision = "20260718_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "after_market_scheduler_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product", sa.String(length=32), nullable=False),
        sa.Column("exchange_code", sa.String(length=16), nullable=False, server_default="DCE"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("authorization_hash", sa.String(length=64), nullable=False),
        sa.Column("last_successful_trading_day", sa.Date(), nullable=True),
        sa.Column("current_trading_day", sa.Date(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_type", sa.String(length=128), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_execution_packet_hash", sa.String(length=64), nullable=True),
        sa.Column("last_receipt_path", sa.Text(), nullable=True),
        sa.Column("last_result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("product", name="uq_after_market_scheduler_checkpoints_product"),
    )
    op.create_index(
        "ix_after_market_scheduler_checkpoints_product",
        "after_market_scheduler_checkpoints",
        ["product"],
    )
    op.create_index(
        "ix_after_market_scheduler_checkpoints_status",
        "after_market_scheduler_checkpoints",
        ["status"],
    )
    op.create_index(
        "ix_after_market_scheduler_checkpoints_last_successful_trading_day",
        "after_market_scheduler_checkpoints",
        ["last_successful_trading_day"],
    )
    op.create_index(
        "ix_after_market_scheduler_checkpoints_current_trading_day",
        "after_market_scheduler_checkpoints",
        ["current_trading_day"],
    )
    op.create_index(
        "ix_after_market_scheduler_checkpoints_next_retry_at",
        "after_market_scheduler_checkpoints",
        ["next_retry_at"],
    )


def downgrade() -> None:
    op.drop_table("after_market_scheduler_checkpoints")
