"""backtest lineage mapping fields

Revision ID: 20260709_0019
Revises: 20260708_0018
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260709_0019"
down_revision = "20260708_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_trades", sa.Column("entry_signal_source", sa.String(length=64), nullable=True))
    op.add_column("backtest_trades", sa.Column("entry_order_no", sa.String(length=64), nullable=True))
    op.add_column("backtest_trades", sa.Column("exit_signal_source", sa.String(length=64), nullable=True))
    op.add_column("backtest_trades", sa.Column("exit_order_no", sa.String(length=64), nullable=True))
    op.add_column("backtest_trades", sa.Column("lineage_status", sa.String(length=32), nullable=True))

    op.add_column("backtest_orders", sa.Column("trade_no", sa.String(length=64), nullable=True))
    op.add_column("backtest_orders", sa.Column("leg", sa.String(length=16), nullable=True))
    op.add_column("backtest_orders", sa.Column("lineage_source", sa.String(length=64), nullable=True))
    op.add_column("backtest_orders", sa.Column("mapping_status", sa.String(length=32), nullable=True))

    op.create_index("ix_backtest_trades_entry_signal_source", "backtest_trades", ["entry_signal_source"])
    op.create_index("ix_backtest_trades_entry_order_no", "backtest_trades", ["entry_order_no"])
    op.create_index("ix_backtest_trades_exit_signal_source", "backtest_trades", ["exit_signal_source"])
    op.create_index("ix_backtest_trades_exit_order_no", "backtest_trades", ["exit_order_no"])
    op.create_index("ix_backtest_trades_lineage_status", "backtest_trades", ["lineage_status"])
    op.create_index("ix_backtest_orders_trade_no", "backtest_orders", ["trade_no"])
    op.create_index("ix_backtest_orders_leg", "backtest_orders", ["leg"])
    op.create_index("ix_backtest_orders_lineage_source", "backtest_orders", ["lineage_source"])
    op.create_index("ix_backtest_orders_mapping_status", "backtest_orders", ["mapping_status"])


def downgrade() -> None:
    op.drop_index("ix_backtest_orders_mapping_status", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_lineage_source", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_leg", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_trade_no", table_name="backtest_orders")
    op.drop_index("ix_backtest_trades_lineage_status", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_exit_order_no", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_exit_signal_source", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_entry_order_no", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_entry_signal_source", table_name="backtest_trades")

    op.drop_column("backtest_orders", "mapping_status")
    op.drop_column("backtest_orders", "lineage_source")
    op.drop_column("backtest_orders", "leg")
    op.drop_column("backtest_orders", "trade_no")

    op.drop_column("backtest_trades", "lineage_status")
    op.drop_column("backtest_trades", "exit_order_no")
    op.drop_column("backtest_trades", "exit_signal_source")
    op.drop_column("backtest_trades", "entry_order_no")
    op.drop_column("backtest_trades", "entry_signal_source")
