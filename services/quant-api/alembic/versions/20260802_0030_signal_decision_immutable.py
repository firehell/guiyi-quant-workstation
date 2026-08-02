"""reject updates to create-only signal decisions

Revision ID: 20260802_0030
Revises: 20260802_0029
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op


revision = "20260802_0030"
down_revision = "20260802_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_signal_decision_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'SIGNAL_DECISION_IMMUTABLE';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_signal_decisions_immutable
        BEFORE UPDATE ON signal_decisions
        FOR EACH ROW
        EXECUTE FUNCTION reject_signal_decision_update()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_signal_decisions_immutable ON signal_decisions")
    op.execute("DROP FUNCTION reject_signal_decision_update()")
