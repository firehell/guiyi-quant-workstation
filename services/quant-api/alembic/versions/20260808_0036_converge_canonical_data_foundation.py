"""Converge the active historical market-data foundation.

Revision ID: 20260808_0036
Revises: 20260808_0035
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260808_0036"
down_revision: str | Sequence[str] | None = "20260808_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RETIRED_TABLES = (
    "data_quality_reports",
    "market_data_files",
    "data_download_tasks",
    "data_sources",
    "fee_margin_rules",
    "futures_trading_parameters",
    "futures_ex_factors",
    "futures_warehouse_stocks",
    "futures_roll_yields",
    "futures_member_ranks",
    "futures_basis",
    "futures_contract_universe",
    "futures_continuous_contract_map",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in RETIRED_TABLES:
        op.drop_table(table)

    op.execute("DROP TABLE IF EXISTS data_gaps")
    op.execute("DROP TABLE IF EXISTS contract_specs")
    op.drop_table("market_partitions")
    op.drop_table("market_datasets")
    op.execute("DROP VIEW IF EXISTS data_core_main_contract_map")
    op.drop_table("main_contract_map")

    # Session identity becomes product-specific and deterministic. Existing
    # exchange-only templates cannot satisfy the new canonical boundary rule.
    op.execute("DELETE FROM trading_sessions")
    op.alter_column(
        "trading_sessions",
        "instrument_symbol",
        existing_type=sa.String(32),
        nullable=False,
    )
    op.add_column(
        "trading_sessions",
        sa.Column("effective_from", sa.Date(), nullable=False),
    )
    op.add_column(
        "trading_sessions",
        sa.Column("effective_to", sa.Date()),
    )
    op.create_unique_constraint(
        "uq_trading_sessions_identity",
        "trading_sessions",
        (
            "exchange_code",
            "instrument_symbol",
            "session_name",
            "start_time",
            "end_time",
            "effective_from",
        ),
    )
    op.create_check_constraint(
        "ck_trading_sessions_effective_window",
        "trading_sessions",
        "effective_to IS NULL OR effective_from <= effective_to",
    )

    op.create_table(
        "main_contract_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("contract_code", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "rule",
            sa.String(64),
            nullable=False,
            server_default="volume_open_interest",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("symbol", "trade_date", name="uq_main_contract_map_symbol_date"),
        sa.CheckConstraint("rank = 1", name="ck_main_contract_map_rank1"),
        sa.CheckConstraint(
            "rule = 'volume_open_interest'", name="ck_main_contract_map_rule"
        ),
    )
    op.create_index("ix_main_contract_map_symbol", "main_contract_map", ["symbol"])
    op.create_index(
        "ix_main_contract_map_trade_date", "main_contract_map", ["trade_date"]
    )
    op.create_index(
        "ix_main_contract_map_contract_code", "main_contract_map", ["contract_code"]
    )

    op.create_table(
        "market_datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("series_or_contract", sa.String(64), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "kind",
            "symbol",
            "series_or_contract",
            "frequency",
            name="uq_market_datasets_key",
        ),
        sa.CheckConstraint(
            "kind IN ('continuous', 'contract')", name="ck_market_datasets_kind"
        ),
        sa.CheckConstraint(
            "frequency IN ('1m', '5m', '15m', '30m', '60m', '1d', '1w')",
            name="ck_market_datasets_frequency",
        ),
    )
    op.create_index("ix_market_datasets_symbol", "market_datasets", ["symbol"])

    op.create_table(
        "market_partitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Integer(),
            sa.ForeignKey("market_datasets.id"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_uri", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "dataset_id", "year", "month", name="uq_market_partitions_month"
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_market_partitions_month"),
        sa.CheckConstraint(
            "coverage_start < coverage_end", name="ck_market_partitions_window"
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_market_partitions_row_count"),
    )


def downgrade() -> None:
    raise RuntimeError("20260808_0036 is intentionally irreversible")
