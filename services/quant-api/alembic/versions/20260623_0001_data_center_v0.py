"""data center v0

Revision ID: 20260623_0001
Revises:
Create Date: 2026-06-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260623_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_data_sources_name", "data_sources", ["name"], unique=True)
    op.create_index("ix_data_sources_provider", "data_sources", ["provider"])
    op.create_index("ix_data_sources_status", "data_sources", ["status"])

    op.create_table(
        "exchanges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_exchanges_code", "exchanges", ["code"], unique=True)

    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("exchange_code", sa.String(length=16), nullable=False),
        sa.Column("sector", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exchange_code"], ["exchanges.code"]),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)
    op.create_index("ix_instruments_name", "instruments", ["name"])
    op.create_index("ix_instruments_exchange_code", "instruments", ["exchange_code"])

    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange_code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("contract_month", sa.String(length=16), nullable=True),
        sa.Column("listed_date", sa.Date(), nullable=True),
        sa.Column("expired_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_symbol", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exchange_code"], ["exchanges.code"]),
        sa.ForeignKeyConstraint(["instrument_symbol"], ["instruments.symbol"]),
    )
    op.create_index("ix_contracts_contract_code", "contracts", ["contract_code"], unique=True)
    op.create_index("ix_contracts_instrument_symbol", "contracts", ["instrument_symbol"])
    op.create_index("ix_contracts_exchange_code", "contracts", ["exchange_code"])
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_provider", "contracts", ["provider"])

    op.create_table(
        "trading_calendars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exchange_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False),
        sa.Column("has_night_session", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["exchange_code"], ["exchanges.code"]),
        sa.UniqueConstraint("exchange_code", "trade_date", name="uq_trading_calendar_exchange_date"),
    )
    op.create_index("ix_trading_calendars_exchange_code", "trading_calendars", ["exchange_code"])
    op.create_index("ix_trading_calendars_trade_date", "trading_calendars", ["trade_date"])

    op.create_table(
        "trading_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exchange_code", sa.String(length=16), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("session_name", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("crosses_midnight", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exchange_code"], ["exchanges.code"]),
    )
    op.create_index("ix_trading_sessions_exchange_code", "trading_sessions", ["exchange_code"])
    op.create_index("ix_trading_sessions_instrument_symbol", "trading_sessions", ["instrument_symbol"])

    op.create_table(
        "fee_margin_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("exchange_code", sa.String(length=16), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("contract_code", sa.String(length=64), nullable=True),
        sa.Column("price_tick", sa.Numeric(18, 6), nullable=True),
        sa.Column("volume_multiple", sa.Integer(), nullable=True),
        sa.Column("margin_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("open_fee", sa.Numeric(18, 6), nullable=True),
        sa.Column("close_fee", sa.Numeric(18, 6), nullable=True),
        sa.Column("close_today_fee", sa.Numeric(18, 6), nullable=True),
        sa.Column("fee_type", sa.String(length=32), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exchange_code"], ["exchanges.code"]),
    )
    op.create_index("ix_fee_margin_rules_provider", "fee_margin_rules", ["provider"])
    op.create_index("ix_fee_margin_rules_exchange_code", "fee_margin_rules", ["exchange_code"])
    op.create_index("ix_fee_margin_rules_instrument_symbol", "fee_margin_rules", ["instrument_symbol"])
    op.create_index("ix_fee_margin_rules_contract_code", "fee_margin_rules", ["contract_code"])
    op.create_index("ix_fee_margin_rules_effective_date", "fee_margin_rules", ["effective_date"])

    op.create_table(
        "data_download_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_no", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("contract_code", sa.String(length=64), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Numeric(5, 2), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_data_download_tasks_task_no", "data_download_tasks", ["task_no"], unique=True)
    op.create_index("ix_data_download_tasks_provider", "data_download_tasks", ["provider"])
    op.create_index("ix_data_download_tasks_data_type", "data_download_tasks", ["data_type"])
    op.create_index("ix_data_download_tasks_instrument_symbol", "data_download_tasks", ["instrument_symbol"])
    op.create_index("ix_data_download_tasks_contract_code", "data_download_tasks", ["contract_code"])
    op.create_index("ix_data_download_tasks_period", "data_download_tasks", ["period"])
    op.create_index("ix_data_download_tasks_status", "data_download_tasks", ["status"])
    op.create_index("ix_data_download_tasks_created_at", "data_download_tasks", ["created_at"])

    op.create_table(
        "market_data_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("contract_code", sa.String(length=64), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=True),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["data_download_tasks.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "provider",
            "data_type",
            "contract_code",
            "period",
            "start_time",
            "end_time",
            "data_version",
            name="uq_market_data_file_version",
        ),
    )
    op.create_index("ix_market_data_files_provider", "market_data_files", ["provider"])
    op.create_index("ix_market_data_files_data_type", "market_data_files", ["data_type"])
    op.create_index("ix_market_data_files_instrument_symbol", "market_data_files", ["instrument_symbol"])
    op.create_index("ix_market_data_files_contract_code", "market_data_files", ["contract_code"])
    op.create_index("ix_market_data_files_period", "market_data_files", ["period"])
    op.create_index("ix_market_data_files_start_time", "market_data_files", ["start_time"])
    op.create_index("ix_market_data_files_end_time", "market_data_files", ["end_time"])
    op.create_index("ix_market_data_files_data_version", "market_data_files", ["data_version"])
    op.create_index("ix_market_data_files_quality_status", "market_data_files", ["quality_status"])

    op.create_table(
        "data_quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=True),
        sa.Column("contract_code", sa.String(length=64), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("missing_bars", sa.Integer(), nullable=False),
        sa.Column("duplicated_bars", sa.Integer(), nullable=False),
        sa.Column("abnormal_price_count", sa.Integer(), nullable=False),
        sa.Column("abnormal_volume_count", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["market_data_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["data_download_tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_data_quality_reports_provider", "data_quality_reports", ["provider"])
    op.create_index("ix_data_quality_reports_data_type", "data_quality_reports", ["data_type"])
    op.create_index("ix_data_quality_reports_instrument_symbol", "data_quality_reports", ["instrument_symbol"])
    op.create_index("ix_data_quality_reports_contract_code", "data_quality_reports", ["contract_code"])
    op.create_index("ix_data_quality_reports_period", "data_quality_reports", ["period"])
    op.create_index("ix_data_quality_reports_start_time", "data_quality_reports", ["start_time"])
    op.create_index("ix_data_quality_reports_end_time", "data_quality_reports", ["end_time"])
    op.create_index("ix_data_quality_reports_status", "data_quality_reports", ["status"])
    op.create_index("ix_data_quality_reports_created_at", "data_quality_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("data_quality_reports")
    op.drop_table("market_data_files")
    op.drop_table("data_download_tasks")
    op.drop_table("fee_margin_rules")
    op.drop_table("trading_sessions")
    op.drop_table("trading_calendars")
    op.drop_table("contracts")
    op.drop_table("instruments")
    op.drop_table("exchanges")
    op.drop_table("data_sources")
