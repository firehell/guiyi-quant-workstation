"""profile active binding partial unique index

Revision ID: 20260712_0022
Revises: 20260712_0021
Create Date: 2026-07-12

Allow multiple superseded bindings per identity while enforcing at most one active
binding per profile x symbol x contract x period.

Downgrade note: rebuilding uq_profile_active_binding_identity_status will fail if
more than one superseded row exists for the same identity.
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
    op.create_unique_constraint(
        "uq_profile_active_binding_identity_status",
        "profile_active_bindings",
        ["profile_id", "instrument_symbol", "contract_code", "period", "binding_status"],
    )
