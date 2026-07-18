"""add immutable backtest binding snapshots

Revision ID: 20260718_0024
Revises: 20260712_0023
Create Date: 2026-07-18

This migration intentionally performs no backfill or UPDATE. Historical
reports, including report 14, retain null lineage fields.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260718_0024"
down_revision = "20260712_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_tasks", sa.Column("binding_snapshot", sa.JSON(), nullable=True))
    op.add_column("backtest_reports", sa.Column("binding_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_reports", "binding_snapshot")
    op.drop_column("backtest_tasks", "binding_snapshot")
