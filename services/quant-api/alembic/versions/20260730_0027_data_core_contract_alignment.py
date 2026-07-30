"""align data-core catalog identity and canonical main-contract view

Revision ID: 20260730_0027
Revises: 20260730_0026
Create Date: 2026-07-30

This revision is schema-only. Both directions require ``market_datasets`` to
be empty so the migration never guesses the new identity fields or discards
them during downgrade. The legacy ``main_contract_map`` table and its rows are
left unchanged.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_0027"
down_revision = "20260730_0026"
branch_labels = None
depends_on = None


def _lock_and_require_empty(*, direction: str) -> None:
    if direction not in {"upgrade", "downgrade"}:
        raise ValueError("direction must be upgrade or downgrade")
    error_message = (
        f"market_datasets must be empty before {revision} {direction}"
    )
    op.execute("LOCK TABLE market_datasets IN ACCESS EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM market_datasets) THEN
                RAISE EXCEPTION '{error_message}'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _lock_and_require_empty(direction="upgrade")

    op.drop_constraint(
        "uq_market_datasets_dataset_key",
        "market_datasets",
        type_="unique",
    )
    op.alter_column(
        "market_datasets",
        "data_type",
        new_column_name="dataset_kind",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "market_datasets",
        "instrument_symbol",
        new_column_name="symbol",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "market_datasets",
        "contract_code",
        new_column_name="contract_or_series",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "market_datasets",
        "period",
        new_column_name="frequency",
        existing_type=sa.String(length=16),
        existing_nullable=False,
    )
    op.add_column(
        "market_datasets",
        sa.Column("adjustment", sa.String(length=32), nullable=False),
    )
    op.add_column(
        "market_datasets",
        sa.Column("schema_version", sa.String(length=32), nullable=False),
    )

    op.create_check_constraint(
        "ck_market_datasets_provider_rqdata",
        "market_datasets",
        "provider = 'rqdata'",
    )
    op.create_check_constraint(
        "ck_market_datasets_kind",
        "market_datasets",
        "dataset_kind IN ('continuous', 'actual_dominant')",
    )
    op.create_check_constraint(
        "ck_market_datasets_direct_frequency",
        "market_datasets",
        "frequency IN ('1m', '1d', '1w')",
    )
    op.create_check_constraint(
        "ck_market_datasets_identity_nonempty",
        "market_datasets",
        "length(trim(provider)) > 0"
        " AND length(trim(dataset_kind)) > 0"
        " AND length(trim(symbol)) > 0"
        " AND length(trim(contract_or_series)) > 0"
        " AND length(trim(frequency)) > 0"
        " AND length(trim(adjustment)) > 0"
        " AND length(trim(schema_version)) > 0",
    )
    op.create_check_constraint(
        "ck_market_datasets_identity_canonical",
        "market_datasets",
        "symbol = lower(trim(symbol))"
        " AND contract_or_series = upper(trim(contract_or_series))"
        " AND adjustment = lower(trim(adjustment))"
        " AND schema_version = trim(schema_version)",
    )
    op.create_unique_constraint(
        "uq_market_datasets_dataset_key",
        "market_datasets",
        [
            "provider",
            "dataset_kind",
            "symbol",
            "contract_or_series",
            "frequency",
            "adjustment",
            "schema_version",
        ],
    )

    op.execute(
        """
        CREATE VIEW data_core_main_contract_map AS
        SELECT DISTINCT
            id,
            instrument_symbol AS symbol,
            trade_date AS trading_day,
            contract_code AS actual_contract,
            provider,
            rank,
            rule,
            data_version,
            created_at
        FROM main_contract_map
        WHERE provider = 'rqdata'
          AND rank = 1
          AND rule = 'volume_open_interest'
        """
    )


def downgrade() -> None:
    _lock_and_require_empty(direction="downgrade")

    op.execute("DROP VIEW data_core_main_contract_map")
    op.drop_constraint(
        "uq_market_datasets_dataset_key",
        "market_datasets",
        type_="unique",
    )
    for constraint_name in (
        "ck_market_datasets_identity_canonical",
        "ck_market_datasets_identity_nonempty",
        "ck_market_datasets_direct_frequency",
        "ck_market_datasets_kind",
        "ck_market_datasets_provider_rqdata",
    ):
        op.drop_constraint(
            constraint_name,
            "market_datasets",
            type_="check",
        )

    op.drop_column("market_datasets", "schema_version")
    op.drop_column("market_datasets", "adjustment")
    op.alter_column(
        "market_datasets",
        "frequency",
        new_column_name="period",
        existing_type=sa.String(length=16),
        existing_nullable=False,
    )
    op.alter_column(
        "market_datasets",
        "contract_or_series",
        new_column_name="contract_code",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "market_datasets",
        "symbol",
        new_column_name="instrument_symbol",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "market_datasets",
        "dataset_kind",
        new_column_name="data_type",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_market_datasets_dataset_key",
        "market_datasets",
        [
            "provider",
            "data_type",
            "instrument_symbol",
            "contract_code",
            "period",
        ],
    )
