"""vnpy backtest metadata

Revision ID: 20260626_0008
Revises: 20260625_0007
Create Date: 2026-06-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_0008"
down_revision = "20260625_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_tasks", sa.Column("engine_type", sa.String(length=32), nullable=False, server_default="custom_v0"))
    op.add_column("backtest_tasks", sa.Column("vnpy_strategy_class", sa.String(length=256), nullable=True))
    op.add_column("backtest_tasks", sa.Column("vnpy_setting_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("backtest_tasks", sa.Column("data_source", sa.String(length=32), nullable=True))
    op.add_column("backtest_tasks", sa.Column("data_role", sa.String(length=32), nullable=True))
    op.add_column("backtest_tasks", sa.Column("data_version", sa.String(length=64), nullable=True))
    op.add_column("backtest_tasks", sa.Column("research_only", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("backtest_tasks", sa.Column("raw_result_path", sa.Text(), nullable=True))
    op.add_column("backtest_tasks", sa.Column("normalized_result_path", sa.Text(), nullable=True))
    op.add_column("backtest_tasks", sa.Column("error_type", sa.String(length=128), nullable=True))
    op.add_column("backtest_tasks", sa.Column("traceback", sa.Text(), nullable=True))
    op.create_index("ix_backtest_tasks_engine_type", "backtest_tasks", ["engine_type"])
    op.create_index("ix_backtest_tasks_data_source", "backtest_tasks", ["data_source"])
    op.create_index("ix_backtest_tasks_data_role", "backtest_tasks", ["data_role"])
    op.create_index("ix_backtest_tasks_data_version", "backtest_tasks", ["data_version"])
    op.create_index("ix_backtest_tasks_research_only", "backtest_tasks", ["research_only"])

    op.add_column("backtest_reports", sa.Column("engine_type", sa.String(length=32), nullable=False, server_default="custom_v0"))
    op.add_column("backtest_reports", sa.Column("engine_version", sa.String(length=64), nullable=True))
    op.add_column("backtest_reports", sa.Column("strategy_code", sa.String(length=64), nullable=True))
    op.add_column("backtest_reports", sa.Column("strategy_version", sa.String(length=64), nullable=True))
    op.add_column("backtest_reports", sa.Column("data_source", sa.String(length=32), nullable=True))
    op.add_column("backtest_reports", sa.Column("data_role", sa.String(length=32), nullable=True))
    op.add_column("backtest_reports", sa.Column("data_version", sa.String(length=64), nullable=True))
    op.add_column("backtest_reports", sa.Column("research_only", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("backtest_reports", sa.Column("initial_capital", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("final_equity", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("total_return", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("annual_return", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("max_drawdown", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("win_rate", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("profit_loss_ratio", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("max_consecutive_losses", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("total_commission", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("total_slippage", sa.Float(), nullable=False, server_default="0"))
    op.add_column("backtest_reports", sa.Column("raw_result_path", sa.Text(), nullable=True))
    op.add_column("backtest_reports", sa.Column("normalized_result_path", sa.Text(), nullable=True))
    op.add_column("backtest_reports", sa.Column("error_type", sa.String(length=128), nullable=True))
    op.add_column("backtest_reports", sa.Column("traceback", sa.Text(), nullable=True))
    op.create_index("ix_backtest_reports_engine_type", "backtest_reports", ["engine_type"])
    op.create_index("ix_backtest_reports_strategy_code", "backtest_reports", ["strategy_code"])
    op.create_index("ix_backtest_reports_strategy_version", "backtest_reports", ["strategy_version"])
    op.create_index("ix_backtest_reports_data_source", "backtest_reports", ["data_source"])
    op.create_index("ix_backtest_reports_data_role", "backtest_reports", ["data_role"])
    op.create_index("ix_backtest_reports_data_version", "backtest_reports", ["data_version"])
    op.create_index("ix_backtest_reports_research_only", "backtest_reports", ["research_only"])
    op.create_index("ix_backtest_reports_total_return", "backtest_reports", ["total_return"])
    op.create_index("ix_backtest_reports_max_drawdown", "backtest_reports", ["max_drawdown"])
    op.create_index("ix_backtest_reports_trade_count", "backtest_reports", ["trade_count"])


def downgrade() -> None:
    op.drop_index("ix_backtest_reports_trade_count", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_max_drawdown", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_total_return", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_research_only", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_data_version", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_data_role", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_data_source", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_strategy_version", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_strategy_code", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_engine_type", table_name="backtest_reports")
    for column in (
        "traceback",
        "error_type",
        "normalized_result_path",
        "raw_result_path",
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
        "research_only",
        "data_version",
        "data_role",
        "data_source",
        "strategy_version",
        "strategy_code",
        "engine_version",
        "engine_type",
    ):
        op.drop_column("backtest_reports", column)

    op.drop_index("ix_backtest_tasks_research_only", table_name="backtest_tasks")
    op.drop_index("ix_backtest_tasks_data_version", table_name="backtest_tasks")
    op.drop_index("ix_backtest_tasks_data_role", table_name="backtest_tasks")
    op.drop_index("ix_backtest_tasks_data_source", table_name="backtest_tasks")
    op.drop_index("ix_backtest_tasks_engine_type", table_name="backtest_tasks")
    for column in (
        "traceback",
        "error_type",
        "normalized_result_path",
        "raw_result_path",
        "research_only",
        "data_version",
        "data_role",
        "data_source",
        "vnpy_setting_json",
        "vnpy_strategy_class",
        "engine_type",
    ):
        op.drop_column("backtest_tasks", column)
