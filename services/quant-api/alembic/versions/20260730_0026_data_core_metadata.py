"""add historical data core metadata

Revision ID: 20260730_0026
Revises: 20260721_0025
Create Date: 2026-07-30

This revision is schema-only. It intentionally performs no legacy
``market_data_files`` backfill and does not modify ``main_contract_map``.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_0026"
down_revision = "20260721_0025"
branch_labels = None
depends_on = None


def _lower_sha256_check(column: str) -> str:
    residue = column
    for character in "0123456789abcdef":
        residue = f"replace({residue}, '{character}', '')"
    return (
        f"length({column}) = 64"
        f" AND {column} = lower({column})"
        f" AND length({residue}) = 0"
    )


def upgrade() -> None:
    op.create_table(
        "market_datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "provider",
            "data_type",
            "instrument_symbol",
            "contract_code",
            "period",
            name="uq_market_datasets_dataset_key",
        ),
    )

    op.create_table(
        "market_partitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column(
            "coverage_start",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "coverage_end",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("manifest_version", sa.String(length=64), nullable=False),
        sa.Column("manifest_uri", sa.Text(), nullable=False),
        sa.Column("manifest_digest", sa.String(length=64), nullable=False),
        sa.Column("file_uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("overlap_reason", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "coverage_start < coverage_end",
            name="ck_market_partitions_half_open_window",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="ck_market_partitions_row_count_nonnegative",
        ),
        sa.CheckConstraint(
            _lower_sha256_check("manifest_digest"),
            name="ck_market_partitions_manifest_digest_sha256",
        ),
        sa.CheckConstraint(
            _lower_sha256_check("checksum"),
            name="ck_market_partitions_checksum_sha256",
        ),
        sa.CheckConstraint(
            "overlap_reason IS NULL OR overlap_reason IN "
            "('version_replacement', 'repair_overlay', 'rollover_transition')",
            name="ck_market_partitions_overlap_reason",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["market_datasets.id"],
            name="fk_market_partitions_dataset_id_market_datasets",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "coverage_start",
            "coverage_end",
            "manifest_version",
            name="uq_market_partitions_exact_identity",
        ),
    )

    op.execute(
        """
        ALTER TABLE market_partitions
        ADD CONSTRAINT ex_market_partitions_unexplained_coverage
        EXCLUDE USING gist (
            int4range(dataset_id, dataset_id, '[]') WITH =,
            tstzrange(coverage_start, coverage_end, '[)') WITH &&
        )
        WHERE (overlap_reason IS NULL)
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_market_partition_fact_updates()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.dataset_id IS DISTINCT FROM NEW.dataset_id
               OR OLD.coverage_start IS DISTINCT FROM NEW.coverage_start
               OR OLD.coverage_end IS DISTINCT FROM NEW.coverage_end
               OR OLD.manifest_version IS DISTINCT FROM NEW.manifest_version
               OR OLD.manifest_uri IS DISTINCT FROM NEW.manifest_uri
               OR OLD.manifest_digest IS DISTINCT FROM NEW.manifest_digest
               OR OLD.file_uri IS DISTINCT FROM NEW.file_uri
               OR OLD.checksum IS DISTINCT FROM NEW.checksum
               OR OLD.row_count IS DISTINCT FROM NEW.row_count
               OR OLD.overlap_reason IS DISTINCT FROM NEW.overlap_reason
            THEN
                RAISE EXCEPTION
                    'market_partitions create-only facts are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_market_partitions_immutable
        BEFORE UPDATE ON market_partitions
        FOR EACH ROW
        EXECUTE FUNCTION reject_market_partition_fact_updates()
        """
    )

    op.create_table(
        "data_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("gap_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gap_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column(
            "details",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "gap_start < gap_end",
            name="ck_data_gaps_half_open_window",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["market_datasets.id"],
            name="fk_data_gaps_dataset_id_market_datasets",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "gap_start",
            "gap_end",
            name="uq_data_gaps_exact_window",
        ),
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_market_partitions_immutable ON market_partitions"
    )
    op.execute("DROP FUNCTION reject_market_partition_fact_updates()")
    op.drop_table("data_gaps")
    op.drop_table("market_partitions")
    op.drop_table("market_datasets")
