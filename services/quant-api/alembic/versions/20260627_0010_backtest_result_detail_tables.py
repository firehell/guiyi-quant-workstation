"""backtest result detail tables

Revision ID: 20260627_0010
Revises: 20260626_0009
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260627_0010"
down_revision = "20260626_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_trades", sa.Column("raw_payload", sa.JSON(), nullable=True))

    op.create_table(
        "backtest_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("backtest_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("offset", sa.String(length=16), nullable=True),
        sa.Column("order_type", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("order_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("traded", sa.Float(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_orders_report_id", "backtest_orders", ["report_id"])
    op.create_index("ix_backtest_orders_order_no", "backtest_orders", ["order_no"])
    op.create_index("ix_backtest_orders_symbol", "backtest_orders", ["symbol"])
    op.create_index("ix_backtest_orders_contract", "backtest_orders", ["contract"])
    op.create_index("ix_backtest_orders_direction", "backtest_orders", ["direction"])
    op.create_index("ix_backtest_orders_status", "backtest_orders", ["status"])
    op.create_index("ix_backtest_orders_order_time", "backtest_orders", ["order_time"])

    op.create_table(
        "backtest_equity_curve",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("backtest_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("point_index", sa.Integer(), nullable=False),
        sa.Column("point_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_equity_curve_report_id", "backtest_equity_curve", ["report_id"])
    op.create_index("ix_backtest_equity_curve_point_index", "backtest_equity_curve", ["point_index"])
    op.create_index("ix_backtest_equity_curve_point_time", "backtest_equity_curve", ["point_time"])

    op.create_table(
        "backtest_drawdown_curve",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("backtest_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("point_index", sa.Integer(), nullable=False),
        sa.Column("point_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.Column("drawdown_pct", sa.Float(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_drawdown_curve_report_id", "backtest_drawdown_curve", ["report_id"])
    op.create_index("ix_backtest_drawdown_curve_point_index", "backtest_drawdown_curve", ["point_index"])
    op.create_index("ix_backtest_drawdown_curve_point_time", "backtest_drawdown_curve", ["point_time"])


def downgrade() -> None:
    op.drop_index("ix_backtest_drawdown_curve_point_time", table_name="backtest_drawdown_curve")
    op.drop_index("ix_backtest_drawdown_curve_point_index", table_name="backtest_drawdown_curve")
    op.drop_index("ix_backtest_drawdown_curve_report_id", table_name="backtest_drawdown_curve")
    op.drop_table("backtest_drawdown_curve")

    op.drop_index("ix_backtest_equity_curve_point_time", table_name="backtest_equity_curve")
    op.drop_index("ix_backtest_equity_curve_point_index", table_name="backtest_equity_curve")
    op.drop_index("ix_backtest_equity_curve_report_id", table_name="backtest_equity_curve")
    op.drop_table("backtest_equity_curve")

    op.drop_index("ix_backtest_orders_order_time", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_status", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_direction", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_contract", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_symbol", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_order_no", table_name="backtest_orders")
    op.drop_index("ix_backtest_orders_report_id", table_name="backtest_orders")
    op.drop_table("backtest_orders")

    op.drop_column("backtest_trades", "raw_payload")
