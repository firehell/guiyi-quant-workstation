"""Remember the newest completed source receipt for each isolated research series."""

from alembic import op
import sqlalchemy as sa

revision = "20261124_0056"
down_revision = "20261124_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("newow_backtest_series", sa.Column("source_publication_at", sa.DateTime(timezone=True)))
    op.add_column("newow_backtest_series", sa.Column("source_publication_sha256", sa.String(64)))


def downgrade() -> None:
    op.drop_column("newow_backtest_series", "source_publication_sha256")
    op.drop_column("newow_backtest_series", "source_publication_at")
