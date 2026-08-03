"""permit persisted aggregate-minute canonical datasets

Revision ID: 20260803_0032
Revises: 20260802_0031
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op


revision = "20260803_0032"
down_revision = "20260802_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE market_datasets IN ACCESS EXCLUSIVE MODE")
    op.drop_constraint(
        "ck_market_datasets_direct_frequency",
        "market_datasets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_market_datasets_frequency",
        "market_datasets",
        "frequency IN ('1m', '5m', '15m', '30m', '60m', '1d', '1w')",
    )
    op.create_check_constraint(
        "ck_market_datasets_actual_dominant_weekly",
        "market_datasets",
        "NOT (dataset_kind = 'actual_dominant' AND frequency = '1w')",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE market_datasets IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM market_datasets
                WHERE frequency IN ('5m', '15m', '30m', '60m')
            ) THEN
                RAISE EXCEPTION 'persisted aggregate market_datasets block 20260803_0032 downgrade';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        "ck_market_datasets_actual_dominant_weekly",
        "market_datasets",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_datasets_frequency",
        "market_datasets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_market_datasets_direct_frequency",
        "market_datasets",
        "frequency IN ('1m', '1d', '1w')",
    )
