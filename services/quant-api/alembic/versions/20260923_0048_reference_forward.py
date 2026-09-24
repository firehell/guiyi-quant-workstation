"""Add disabled-by-default forward activation and pending captures.

Revision ID: 20260923_0048
Revises: 20260919_0047
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260923_0048"
down_revision: str | Sequence[str] | None = "20260919_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column("reference_streams", sa.Column(
        "activation_generation", sa.BigInteger(), nullable=False, server_default="0",
    ))
    op.add_column("reference_streams", sa.Column("recording_start", sa.DateTime(timezone=True)))
    op.add_column("reference_streams", sa.Column("activation_plan_hash", sa.String(64)))
    op.add_column("reference_batches", sa.Column("consumed_by_batch_id", sa.String(96)))
    op.drop_constraint("ck_reference_batches_kind_seq", "reference_batches", type_="check")
    op.create_check_constraint(
        "ck_reference_batches_kind_seq", "reference_batches",
        "(kind IN ('diagnostic','seed_chunk','capture') AND seq IS NULL) OR "
        "(kind IN ('seed_seal','calculation') AND seq IS NOT NULL)",
    )
    op.create_table(
        "reference_activation_receipts",
        sa.Column("receipt_id", sa.String(64), primary_key=True),
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("recording_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("environment", sa.String(64), nullable=False),
        sa.Column("host", sa.String(128), nullable=False),
        sa.Column("budget", JSONB(), nullable=False),
        sa.Column("recovery_policy", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["stream_id"], ["reference_streams.stream_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("stream_id", "generation", name="uq_reference_activation_generation"),
        sa.CheckConstraint("generation > 0", name="ck_reference_activation_generation"),
        sa.CheckConstraint("recovery_policy IN ('block','interrupt_and_restart')", name="ck_reference_activation_recovery_policy"),
    )
    op.create_index(
        "ix_reference_batches_pending_capture", "reference_batches",
        ["stream_id", "revision_id", "processed_at"],
        postgresql_where=sa.text("kind = 'capture' AND consumed_by_batch_id IS NULL"),
    )
    op.create_table(
        "reference_capture_reconciliations",
        sa.Column("reconciliation_id", sa.String(64), primary_key=True),
        sa.Column("capture_batch_id", sa.String(96), nullable=False),
        sa.Column("source_revision", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("captured_sha256", sa.String(64), nullable=False),
        sa.Column("canonical_sha256", sa.String(64)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["capture_batch_id"], ["reference_batches.batch_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("capture_batch_id", "source_revision", name="uq_reference_capture_reconciliation"),
        sa.CheckConstraint("status IN ('matched','mismatch','pending')", name="ck_reference_capture_reconciliation_status"),
    )


def downgrade() -> None:
    op.drop_table("reference_capture_reconciliations")
    op.drop_index("ix_reference_batches_pending_capture", table_name="reference_batches")
    op.drop_table("reference_activation_receipts")
    op.drop_constraint("ck_reference_batches_kind_seq", "reference_batches", type_="check")
    op.create_check_constraint(
        "ck_reference_batches_kind_seq", "reference_batches",
        "(kind = 'diagnostic' AND seq IS NULL) OR "
        "(kind = 'seed_chunk' AND seq IS NULL) OR "
        "(kind IN ('seed_seal','calculation') AND seq IS NOT NULL)",
    )
    op.drop_column("reference_batches", "consumed_by_batch_id")
    op.drop_column("reference_streams", "activation_plan_hash")
    op.drop_column("reference_streams", "recording_start")
    op.drop_column("reference_streams", "activation_generation")
