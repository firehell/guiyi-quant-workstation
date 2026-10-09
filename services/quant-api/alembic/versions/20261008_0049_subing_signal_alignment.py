"""Add immutable EMA21 alignment research snapshots and six-period silent Scope.

Existing Event rows remain untouched. Upgrade is one transaction; only products
already present in the SuBing Scope gain the six recording periods.
"""

from alembic import op
import sqlalchemy as sa
import json

revision = "20261008_0049"
down_revision = "20260923_0048"
branch_labels = None
depends_on = None
FREQUENCIES = ["5m", "15m", "30m", "60m", "1d", "1w"]


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    bind = op.get_bind()
    rule = (
        bind.execute(
            sa.text(
                "SELECT id, enabled, scope_product_frequencies FROM alert_rules "
                "WHERE rule_code = :code FOR UPDATE"
            ),
            {"code": "subing_ths_alert_15m_v1"},
        )
        .mappings()
        .one_or_none()
    )
    if rule is None or not isinstance(rule["scope_product_frequencies"], dict):
        raise RuntimeError("SUBING_MULTIPERIOD_MIGRATION_PREFLIGHT_FAILED")
    scope = rule["scope_product_frequencies"]
    if any(
        not isinstance(symbol, str)
        or not symbol.isalpha()
        or symbol != symbol.lower()
        or not isinstance(periods, list)
        or not periods
        or any(not isinstance(f, str) for f in periods)
        or len(set(periods)) != len(periods)
        or any(f not in FREQUENCIES for f in periods)
        for symbol, periods in scope.items()
    ):
        raise RuntimeError("SUBING_MULTIPERIOD_MIGRATION_PREFLIGHT_FAILED")
    op.create_table(
        "subing_signal_alignments",
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("alert_events.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PASS','FAIL','UNKNOWN')", name="ck_subing_alignment_status"
        ),
    )
    op.create_index(
        "ix_subing_alignment_status", "subing_signal_alignments", ["status", "event_id"]
    )
    if rule["enabled"] and scope:
        bind.execute(
            sa.text(
                "UPDATE alert_rules SET scope_product_frequencies = CAST(:scope AS json) WHERE id = :id"
            ),
            {
                "scope": json.dumps(
                    {symbol: FREQUENCIES for symbol in scope}, sort_keys=True
                ),
                "id": rule["id"],
            },
        )


def downgrade():
    # Deleting accumulated research facts is not a rollback operation.
    raise RuntimeError("SUBING_ALIGNMENT_DOWNGRADE_UNSUPPORTED")
