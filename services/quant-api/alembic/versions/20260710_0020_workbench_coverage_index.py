"""workbench coverage lookup index

Revision ID: 20260710_0020
Revises: 20260709_0019
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op


revision = "20260710_0020"
down_revision = "20260709_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_market_data_files_workbench_lookup",
        "market_data_files",
        ["data_role", "provider", "quality_status", "instrument_symbol", "contract_code", "period"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_market_data_files_workbench_lookup", table_name="market_data_files")
