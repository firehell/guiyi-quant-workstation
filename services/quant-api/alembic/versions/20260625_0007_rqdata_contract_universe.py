"""add rqdata contract universe and continuous maps

Revision ID: 20260625_0007
Revises: 20260625_0006
Create Date: 2026-06-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0007"
down_revision: Union[str, Sequence[str], None] = "20260625_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "futures_contract_universe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "contract_code",
            "provider",
            "data_version",
            name="uq_futures_contract_universe_version",
        ),
    )
    op.create_index("ix_futures_contract_universe_instrument_symbol", "futures_contract_universe", ["instrument_symbol"])
    op.create_index("ix_futures_contract_universe_trade_date", "futures_contract_universe", ["trade_date"])
    op.create_index("ix_futures_contract_universe_contract_code", "futures_contract_universe", ["contract_code"])
    op.create_index("ix_futures_contract_universe_provider", "futures_contract_universe", ["provider"])
    op.create_index("ix_futures_contract_universe_data_version", "futures_contract_universe", ["data_version"])

    op.create_table(
        "futures_continuous_contract_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("continuous_type", sa.String(length=32), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "continuous_type",
            "provider",
            "data_version",
            name="uq_futures_continuous_contract_map_version",
        ),
    )
    op.create_index("ix_futures_continuous_contract_map_instrument_symbol", "futures_continuous_contract_map", ["instrument_symbol"])
    op.create_index("ix_futures_continuous_contract_map_trade_date", "futures_continuous_contract_map", ["trade_date"])
    op.create_index("ix_futures_continuous_contract_map_continuous_type", "futures_continuous_contract_map", ["continuous_type"])
    op.create_index("ix_futures_continuous_contract_map_contract_code", "futures_continuous_contract_map", ["contract_code"])
    op.create_index("ix_futures_continuous_contract_map_provider", "futures_continuous_contract_map", ["provider"])
    op.create_index("ix_futures_continuous_contract_map_data_version", "futures_continuous_contract_map", ["data_version"])


def downgrade() -> None:
    op.drop_index("ix_futures_continuous_contract_map_data_version", table_name="futures_continuous_contract_map")
    op.drop_index("ix_futures_continuous_contract_map_provider", table_name="futures_continuous_contract_map")
    op.drop_index("ix_futures_continuous_contract_map_contract_code", table_name="futures_continuous_contract_map")
    op.drop_index("ix_futures_continuous_contract_map_continuous_type", table_name="futures_continuous_contract_map")
    op.drop_index("ix_futures_continuous_contract_map_trade_date", table_name="futures_continuous_contract_map")
    op.drop_index("ix_futures_continuous_contract_map_instrument_symbol", table_name="futures_continuous_contract_map")
    op.drop_table("futures_continuous_contract_map")

    op.drop_index("ix_futures_contract_universe_data_version", table_name="futures_contract_universe")
    op.drop_index("ix_futures_contract_universe_provider", table_name="futures_contract_universe")
    op.drop_index("ix_futures_contract_universe_contract_code", table_name="futures_contract_universe")
    op.drop_index("ix_futures_contract_universe_trade_date", table_name="futures_contract_universe")
    op.drop_index("ix_futures_contract_universe_instrument_symbol", table_name="futures_contract_universe")
    op.drop_table("futures_contract_universe")
