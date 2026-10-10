"""Preserve source observation and explicit unsent expiry without rewriting facts."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0051'
down_revision = '20261009_0050'
branch_labels = None
depends_on = None

_STATUS = "status IN ('BATCH_PROCESSED','ATTEMPTED_UNKNOWN','PROVIDER_ACCEPTED','FAILED_OR_UNKNOWN','EXPIRED_NO_SEND')"


def upgrade():
    for name, kind in [('source_observed_at', sa.DateTime(timezone=True)),
                       ('source_observation_id', sa.String(160)),
                       ('processing_mode', sa.String(32)), ('notification_status', sa.String(32))]:
        op.add_column('alert_events', sa.Column(name, kind, nullable=True))
    op.drop_constraint('ck_newow_delivery_status', 'newow_notification_deliveries', type_='check')
    op.create_check_constraint('ck_newow_delivery_status', 'newow_notification_deliveries', _STATUS)
    op.alter_column('newow_notification_deliveries', 'attempted_at', existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade():
    # Refuse lossy downgrade once the new fact type exists.
    if op.get_bind().execute(sa.text("SELECT 1 FROM newow_notification_deliveries WHERE attempted_at IS NULL OR status='EXPIRED_NO_SEND' LIMIT 1")).first():
        raise RuntimeError('OBSERVATION_HANDOVER_DOWNGRADE_UNSAFE')
    if op.get_bind().execute(sa.text("SELECT 1 FROM alert_events WHERE source_observed_at IS NOT NULL OR source_observation_id IS NOT NULL OR processing_mode IS NOT NULL OR notification_status IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("OBSERVATION_HANDOVER_DOWNGRADE_UNSAFE")
    op.alter_column('newow_notification_deliveries', 'attempted_at', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.drop_constraint('ck_newow_delivery_status', 'newow_notification_deliveries', type_='check')
    op.create_check_constraint('ck_newow_delivery_status', 'newow_notification_deliveries', _STATUS.replace(",'EXPIRED_NO_SEND'", ''))
    for name in ('notification_status', 'processing_mode', 'source_observation_id', 'source_observed_at'):
        op.drop_column('alert_events', name)
