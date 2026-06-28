"""backtest real contract and cost fields

Revision ID: 20260628_0011
Revises: 20260627_0010
Create Date: 2026-06-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260628_0011"
down_revision = "20260627_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_reports", sa.Column("max_drawdown_amount", sa.Float(), nullable=True))
    op.add_column("backtest_reports", sa.Column("max_drawdown_pct", sa.Float(), nullable=True))
    op.add_column("backtest_reports", sa.Column("max_margin_required", sa.Float(), nullable=True))
    op.add_column("backtest_reports", sa.Column("max_margin_usage_pct", sa.Float(), nullable=True))
    op.add_column("backtest_reports", sa.Column("rollover_exit_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("delivery_risk_exit_count", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("backtest_trades", sa.Column("entry_contract", sa.String(length=64), nullable=True))
    op.add_column("backtest_trades", sa.Column("exit_contract", sa.String(length=64), nullable=True))
    op.add_column("backtest_trades", sa.Column("entry_contract_month", sa.String(length=16), nullable=True))
    op.add_column("backtest_trades", sa.Column("exit_contract_month", sa.String(length=16), nullable=True))
    op.add_column("backtest_trades", sa.Column("contract_multiplier", sa.Integer(), nullable=True))
    op.add_column("backtest_trades", sa.Column("price_tick", sa.Float(), nullable=True))
    op.add_column("backtest_trades", sa.Column("margin_ratio", sa.Float(), nullable=True))
    op.add_column("backtest_trades", sa.Column("margin_required", sa.Float(), nullable=True))
    op.add_column("backtest_trades", sa.Column("parameter_source", sa.String(length=32), nullable=True))
    op.add_column("backtest_trades", sa.Column("fee_rule_source", sa.JSON(), nullable=True))
    op.add_column("backtest_trades", sa.Column("main_contract_source", sa.JSON(), nullable=True))
    op.add_column("backtest_trades", sa.Column("rollover_forced_exit", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("backtest_trades", sa.Column("delivery_risk_exit", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("backtest_trades", sa.Column("rollover_reason", sa.Text(), nullable=True))

    op.create_index("ix_backtest_trades_entry_contract", "backtest_trades", ["entry_contract"])
    op.create_index("ix_backtest_trades_exit_contract", "backtest_trades", ["exit_contract"])
    op.create_index("ix_backtest_trades_parameter_source", "backtest_trades", ["parameter_source"])
    op.create_index("ix_backtest_trades_rollover_forced_exit", "backtest_trades", ["rollover_forced_exit"])
    op.create_index("ix_backtest_trades_delivery_risk_exit", "backtest_trades", ["delivery_risk_exit"])


def downgrade() -> None:
    op.drop_index("ix_backtest_trades_delivery_risk_exit", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_rollover_forced_exit", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_parameter_source", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_exit_contract", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_entry_contract", table_name="backtest_trades")

    for column in (
        "rollover_reason",
        "delivery_risk_exit",
        "rollover_forced_exit",
        "main_contract_source",
        "fee_rule_source",
        "parameter_source",
        "margin_required",
        "margin_ratio",
        "price_tick",
        "contract_multiplier",
        "exit_contract_month",
        "entry_contract_month",
        "exit_contract",
        "entry_contract",
    ):
        op.drop_column("backtest_trades", column)

    for column in (
        "delivery_risk_exit_count",
        "rollover_exit_count",
        "max_margin_usage_pct",
        "max_margin_required",
        "max_drawdown_pct",
        "max_drawdown_amount",
    ):
        op.drop_column("backtest_reports", column)
