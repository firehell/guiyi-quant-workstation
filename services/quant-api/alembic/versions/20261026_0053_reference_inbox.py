"""Append-only original Reference input receipts and frozen delivery routes."""
from alembic import op
import sqlalchemy as sa

revision = "20261026_0053"
down_revision = "20261015_0052"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "reference_inbox_inputs",
        sa.Column("input_id", sa.String(64), primary_key=True),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("journal_id", sa.String(48), nullable=False),
        sa.Column("journal_ms", sa.Numeric(20, 0), nullable=False),
        sa.Column("journal_sequence", sa.Numeric(20, 0), nullable=False),
        sa.Column("observation_id", sa.String(256), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("canonical_envelope", sa.Text(), nullable=False),
        sa.Column("envelope_sha256", sa.String(64), nullable=False),
        sa.Column("routing_sha256", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("target_count", sa.BigInteger(), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_received_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trading_day", "journal_id", name="uq_reference_inbox_journal"),
        sa.CheckConstraint("journal_ms >= 0 AND journal_sequence >= 0", name="ck_reference_inbox_journal_order"),
        sa.CheckConstraint("payload_bytes > 0 AND target_count >= 0", name="ck_reference_inbox_input_size"),
    )
    op.create_index("ix_reference_inbox_day", "reference_inbox_inputs", ["trading_day"])
    op.create_table(
        "reference_inbox_deliveries",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("input_id", sa.String(64), nullable=False),
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("activation_receipt_id", sa.String(64), nullable=False),
        sa.Column("activation_plan_hash", sa.String(64), nullable=False),
        sa.Column("recording_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("waiting_at", sa.DateTime(timezone=True)),
        sa.Column("blocked_at", sa.DateTime(timezone=True)),
        sa.Column("unknown_at", sa.DateTime(timezone=True)),
        sa.Column("legacy_capture_batch_id", sa.String(96)),
        sa.Column("calculation_batch_id", sa.String(96)),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["input_id"], ["reference_inbox_inputs.input_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stream_id", "revision_id"],
                                ["reference_revisions.stream_id", "reference_revisions.revision_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activation_receipt_id"], ["reference_activation_receipts.receipt_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["legacy_capture_batch_id"], ["reference_batches.batch_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stream_id", "revision_id", "calculation_batch_id"],
                                ["reference_batches.stream_id", "reference_batches.revision_id", "reference_batches.batch_id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("input_id", "stream_id", name="uq_reference_inbox_delivery_target"),
        sa.UniqueConstraint("legacy_capture_batch_id", name="uq_reference_inbox_legacy_capture"),
        sa.UniqueConstraint("calculation_batch_id", name="uq_reference_inbox_calculation"),
        sa.CheckConstraint("generation > 0", name="ck_reference_inbox_delivery_generation"),
        sa.CheckConstraint("status IN ('PENDING','WAITING_HISTORY','COMPLETED','BLOCKED','UNKNOWN')",
                           name="ck_reference_inbox_delivery_status"),
        sa.CheckConstraint("(status = 'COMPLETED' AND calculation_batch_id IS NOT NULL AND calculated_at IS NOT NULL) OR "
                           "(status <> 'COMPLETED' AND calculation_batch_id IS NULL AND calculated_at IS NULL)",
                           name="ck_reference_inbox_delivery_completion"),
    )
    op.create_index("ix_reference_inbox_delivery_head", "reference_inbox_deliveries", ["stream_id", "input_id"],
                    postgresql_where=sa.text("status <> 'COMPLETED'"))
    op.create_index("ix_reference_inbox_delivery_status", "reference_inbox_deliveries", ["status", "updated_at"])
    # Protect original envelopes and frozen routing even from accidental ORM or
    # manual UPDATEs. Status/code/timestamps are the only mutable delivery data.
    op.execute("""
        CREATE FUNCTION reference_inbox_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR TG_TABLE_NAME = 'reference_inbox_inputs' THEN
                RAISE EXCEPTION 'REFERENCE_INBOX_IMMUTABLE';
            END IF;
            IF ROW(NEW.delivery_id, NEW.input_id, NEW.stream_id, NEW.revision_id,
                   NEW.generation, NEW.activation_receipt_id, NEW.activation_plan_hash,
                   NEW.recording_start, NEW.created_at, NEW.legacy_capture_batch_id)
               IS DISTINCT FROM
               ROW(OLD.delivery_id, OLD.input_id, OLD.stream_id, OLD.revision_id,
                   OLD.generation, OLD.activation_receipt_id, OLD.activation_plan_hash,
                   OLD.recording_start, OLD.created_at, OLD.legacy_capture_batch_id)
               OR OLD.status = 'COMPLETED' AND NEW IS DISTINCT FROM OLD
               OR OLD.status IN ('BLOCKED','UNKNOWN') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'REFERENCE_INBOX_IMMUTABLE';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in ("reference_inbox_inputs", "reference_inbox_deliveries"):
        op.execute(f"CREATE TRIGGER reference_inbox_immutable BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION reference_inbox_guard()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM reference_inbox_inputs LIMIT 1")).first():
        raise RuntimeError("REFERENCE_INBOX_DOWNGRADE_UNSAFE")
    op.drop_table("reference_inbox_deliveries")
    op.drop_table("reference_inbox_inputs")
    op.execute("DROP FUNCTION reference_inbox_guard()")
