"""batch backtest v0

Revision ID: 20260624_0002
Revises: 20260623_0001
Create Date: 2026-06-24

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260624_0002"
down_revision: Union[str, Sequence[str], None] = "20260623_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WATCHLIST_ROWS = [
    {"code": "black", "name": "黑色池", "category": "futures", "description": "黑色系趋势/波段研究品种", "is_active": True},
    {"code": "chemical", "name": "化工池", "category": "futures", "description": "化工系趋势/波段研究品种", "is_active": True},
    {"code": "energy", "name": "能源池", "category": "futures", "description": "能源系趋势/波段研究品种", "is_active": True},
]

WATCHLIST_ITEM_ROWS = [
    ("black", "rb", "螺纹", "SHFE", "rb.MAIN", 10),
    ("black", "hc", "热卷", "SHFE", "hc.MAIN", 20),
    ("black", "i", "铁矿", "DCE", "i.MAIN", 30),
    ("black", "jm", "焦煤", "DCE", "jm.MAIN", 40),
    ("black", "j", "焦炭", "DCE", "j.MAIN", 50),
    ("chemical", "TA", "PTA", "CZCE", "TA.MAIN", 10),
    ("chemical", "MA", "甲醇", "CZCE", "MA.MAIN", 20),
    ("chemical", "l", "塑料", "DCE", "l.MAIN", 30),
    ("chemical", "pp", "PP", "DCE", "pp.MAIN", 40),
    ("chemical", "v", "PVC", "DCE", "v.MAIN", 50),
    ("chemical", "SA", "纯碱", "CZCE", "SA.MAIN", 60),
    ("chemical", "FG", "玻璃", "CZCE", "FG.MAIN", 70),
    ("energy", "sc", "原油", "INE", "sc.MAIN", 10),
    ("energy", "fu", "燃油", "SHFE", "fu.MAIN", 20),
    ("energy", "bu", "沥青", "SHFE", "bu.MAIN", 30),
    ("energy", "pg", "LPG", "DCE", "pg.MAIN", 40),
]


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchlists_code", "watchlists", ["code"], unique=True)
    op.create_index("ix_watchlists_category", "watchlists", ["category"])
    op.create_index("ix_watchlists_is_active", "watchlists", ["is_active"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("watchlist_code", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("exchange_code", sa.String(length=16), nullable=True),
        sa.Column("default_contract", sa.String(length=64), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["watchlist_code"], ["watchlists.code"], ondelete="CASCADE"),
        sa.UniqueConstraint("watchlist_code", "symbol", name="uq_watchlist_item_symbol"),
    )
    op.create_index("ix_watchlist_items_watchlist_code", "watchlist_items", ["watchlist_code"])
    op.create_index("ix_watchlist_items_symbol", "watchlist_items", ["symbol"])
    op.create_index("ix_watchlist_items_exchange_code", "watchlist_items", ["exchange_code"])
    op.create_index("ix_watchlist_items_default_contract", "watchlist_items", ["default_contract"])
    op.create_index("ix_watchlist_items_is_active", "watchlist_items", ["is_active"])

    op.create_table(
        "backtest_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_no", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("skipped_items", sa.Integer(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_backtest_tasks_task_no", "backtest_tasks", ["task_no"], unique=True)
    op.create_index("ix_backtest_tasks_task_type", "backtest_tasks", ["task_type"])
    op.create_index("ix_backtest_tasks_status", "backtest_tasks", ["status"])
    op.create_index("ix_backtest_tasks_created_at", "backtest_tasks", ["created_at"])

    op.create_table(
        "backtest_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_no", sa.String(length=64), nullable=False),
        sa.Column("report_no", sa.String(length=96), nullable=False),
        sa.Column("template_name", sa.String(length=64), nullable=False),
        sa.Column("template_label", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("suitability_label", sa.String(length=32), nullable=False),
        sa.Column("suitability_score", sa.Float(), nullable=False),
        sa.Column("quality_status", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("orders", sa.JSON(), nullable=False),
        sa.Column("fills", sa.JSON(), nullable=False),
        sa.Column("equity_curve", sa.JSON(), nullable=False),
        sa.Column("drawdown_curve", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["backtest_tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_backtest_reports_task_id", "backtest_reports", ["task_id"])
    op.create_index("ix_backtest_reports_task_no", "backtest_reports", ["task_no"])
    op.create_index("ix_backtest_reports_report_no", "backtest_reports", ["report_no"], unique=True)
    op.create_index("ix_backtest_reports_template_name", "backtest_reports", ["template_name"])
    op.create_index("ix_backtest_reports_symbol", "backtest_reports", ["symbol"])
    op.create_index("ix_backtest_reports_contract", "backtest_reports", ["contract"])
    op.create_index("ix_backtest_reports_period", "backtest_reports", ["period"])
    op.create_index("ix_backtest_reports_status", "backtest_reports", ["status"])
    op.create_index("ix_backtest_reports_suitability_label", "backtest_reports", ["suitability_label"])
    op.create_index("ix_backtest_reports_suitability_score", "backtest_reports", ["suitability_score"])
    op.create_index("ix_backtest_reports_created_at", "backtest_reports", ["created_at"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("trade_no", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("commission", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False),
        sa.Column("gross_pnl", sa.Float(), nullable=False),
        sa.Column("net_pnl", sa.Float(), nullable=False),
        sa.Column("return_pct", sa.Float(), nullable=False),
        sa.Column("holding_bars", sa.Integer(), nullable=False),
        sa.Column("entry_reason", sa.Text(), nullable=False),
        sa.Column("exit_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["backtest_reports.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_backtest_trades_report_id", "backtest_trades", ["report_id"])
    op.create_index("ix_backtest_trades_trade_no", "backtest_trades", ["trade_no"])
    op.create_index("ix_backtest_trades_symbol", "backtest_trades", ["symbol"])
    op.create_index("ix_backtest_trades_contract", "backtest_trades", ["contract"])
    op.create_index("ix_backtest_trades_direction", "backtest_trades", ["direction"])
    op.create_index("ix_backtest_trades_open_time", "backtest_trades", ["open_time"])
    op.create_index("ix_backtest_trades_close_time", "backtest_trades", ["close_time"])
    op.create_index("ix_backtest_trades_net_pnl", "backtest_trades", ["net_pnl"])
    op.create_index("ix_backtest_trades_created_at", "backtest_trades", ["created_at"])

    watchlists_table = sa.table(
        "watchlists",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    watchlist_items_table = sa.table(
        "watchlist_items",
        sa.column("watchlist_code", sa.String),
        sa.column("symbol", sa.String),
        sa.column("name", sa.String),
        sa.column("exchange_code", sa.String),
        sa.column("default_contract", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("extra", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(watchlists_table, [{**row, "created_at": now, "updated_at": now} for row in WATCHLIST_ROWS])
    op.bulk_insert(
        watchlist_items_table,
        [
            {
                "watchlist_code": code,
                "symbol": symbol,
                "name": name,
                "exchange_code": exchange,
                "default_contract": contract,
                "sort_order": order,
                "is_active": True,
                "extra": {},
                "created_at": now,
                "updated_at": now,
            }
            for code, symbol, name, exchange, contract, order in WATCHLIST_ITEM_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_table("backtest_trades")
    op.drop_table("backtest_reports")
    op.drop_table("backtest_tasks")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
