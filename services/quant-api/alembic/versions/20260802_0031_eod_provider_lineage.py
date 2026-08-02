"""persist exact provider-final version and request identity

Revision ID: 20260802_0031
Revises: 20260802_0030
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_0031"
down_revision = "20260802_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signal_decision_reconciliations",
        sa.Column("provider_data_version", sa.String(128), nullable=True),
    )
    op.add_column(
        "signal_decision_reconciliations",
        sa.Column("provider_request_digest", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_signal_decision_reconciliation_provider_lineage",
        "signal_decision_reconciliations",
        "status != 'completed' OR (provider_data_version IS NOT NULL AND provider_request_digest IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM signal_decision_reconciliations) THEN
                RAISE EXCEPTION 'signal decision reconciliations must be empty before 20260802_0031 downgrade';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        "ck_signal_decision_reconciliation_provider_lineage",
        "signal_decision_reconciliations",
        type_="check",
    )
    op.drop_column("signal_decision_reconciliations", "provider_request_digest")
    op.drop_column("signal_decision_reconciliations", "provider_data_version")
