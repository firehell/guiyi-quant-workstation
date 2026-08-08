"""drop retired profile/binding and after-market scheduler tables

Revision ID: 20260808_0035
Revises: 20260808_0034
Create Date: 2026-08-08

Candidate migration only: verify on isolated PostgreSQL. Production upgrade
requires a separate scoped execution intent.
"""

from alembic import op


revision = "20260808_0035"
down_revision = "20260808_0034"
branch_labels = None
depends_on = None


_DROP_TABLES = (
    "profile_active_bindings",
    "data_profiles",
    "after_market_scheduler_checkpoints",
)


def upgrade() -> None:
    """Irreversibly drop Profile/Binding and after-market checkpoint tables."""

    op.execute("SET LOCAL lock_timeout = '5s'")
    for table_name in _DROP_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')


def downgrade() -> None:
    raise RuntimeError(
        "profile/binding drop is irreversible: recover schema from Git history "
        "before attempting a downgrade"
    )
