"""Keep D1 source-price exceptions on the authoritative month partition.

Revision ID: 20260916_0046
Revises: 20260903_0045

Schema-only: no provider request, historical backfill or Canonical write.
Production execution remains a separately controlled operation.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260916_0046"
down_revision: str | Sequence[str] | None = "20260903_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("market_partitions", sa.Column(
        "source_coverage_start", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("market_partitions", sa.Column(
        "source_coverage_end", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("market_partitions", sa.Column(
        "source_quality", JSONB(), nullable=True,
    ))
    op.add_column("market_partitions", sa.Column(
        "source_quality_sha256", sa.String(64), nullable=True,
    ))
    op.drop_constraint("ck_market_partitions_window", "market_partitions", type_="check")
    op.alter_column("market_partitions", "coverage_start", nullable=True,
                    existing_type=sa.DateTime(timezone=True))
    op.alter_column("market_partitions", "coverage_end", nullable=True,
                    existing_type=sa.DateTime(timezone=True))
    op.create_check_constraint(
        "ck_market_partitions_window", "market_partitions",
        "(coverage_start IS NULL AND coverage_end IS NULL) OR coverage_start < coverage_end",
    )
    op.create_check_constraint(
        "ck_market_partitions_price_coverage_pair", "market_partitions",
        "(coverage_start IS NULL) = (coverage_end IS NULL)",
    )
    op.create_check_constraint(
        "ck_market_partitions_source_window", "market_partitions",
        "(source_coverage_start IS NULL AND source_coverage_end IS NULL) "
        "OR source_coverage_start < source_coverage_end",
    )
    op.create_check_constraint(
        "ck_market_partitions_quality_pair", "market_partitions",
        "(source_quality IS NULL) = (source_quality_sha256 IS NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("SOURCE_PRICE_QUALITY_DOWNGRADE_REQUIRES_EXACT_DATA_REVIEW")
