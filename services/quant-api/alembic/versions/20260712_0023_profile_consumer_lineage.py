"""profile consumer lineage fields

Revision ID: 20260712_0023
Revises: 20260712_0022
Create Date: 2026-07-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260712_0023"
down_revision = "20260712_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backtest_tasks", sa.Column("profile_id", sa.String(length=64), nullable=True))
    op.add_column("backtest_tasks", sa.Column("market_data_file_id", sa.Integer(), nullable=True))
    op.create_index("ix_backtest_tasks_profile_id", "backtest_tasks", ["profile_id"])
    op.create_index("ix_backtest_tasks_market_data_file_id", "backtest_tasks", ["market_data_file_id"])

    op.add_column("backtest_reports", sa.Column("profile_id", sa.String(length=64), nullable=True))
    op.add_column("backtest_reports", sa.Column("market_data_file_id", sa.Integer(), nullable=True))
    op.create_index("ix_backtest_reports_profile_id", "backtest_reports", ["profile_id"])
    op.create_index("ix_backtest_reports_market_data_file_id", "backtest_reports", ["market_data_file_id"])

    op.add_column("signal_scan_tasks", sa.Column("profile_id", sa.String(length=64), nullable=True))
    op.add_column("signal_scan_tasks", sa.Column("market_data_file_id", sa.Integer(), nullable=True))
    op.create_index("ix_signal_scan_tasks_profile_id", "signal_scan_tasks", ["profile_id"])
    op.create_index("ix_signal_scan_tasks_market_data_file_id", "signal_scan_tasks", ["market_data_file_id"])

    op.add_column("strategy_signals", sa.Column("profile_id", sa.String(length=64), nullable=True))
    op.add_column("strategy_signals", sa.Column("market_data_file_id", sa.Integer(), nullable=True))
    op.create_index("ix_strategy_signals_profile_id", "strategy_signals", ["profile_id"])
    op.create_index("ix_strategy_signals_market_data_file_id", "strategy_signals", ["market_data_file_id"])

    op.add_column("signal_events", sa.Column("profile_id", sa.String(length=64), nullable=True))
    op.add_column("signal_events", sa.Column("market_data_file_id", sa.Integer(), nullable=True))
    op.create_index("ix_signal_events_profile_id", "signal_events", ["profile_id"])
    op.create_index("ix_signal_events_market_data_file_id", "signal_events", ["market_data_file_id"])


def downgrade() -> None:
    op.drop_index("ix_signal_events_market_data_file_id", table_name="signal_events")
    op.drop_index("ix_signal_events_profile_id", table_name="signal_events")
    op.drop_column("signal_events", "market_data_file_id")
    op.drop_column("signal_events", "profile_id")

    op.drop_index("ix_strategy_signals_market_data_file_id", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_profile_id", table_name="strategy_signals")
    op.drop_column("strategy_signals", "market_data_file_id")
    op.drop_column("strategy_signals", "profile_id")

    op.drop_index("ix_signal_scan_tasks_market_data_file_id", table_name="signal_scan_tasks")
    op.drop_index("ix_signal_scan_tasks_profile_id", table_name="signal_scan_tasks")
    op.drop_column("signal_scan_tasks", "market_data_file_id")
    op.drop_column("signal_scan_tasks", "profile_id")

    op.drop_index("ix_backtest_reports_market_data_file_id", table_name="backtest_reports")
    op.drop_index("ix_backtest_reports_profile_id", table_name="backtest_reports")
    op.drop_column("backtest_reports", "market_data_file_id")
    op.drop_column("backtest_reports", "profile_id")

    op.drop_index("ix_backtest_tasks_market_data_file_id", table_name="backtest_tasks")
    op.drop_index("ix_backtest_tasks_profile_id", table_name="backtest_tasks")
    op.drop_column("backtest_tasks", "market_data_file_id")
    op.drop_column("backtest_tasks", "profile_id")
