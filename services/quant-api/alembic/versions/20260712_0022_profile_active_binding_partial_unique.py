"""profile active binding partial unique index

Revision ID: 20260712_0022
Revises: 20260712_0021
Create Date: 2026-07-12

Allow multiple superseded bindings per identity while enforcing at most one active
binding per profile x symbol x contract x period.

Downgrade note: the old constraint cannot represent multiple superseded rows per
identity, so downgrade keeps the newest row per identity/status before rebuilding
the legacy unique constraint.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260712_0022"
down_revision = "20260712_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_profile_active_binding_identity_status", "profile_active_bindings", type_="unique")
    op.create_index(
        "uq_profile_active_binding_active_identity",
        "profile_active_bindings",
        ["profile_id", "instrument_symbol", "contract_code", "period"],
        unique=True,
        postgresql_where=sa.text("binding_status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_profile_active_binding_active_identity", table_name="profile_active_bindings")
    op.execute(
        """
        DELETE FROM profile_active_bindings a
        USING profile_active_bindings b
        WHERE a.id < b.id
          AND a.profile_id = b.profile_id
          AND a.instrument_symbol = b.instrument_symbol
          AND a.contract_code = b.contract_code
          AND a.period = b.period
          AND a.binding_status = b.binding_status
        """
    )
    op.create_unique_constraint(
        "uq_profile_active_binding_identity_status",
        "profile_active_bindings",
        ["profile_id", "instrument_symbol", "contract_code", "period", "binding_status"],
    )
