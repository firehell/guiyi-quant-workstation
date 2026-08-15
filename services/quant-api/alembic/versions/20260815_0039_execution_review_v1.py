"""Add the Execution Review V1 application domain.

Revision ID: 20260815_0039
Revises: 20260814_0038
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260815_0039"
down_revision: str | Sequence[str] | None = "20260814_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trade_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "alert_event_id",
            sa.Integer(),
            sa.ForeignKey("alert_events.id"),
            nullable=False,
        ),
        sa.Column("disposition", sa.String(16), nullable=False),
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "primary_not_execute_reason",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "secondary_not_execute_reasons",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "execution_reason_tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("planned_stop_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("stop_basis", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "alert_event_id",
            name="uq_trade_decisions_alert_event",
        ),
        sa.CheckConstraint(
            "disposition IN ('EXECUTED','NOT_EXECUTED')",
            name="ck_trade_decisions_disposition",
        ),
        sa.CheckConstraint(
            "planned_stop_price IS NULL OR planned_stop_price > 0",
            name="ck_trade_decisions_stop_price_positive",
        ),
    )
    op.create_table(
        "trade_episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "origin_decision_id",
            sa.Integer(),
            sa.ForeignKey("trade_decisions.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("contract", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(32), nullable=True),
        sa.Column(
            "roll_reference_exit_price",
            sa.Numeric(24, 8),
            nullable=True,
        ),
        sa.Column(
            "roll_reference_bar_end",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "contract_multiplier_snapshot",
            sa.Numeric(24, 8),
            nullable=True,
        ),
        sa.Column("multiplier_policy_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "origin_decision_id",
            name="uq_trade_episodes_origin_decision",
        ),
        sa.CheckConstraint(
            "direction IN ('LONG','SHORT')",
            name="ck_trade_episodes_direction",
        ),
        sa.CheckConstraint(
            "contract_multiplier_snapshot IS NULL "
            "OR contract_multiplier_snapshot > 0",
            name="ck_trade_episodes_multiplier_positive",
        ),
        sa.CheckConstraint(
            "((contract_multiplier_snapshot IS NULL "
            "AND multiplier_policy_id IS NULL) "
            "OR (contract_multiplier_snapshot IS NOT NULL "
            "AND multiplier_policy_id IS NOT NULL "
            "AND multiplier_policy_id = 'product_trade_multipliers_v1'))",
            name="ck_trade_episodes_multiplier_lineage",
        ),
        sa.CheckConstraint(
            "((closed_at IS NULL AND close_reason IS NULL "
            "AND roll_reference_exit_price IS NULL "
            "AND roll_reference_bar_end IS NULL) "
            "OR (closed_at IS NOT NULL AND close_reason IS NOT NULL "
            "AND close_reason = 'DOMINANT_ROLL' "
            "AND roll_reference_exit_price IS NOT NULL "
            "AND roll_reference_bar_end IS NOT NULL) "
            "OR (closed_at IS NOT NULL AND close_reason IS NOT NULL "
            "AND close_reason = 'EXECUTION_NET_ZERO' "
            "AND roll_reference_exit_price IS NULL "
            "AND roll_reference_bar_end IS NULL))",
            name="ck_trade_episodes_lifecycle",
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="ck_trade_episodes_closed_at",
        ),
    )
    op.create_index(
        "uq_trade_episodes_symbol_open",
        "trade_episodes",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_table(
        "trade_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "episode_id",
            sa.Integer(),
            sa.ForeignKey("trade_episodes.id"),
            nullable=False,
        ),
        sa.Column(
            "trigger_decision_id",
            sa.Integer(),
            sa.ForeignKey("trade_decisions.id"),
            nullable=True,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("execution_type", sa.String(16), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "episode_id",
            "sequence_no",
            name="uq_trade_executions_episode_sequence",
        ),
        sa.UniqueConstraint(
            "trigger_decision_id",
            name="uq_trade_executions_trigger_decision",
        ),
        sa.CheckConstraint(
            "sequence_no > 0",
            name="ck_trade_executions_sequence_positive",
        ),
        sa.CheckConstraint(
            "execution_type IN ('OPEN','ADD','REDUCE','CLOSE')",
            name="ck_trade_executions_type",
        ),
        sa.CheckConstraint(
            "((execution_type = 'OPEN' AND sequence_no = 1) "
            "OR (execution_type <> 'OPEN' AND sequence_no > 1))",
            name="ck_trade_executions_open_sequence",
        ),
        sa.CheckConstraint(
            "price > 0",
            name="ck_trade_executions_price_positive",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_trade_executions_quantity_positive",
        ),
    )
    op.create_table(
        "trade_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "episode_id",
            sa.Integer(),
            sa.ForeignKey("trade_episodes.id"),
            nullable=False,
        ),
        sa.Column(
            "signal_execution_adherence",
            sa.String(16),
            nullable=False,
        ),
        sa.Column(
            "entry_tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "holding_tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "exit_tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "market_context_tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "psychology_tags",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "episode_id",
            name="uq_trade_reviews_episode",
        ),
        sa.CheckConstraint(
            "signal_execution_adherence IN ('ALIGNED','DEVIATED')",
            name="ck_trade_reviews_adherence",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("EXECUTION_REVIEW_V1_DOWNGRADE_UNSUPPORTED")
