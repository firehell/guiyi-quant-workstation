"""market data file data role

Revision ID: 20260626_0009
Revises: 20260626_0008
Create Date: 2026-06-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_0009"
down_revision = "20260626_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_data_files", sa.Column("data_role", sa.String(length=32), nullable=False, server_default="candidate"))
    op.execute(
        """
        update market_data_files
        set data_role = case
            when provider in ('rqdata', 'local_parquet') then 'primary'
            when provider in ('tqsdk', 'tq_old') then 'validation'
            when provider in ('trader_future_data', 'trader_trainer') then 'legacy_reference'
            else 'candidate'
        end
        """
    )
    op.create_index("ix_market_data_files_data_role", "market_data_files", ["data_role"])


def downgrade() -> None:
    op.drop_index("ix_market_data_files_data_role", table_name="market_data_files")
    op.drop_column("market_data_files", "data_role")
