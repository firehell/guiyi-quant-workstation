"""Versioned quality input and nonrecoverable one-shot Alert memory handoff."""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0052"
down_revision = "20261009_0051"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("input_policy_version", sa.String(64)),
    ("notification_policy_version", sa.String(64)),
    ("notification_claimed_at", sa.DateTime(timezone=True)),
    ("notification_generation", sa.Integer()),
    ("notification_batch_id", sa.String(64)),
    ("notification_finished_at", sa.DateTime(timezone=True)),
    ("notification_provider_reference", sa.String(128)),
)


def upgrade():
    for name, kind in _COLUMNS:
        op.add_column("alert_events", sa.Column(name, kind, nullable=True))


def downgrade():
    predicate = " OR ".join(name + " IS NOT NULL" for name, _ in _COLUMNS)
    if op.get_bind().execute(sa.text("SELECT 1 FROM alert_events WHERE " + predicate + " LIMIT 1")).first():
        raise RuntimeError("ALERT_DELIVERY_V2_DOWNGRADE_UNSAFE")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("alert_events", name)
