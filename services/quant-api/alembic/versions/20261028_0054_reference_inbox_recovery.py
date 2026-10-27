"""Append-only explicit recovery results; preserve every 0053 original/guard."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261028_0054"
down_revision = "20261026_0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reference_inbox_recovery_results",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("input_id", sa.String(64), nullable=False),
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("target_receipt_id", sa.String(64), nullable=False),
        sa.Column("target_revision_id", sa.String(64), nullable=False),
        sa.Column("target_generation", sa.BigInteger(), nullable=False),
        sa.Column("capture_batch_id", sa.String(96), nullable=False),
        sa.Column("calculation_batch_id", sa.String(96), nullable=False),
        sa.Column("calculation_seq", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("proof", postgresql.JSONB(), nullable=False),
        sa.Column("proof_sha256", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["reference_inbox_deliveries.delivery_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["input_id"], ["reference_inbox_inputs.input_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_receipt_id"],
            ["reference_activation_receipts.receipt_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "target_revision_id", "capture_batch_id"],
            [
                "reference_batches.stream_id",
                "reference_batches.revision_id",
                "reference_batches.batch_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "target_revision_id", "calculation_batch_id"],
            [
                "reference_batches.stream_id",
                "reference_batches.revision_id",
                "reference_batches.batch_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "calculation_batch_id", name="uq_reference_inbox_recovery_calculation"
        ),
        sa.CheckConstraint(
            "target_generation > 0 AND calculation_seq > 0",
            name="ck_reference_inbox_recovery_progress",
        ),
        sa.CheckConstraint(
            "outcome IN ('CALCULATED','INTERRUPTED')",
            name="ck_reference_inbox_recovery_outcome",
        ),
    )
    op.execute("""CREATE FUNCTION reference_inbox_recovery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'REFERENCE_INBOX_RECOVERY_IMMUTABLE'; END $$""")
    op.execute("""CREATE TRIGGER reference_inbox_recovery_immutable BEFORE UPDATE OR DELETE
        ON reference_inbox_recovery_results FOR EACH ROW EXECUTE FUNCTION reference_inbox_recovery_guard()""")


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM reference_inbox_recovery_results LIMIT 1"))
        .first()
    ):
        raise RuntimeError("REFERENCE_INBOX_RECOVERY_DOWNGRADE_UNSAFE")
    op.drop_table("reference_inbox_recovery_results")
    op.execute("DROP FUNCTION reference_inbox_recovery_guard()")
