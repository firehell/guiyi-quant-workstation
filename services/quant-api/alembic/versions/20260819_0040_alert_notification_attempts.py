"""Add the fixed-recipient Alert notification attempt ledger.

Revision ID: 20260819_0040
Revises: 20260815_0039
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_0040"
down_revision: str | Sequence[str] | None = "20260815_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_notification_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("alert_events.id"),
            nullable=False,
        ),
        sa.Column("recipient_alias", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "event_id",
            "recipient_alias",
            "channel",
            name="uq_alert_notification_attempts_event_alias_channel",
        ),
        sa.CheckConstraint(
            "status IN ('STARTED','PROVIDER_ACCEPTED','FAILED')",
            name="ck_alert_notification_attempts_status",
        ),
        sa.CheckConstraint(
            "((status = 'STARTED' AND completed_at IS NULL AND error_code IS NULL) "
            "OR (status = 'PROVIDER_ACCEPTED' AND completed_at IS NOT NULL "
            "AND error_code IS NULL) "
            "OR (status = 'FAILED' AND completed_at IS NOT NULL "
            "AND error_code IS NOT NULL))",
            name="ck_alert_notification_attempts_completion",
        ),
    )
    op.create_index(
        "ix_alert_notification_attempts_event_id",
        "alert_notification_attempts",
        ["event_id"],
    )
    op.create_index(
        "ix_alert_notification_attempts_status_attempted_at",
        "alert_notification_attempts",
        ["status", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_table("alert_notification_attempts")
