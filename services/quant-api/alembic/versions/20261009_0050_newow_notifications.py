"""Durable, default-off Newow action delivery policy and one-shot claims."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0050'
down_revision = '20261008_0049'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('newow_notification_policies',
        sa.Column('policy_id', sa.String(32), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('topic_hash', sa.String(64), nullable=False),
        sa.Column('products', sa.JSON(), nullable=False),
        sa.Column('cursor_at', sa.DateTime(timezone=True)),
        sa.Column('cursor_batch_id', sa.String(96)))
    op.create_table('newow_notification_deliveries',
        sa.Column('delivery_id', sa.String(64), primary_key=True),
        sa.Column('stream_id', sa.String(96), nullable=False),
        sa.Column('signal_id', sa.String(160), nullable=False),
        sa.Column('batch_id', sa.String(96), nullable=False),
        sa.Column('topic_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('provider_reference', sa.String(256)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('BATCH_PROCESSED','ATTEMPTED_UNKNOWN','PROVIDER_ACCEPTED','FAILED_OR_UNKNOWN')", name='ck_newow_delivery_status'),
        sa.UniqueConstraint('stream_id', 'signal_id', name='uq_newow_delivery_signal'))

    op.create_index('ix_newow_delivery_batch_status', 'newow_notification_deliveries', ['status', 'batch_id'])

def downgrade():
    op.drop_table('newow_notification_deliveries')
    op.drop_table('newow_notification_policies')
