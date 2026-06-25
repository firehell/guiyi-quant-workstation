"""rqdata structured ingest

Revision ID: 20260624_0005
Revises: 20260624_0004
Create Date: 2026-06-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260624_0005"
down_revision: Union[str, Sequence[str], None] = "20260624_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contracts", sa.Column("contract_multiplier", sa.Integer(), nullable=True))
    op.add_column("contracts", sa.Column("trading_code", sa.String(length=64), nullable=True))
    op.add_column("contracts", sa.Column("maturity_date", sa.Date(), nullable=True))
    op.add_column("contracts", sa.Column("start_delivery_date", sa.Date(), nullable=True))
    op.add_column("contracts", sa.Column("end_delivery_date", sa.Date(), nullable=True))
    op.add_column("contracts", sa.Column("product", sa.String(length=32), nullable=True))
    op.add_column("contracts", sa.Column("trading_hours", sa.Text(), nullable=True))
    op.create_index("ix_contracts_trading_code", "contracts", ["trading_code"])
    op.create_index("ix_contracts_product", "contracts", ["product"])

    op.create_table(
        "main_contract_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("instrument_symbol", "trade_date", "rank", "rule", "provider", "data_version", name="uq_main_contract_map_rank_version"),
    )
    op.create_index("ix_main_contract_map_instrument_symbol", "main_contract_map", ["instrument_symbol"])
    op.create_index("ix_main_contract_map_trade_date", "main_contract_map", ["trade_date"])
    op.create_index("ix_main_contract_map_rank", "main_contract_map", ["rank"])
    op.create_index("ix_main_contract_map_contract_code", "main_contract_map", ["contract_code"])
    op.create_index("ix_main_contract_map_rule", "main_contract_map", ["rule"])
    op.create_index("ix_main_contract_map_provider", "main_contract_map", ["provider"])
    op.create_index("ix_main_contract_map_data_version", "main_contract_map", ["data_version"])

    op.create_table(
        "futures_ex_factors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=True),
        sa.Column("prev_close_spread", sa.Numeric(18, 8), nullable=True),
        sa.Column("open_spread", sa.Numeric(18, 8), nullable=True),
        sa.Column("prev_close_ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("open_ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("instrument_symbol", "trade_date", "contract_code", "provider", "data_version", name="uq_futures_ex_factors_version"),
    )
    op.create_index("ix_futures_ex_factors_instrument_symbol", "futures_ex_factors", ["instrument_symbol"])
    op.create_index("ix_futures_ex_factors_trade_date", "futures_ex_factors", ["trade_date"])
    op.create_index("ix_futures_ex_factors_contract_code", "futures_ex_factors", ["contract_code"])
    op.create_index("ix_futures_ex_factors_provider", "futures_ex_factors", ["provider"])
    op.create_index("ix_futures_ex_factors_data_version", "futures_ex_factors", ["data_version"])

    op.create_table(
        "futures_trading_parameters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("exchange_code", sa.String(length=16), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("long_margin_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("short_margin_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("open_commission", sa.Numeric(18, 8), nullable=True),
        sa.Column("close_commission", sa.Numeric(18, 8), nullable=True),
        sa.Column("close_today_commission", sa.Numeric(18, 8), nullable=True),
        sa.Column("commission_type", sa.String(length=32), nullable=True),
        sa.Column("price_tick", sa.Numeric(18, 6), nullable=True),
        sa.Column("contract_multiplier", sa.Integer(), nullable=True),
        sa.Column("min_order_quantity", sa.Integer(), nullable=True),
        sa.Column("max_order_quantity", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contract_code", "trade_date", "provider", "data_version", name="uq_futures_trading_parameters_version"),
    )
    for column in ["contract_code", "instrument_symbol", "exchange_code", "trade_date", "provider", "data_version"]:
        op.create_index(f"ix_futures_trading_parameters_{column}", "futures_trading_parameters", [column])

    op.create_table(
        "futures_warehouse_stocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("warehouse", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("instrument_symbol", "trade_date", "warehouse", "provider", "data_version", name="uq_futures_warehouse_stocks_version"),
    )
    for column in ["instrument_symbol", "trade_date", "warehouse", "provider", "data_version"]:
        op.create_index(f"ix_futures_warehouse_stocks_{column}", "futures_warehouse_stocks", [column])

    op.create_table(
        "futures_roll_yields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("near_contract", sa.String(length=64), nullable=True),
        sa.Column("far_contract", sa.String(length=64), nullable=True),
        sa.Column("roll_yield", sa.Numeric(18, 8), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("instrument_symbol", "trade_date", "near_contract", "far_contract", "provider", "data_version", name="uq_futures_roll_yields_version"),
    )
    for column in ["instrument_symbol", "trade_date", "near_contract", "far_contract", "provider", "data_version"]:
        op.create_index(f"ix_futures_roll_yields_{column}", "futures_roll_yields", [column])

    op.create_table(
        "futures_basis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("spot_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("futures_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("basis", sa.Numeric(18, 6), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contract_code", "trade_date", "provider", "data_version", name="uq_futures_basis_version"),
    )
    for column in ["contract_code", "instrument_symbol", "trade_date", "provider", "data_version"]:
        op.create_index(f"ix_futures_basis_{column}", "futures_basis", [column])


def downgrade() -> None:
    op.drop_table("futures_basis")
    op.drop_table("futures_roll_yields")
    op.drop_table("futures_warehouse_stocks")
    op.drop_table("futures_trading_parameters")
    op.drop_table("futures_ex_factors")
    op.drop_table("main_contract_map")

    op.drop_index("ix_contracts_product", table_name="contracts")
    op.drop_index("ix_contracts_trading_code", table_name="contracts")
    op.drop_column("contracts", "trading_hours")
    op.drop_column("contracts", "product")
    op.drop_column("contracts", "end_delivery_date")
    op.drop_column("contracts", "start_delivery_date")
    op.drop_column("contracts", "maturity_date")
    op.drop_column("contracts", "trading_code")
    op.drop_column("contracts", "contract_multiplier")
