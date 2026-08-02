"""add clean-start live decision, reconciliation, sample, and retention schema

Revision ID: 20260802_0028
Revises: 20260730_0027
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_0028"
down_revision = "20260730_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_observation_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("source_mode", sa.String(64), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("actual_contract", sa.String(64), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("open", sa.Numeric(38, 18), nullable=False),
        sa.Column("high", sa.Numeric(38, 18), nullable=False),
        sa.Column("low", sa.Numeric(38, 18), nullable=False),
        sa.Column("close", sa.Numeric(38, 18), nullable=False),
        sa.Column("volume", sa.Numeric(38, 18), nullable=False),
        sa.Column("open_interest", sa.Numeric(38, 18)),
        sa.Column("turnover", sa.Numeric(38, 18)),
        sa.Column("source_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_bar_count", sa.Integer(), nullable=False),
        sa.Column("expected_bar_count", sa.Integer(), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "source_mode", "actual_contract", "period", "trading_day", "bar_end", name="uq_live_observation_bars_natural_key"),
        sa.CheckConstraint("provider = 'rqdata'", name="ck_live_observation_provider"),
        sa.CheckConstraint("product = 'jm'", name="ck_live_observation_product"),
        sa.CheckConstraint("period IN ('1m', '15m')", name="ck_live_observation_period"),
        sa.CheckConstraint("revision >= 0", name="ck_live_observation_revision"),
        sa.CheckConstraint("confirmed = true", name="ck_live_observation_confirmed"),
        sa.CheckConstraint("source_bar_count > 0", name="ck_live_observation_source_count"),
        sa.CheckConstraint("expected_bar_count > 0", name="ck_live_observation_expected_count"),
        sa.CheckConstraint("source_bar_count = expected_bar_count", name="ck_live_observation_complete"),
        sa.CheckConstraint("low <= open AND low <= close AND high >= open AND high >= close AND low <= high", name="ck_live_observation_ohlc"),
    )
    op.create_index("ix_live_observation_trading_bucket", "live_observation_bars", ["trading_day", "actual_contract", "period", "bar_end"])

    op.create_table(
        "signal_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_key", sa.String(64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("source_mode", sa.String(64), nullable=False),
        sa.Column("actual_contract", sa.String(64), nullable=False),
        sa.Column("strategy_code", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("policy_id", sa.String(96), nullable=False),
        sa.Column("parameter_digest", sa.String(64), nullable=False),
        sa.Column("input_schema_version", sa.String(32), nullable=False),
        sa.Column("input_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset_key", sa.JSON(), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("fingerprint_recipe_version", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result_kind", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(16)),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_key", name="uq_signal_decisions_key"),
        sa.CheckConstraint("result_kind IN ('signal', 'no_signal')", name="ck_signal_decisions_result_kind"),
        sa.CheckConstraint("(result_kind = 'signal' AND direction IS NOT NULL AND direction IN ('long', 'short')) OR (result_kind = 'no_signal' AND direction IS NULL)", name="ck_signal_decisions_direction"),
    )
    op.create_index("ix_signal_decisions_bucket", "signal_decisions", ["trading_day", "actual_contract", "bar_end"])

    op.create_table(
        "signal_decision_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("recipe_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(40)),
        sa.Column("data_changed", sa.Boolean()),
        sa.Column("result_changed", sa.Boolean()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_final_snapshot", sa.JSON(), nullable=False),
        sa.Column("provider_final_digest", sa.String(64)),
        sa.Column("recomputed_result", sa.JSON(), nullable=False),
        sa.Column("recomputed_result_digest", sa.String(64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(96)),
        sa.Column("error_message", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_id", "recipe_version", name="uq_signal_decision_reconciliation"),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_signal_decision_reconciliation_attempts"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('unchanged', 'data_changed', 'result_changed', 'data_and_result_changed')", name="ck_signal_decision_reconciliation_outcome"),
    )
    op.create_index("ix_signal_decision_reconciliations_decision_id", "signal_decision_reconciliations", ["decision_id"])

    op.create_table(
        "research_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sample_key", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("decision_key", sa.String(64), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("reconciliation_digest", sa.String(64), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("lineage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sample_key", name="uq_research_samples_key"),
    )
    op.create_index("ix_research_samples_decision_key", "research_samples", ["decision_key"])

    op.create_table(
        "retention_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("target_counts", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("manifest_digest", name="uq_retention_runs_manifest_digest"),
    )

    op.add_column("signal_events", sa.Column("decision_id", sa.Integer(), nullable=True))
    op.create_index("ix_signal_events_decision_id", "signal_events", ["decision_id"])


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM live_observation_bars)
               OR EXISTS (SELECT 1 FROM signal_decisions)
               OR EXISTS (SELECT 1 FROM signal_decision_reconciliations)
               OR EXISTS (SELECT 1 FROM research_samples)
               OR EXISTS (SELECT 1 FROM retention_runs)
               OR EXISTS (SELECT 1 FROM signal_events WHERE decision_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Task 06 clean-start tables must be empty before downgrade';
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_signal_events_decision_id", table_name="signal_events")
    op.drop_column("signal_events", "decision_id")
    op.drop_table("retention_runs")
    op.drop_table("research_samples")
    op.drop_table("signal_decision_reconciliations")
    op.drop_table("signal_decisions")
    op.drop_table("live_observation_bars")
