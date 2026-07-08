"""futures member ranks

Revision ID: 20260707_0017
Revises: 20260707_0016
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260707_0017"
down_revision = "20260707_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "futures_member_ranks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rank_by", sa.String(length=16), nullable=False),
        sa.Column("member_name", sa.String(length=128), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("volume", sa.Numeric(20, 6), nullable=True),
        sa.Column("volume_change", sa.Numeric(20, 6), nullable=True),
        sa.Column("commodity_id", sa.String(length=64), nullable=True),
        sa.Column("target_type", sa.String(length=16), nullable=False, server_default="product"),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "rank_by",
            "member_name",
            "provider",
            "data_version",
            name="uq_futures_member_ranks_version",
        ),
    )
    op.create_index("ix_futures_member_ranks_instrument_symbol", "futures_member_ranks", ["instrument_symbol"])
    op.create_index("ix_futures_member_ranks_trade_date", "futures_member_ranks", ["trade_date"])
    op.create_index("ix_futures_member_ranks_rank_by", "futures_member_ranks", ["rank_by"])
    op.create_index("ix_futures_member_ranks_member_name", "futures_member_ranks", ["member_name"])
    op.create_index("ix_futures_member_ranks_rank", "futures_member_ranks", ["rank"])
    op.create_index("ix_futures_member_ranks_provider", "futures_member_ranks", ["provider"])
    op.create_index("ix_futures_member_ranks_data_version", "futures_member_ranks", ["data_version"])
    op.create_index(
        "ix_futures_member_ranks_lookup",
        "futures_member_ranks",
        ["instrument_symbol", "trade_date", "rank_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_futures_member_ranks_lookup", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_data_version", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_provider", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_rank", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_member_name", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_rank_by", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_trade_date", table_name="futures_member_ranks")
    op.drop_index("ix_futures_member_ranks_instrument_symbol", table_name="futures_member_ranks")
    op.drop_table("futures_member_ranks")
