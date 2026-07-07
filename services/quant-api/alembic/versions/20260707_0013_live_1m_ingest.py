"""live 1m ingest tables

Revision ID: 20260707_0013
Revises: 20260628_0012
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260707_0013"
down_revision = "20260628_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_minute_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("exchange_code", sa.String(length=16), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("bar_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=True),
        sa.Column("open", sa.Numeric(18, 6), nullable=True),
        sa.Column("high", sa.Numeric(18, 6), nullable=True),
        sa.Column("low", sa.Numeric(18, 6), nullable=True),
        sa.Column("close", sa.Numeric(18, 6), nullable=True),
        sa.Column("volume", sa.Numeric(20, 6), nullable=True),
        sa.Column("open_interest", sa.Numeric(20, 6), nullable=True),
        sa.Column("turnover", sa.Numeric(24, 6), nullable=True),
        sa.Column("bar_status", sa.String(length=32), nullable=False),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("source_mode", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "contract_code", "period", "bar_datetime", name="uq_live_minute_bars_provider_contract_period_time"),
    )
    for column in (
        "provider",
        "instrument_symbol",
        "contract_code",
        "exchange_code",
        "period",
        "bar_datetime",
        "trading_day",
        "bar_status",
        "quality_status",
        "source_mode",
    ):
        op.create_index(f"ix_live_minute_bars_{column}", "live_minute_bars", [column])
    op.create_index(
        "ix_live_minute_bars_instrument_contract_period_time",
        "live_minute_bars",
        ["instrument_symbol", "contract_code", "period", "bar_datetime"],
    )
    op.create_index("ix_live_minute_bars_contract_status_time", "live_minute_bars", ["contract_code", "bar_status", "bar_datetime"])
    op.create_index("ix_live_minute_bars_trading_day_contract_period", "live_minute_bars", ["trading_day", "contract_code", "period"])

    op.create_table(
        "live_ingest_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("source_mode", sa.String(length=64), nullable=False),
        sa.Column("last_confirmed_bar_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("lag_seconds", sa.Integer(), nullable=True),
        sa.Column("consecutive_error_count", sa.Integer(), nullable=False),
        sa.Column("last_error_type", sa.String(length=128), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "contract_code", "period", "source_mode", name="uq_live_ingest_checkpoints_target"),
    )
    for column in (
        "provider",
        "instrument_symbol",
        "contract_code",
        "period",
        "source_mode",
        "last_confirmed_bar_at",
        "status",
    ):
        op.create_index(f"ix_live_ingest_checkpoints_{column}", "live_ingest_checkpoints", [column])
    op.create_index("ix_live_ingest_checkpoints_contract_status", "live_ingest_checkpoints", ["contract_code", "status"])


def downgrade() -> None:
    op.drop_table("live_ingest_checkpoints")
    op.drop_table("live_minute_bars")
