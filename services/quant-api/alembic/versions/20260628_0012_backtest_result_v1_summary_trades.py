"""backtest result v1 summary and trades

Revision ID: 20260628_0012
Revises: 20260628_0011
Create Date: 2026-06-28 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260628_0012"
down_revision = "20260628_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_reports", sa.Column("consistency_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_backtest_reports_consistency_hash", "backtest_reports", ["consistency_hash"])

    op.add_column("backtest_trades", sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("backtest_trades", sa.Column("exchange", sa.String(length=16), nullable=False, server_default=""))
    op.add_column("backtest_trades", sa.Column("research_contract", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("backtest_trades", sa.Column("timeframe", sa.String(length=16), nullable=False, server_default=""))
    op.add_column("backtest_trades", sa.Column("entry_signal_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_trades", sa.Column("exit_signal_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_trades", sa.Column("stop_loss_price", sa.Float(), nullable=True))
    op.create_index("ix_backtest_trades_sequence", "backtest_trades", ["sequence"])
    op.create_index("ix_backtest_trades_exchange", "backtest_trades", ["exchange"])
    op.create_index("ix_backtest_trades_research_contract", "backtest_trades", ["research_contract"])
    op.create_index("ix_backtest_trades_timeframe", "backtest_trades", ["timeframe"])
    op.create_index("ix_backtest_trades_entry_signal_time", "backtest_trades", ["entry_signal_time"])
    op.create_index("ix_backtest_trades_exit_signal_time", "backtest_trades", ["exit_signal_time"])

    op.drop_index("ix_backtest_drawdown_curve_point_time", table_name="backtest_drawdown_curve")
    op.drop_index("ix_backtest_drawdown_curve_point_index", table_name="backtest_drawdown_curve")
    op.drop_index("ix_backtest_drawdown_curve_report_id", table_name="backtest_drawdown_curve")
    op.drop_table("backtest_drawdown_curve")
    op.drop_index("ix_backtest_equity_curve_point_time", table_name="backtest_equity_curve")
    op.drop_index("ix_backtest_equity_curve_point_index", table_name="backtest_equity_curve")
    op.drop_index("ix_backtest_equity_curve_report_id", table_name="backtest_equity_curve")
    op.drop_table("backtest_equity_curve")

    op.drop_index("ix_backtest_reports_trade_count", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_max_drawdown", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_total_return", table_name="backtest_reports")
    with op.batch_alter_table("backtest_reports") as batch_op:
        for column in (
            "delivery_risk_exit_count",
            "rollover_exit_count",
            "max_margin_usage_pct",
            "max_margin_required",
            "max_drawdown_pct",
            "max_drawdown_amount",
            "total_slippage",
            "total_commission",
            "max_consecutive_losses",
            "trade_count",
            "profit_loss_ratio",
            "win_rate",
            "max_drawdown",
            "annual_return",
            "total_return",
            "final_equity",
            "initial_capital",
            "quality_status",
            "drawdown_curve",
            "equity_curve",
            "fills",
            "orders",
        ):
            batch_op.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("backtest_reports") as batch_op:
        batch_op.add_column(sa.Column("orders", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("fills", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("equity_curve", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("drawdown_curve", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("quality_status", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("initial_capital", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("final_equity", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_return", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("annual_return", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("max_drawdown", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("win_rate", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("profit_loss_ratio", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("max_consecutive_losses", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_commission", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_slippage", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("max_drawdown_amount", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("max_drawdown_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("max_margin_required", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("max_margin_usage_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("rollover_exit_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("delivery_risk_exit_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_backtest_reports_total_return", "backtest_reports", ["total_return"])
    op.create_index("ix_backtest_reports_max_drawdown", "backtest_reports", ["max_drawdown"])
    op.create_index("ix_backtest_reports_trade_count", "backtest_reports", ["trade_count"])

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

    op.drop_index("ix_backtest_trades_exit_signal_time", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_entry_signal_time", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_timeframe", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_research_contract", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_exchange", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_sequence", table_name="backtest_trades")
    for column in (
        "stop_loss_price",
        "exit_signal_time",
        "entry_signal_time",
        "timeframe",
        "research_contract",
        "exchange",
        "sequence",
    ):
        op.drop_column("backtest_trades", column)

    op.drop_index("ix_backtest_reports_consistency_hash", table_name="backtest_reports")
    op.drop_column("backtest_reports", "consistency_hash")
