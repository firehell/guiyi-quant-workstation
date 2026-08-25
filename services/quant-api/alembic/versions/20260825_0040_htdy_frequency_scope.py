"""Add per-product HTDY frequency scope and frequency-aware Event identity.

Revision ID: 20260825_0040
Revises: 20260815_0039
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260825_0040"
down_revision: str | Sequence[str] | None = "20260815_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alert_rules",
        sa.Column(
            "scope_product_frequencies",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )

    rule_table = sa.table(
        "alert_rules",
        sa.column("rule_code", sa.String(64)),
        sa.column("scope_products", postgresql.ARRAY(sa.String(32))),
        sa.column("scope_product_frequencies", sa.JSON()),
    )
    bind = op.get_bind()
    htdy_scope = bind.execute(
        sa.select(rule_table.c.scope_products).where(
            rule_table.c.rule_code == "htdy_original_15m"
        )
    ).scalar_one_or_none()
    if htdy_scope is not None:
        bind.execute(
            sa.update(rule_table)
            .where(rule_table.c.rule_code == "htdy_original_15m")
            .values(
                scope_products=[],
                scope_product_frequencies={symbol: ["15m"] for symbol in htdy_scope},
            )
        )

    op.drop_constraint(
        "uq_alert_events_rule_symbol_bar_end",
        "alert_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_alert_events_rule_symbol_frequency_bar_end",
        "alert_events",
        ["rule_id", "symbol", "frequency", "bar_end"],
    )


def downgrade() -> None:
    raise RuntimeError("HTDY_FREQUENCY_SCOPE_DOWNGRADE_UNSUPPORTED")
