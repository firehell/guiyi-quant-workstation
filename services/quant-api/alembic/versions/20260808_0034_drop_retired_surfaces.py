"""drop retired signal/review/watchlist and live/task06 tables

Revision ID: 20260808_0034
Revises: 20260805_0033
Create Date: 2026-08-08
"""

from alembic import op


revision = "20260808_0034"
down_revision = "20260805_0033"
branch_labels = None
depends_on = None


_DROP_TABLES = (
    # Poll Live
    "live_aggregation_checkpoints",
    "live_aggregated_bars",
    "live_ingest_checkpoints",
    "live_minute_bars",
    # Task 06 observation
    "signal_decision_reconciliations",
    "research_samples",
    "retention_runs",
    "signal_decisions",
    "live_observation_bars",
    # Signal / Review / Watchlist
    "signal_notifications",
    "signal_events",
    "strategy_signals",
    "signal_scan_tasks",
    "review_attachments",
    "review_notes",
    "review_tags",
    "watchlist_items",
    "watchlists",
)


def upgrade() -> None:
    """Irreversibly drop retired research/live surfaces; missing tables are ignored."""

    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.signal_decisions') IS NOT NULL THEN
                EXECUTE 'DROP TRIGGER IF EXISTS trg_signal_decisions_immutable ON signal_decisions';
            END IF;
            DROP FUNCTION IF EXISTS reject_signal_decision_update() CASCADE;
        END
        $$;
        """
    )
    for table_name in _DROP_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')


def downgrade() -> None:
    raise RuntimeError(
        "retired surface drop is irreversible: recover schema and data from Git/RQData before attempting a downgrade"
    )
