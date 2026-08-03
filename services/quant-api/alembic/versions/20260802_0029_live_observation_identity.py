"""include revision and confirmed in immutable live observation identity

Revision ID: 20260802_0029
Revises: 20260802_0028
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_0029"
down_revision = "20260802_0028"
branch_labels = None
depends_on = None


_BASE_IDENTITY = (
    "provider",
    "source_mode",
    "actual_contract",
    "period",
    "trading_day",
    "bar_end",
)
_FULL_IDENTITY = (*_BASE_IDENTITY, "revision", "confirmed")


def upgrade() -> None:
    op.drop_constraint(
        "uq_live_observation_bars_natural_key",
        "live_observation_bars",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_live_observation_bars_natural_key",
        "live_observation_bars",
        _FULL_IDENTITY,
    )
    op.create_check_constraint(
        "ck_live_observation_source_contract",
        "live_observation_bars",
        "(period = '1m' AND source_mode = 'rqdata_live_1m_v2' AND source_bar_count = 1) OR "
        "(period = '15m' AND source_mode = 'session_aggregate_15m_v2' AND source_bar_count = 15)",
    )
    op.create_check_constraint(
        "ck_live_observation_source_end",
        "live_observation_bars",
        sa.column("source_end") == sa.column("bar_end"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM live_observation_bars
                GROUP BY provider, source_mode, actual_contract, period, trading_day, bar_end
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'live observation revisions must be collapsed before 20260802_0029 downgrade';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        "ck_live_observation_source_end",
        "live_observation_bars",
        type_="check",
    )
    op.drop_constraint(
        "ck_live_observation_source_contract",
        "live_observation_bars",
        type_="check",
    )
    op.drop_constraint(
        "uq_live_observation_bars_natural_key",
        "live_observation_bars",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_live_observation_bars_natural_key",
        "live_observation_bars",
        _BASE_IDENTITY,
    )
