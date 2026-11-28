"""Add the personal trade journal.

Revision ID: 20261128_0057
Revises: 20261124_0056
"""

from alembic import op

revision = "20261128_0057"
down_revision = "20261124_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE trade_journal_plans (
            id uuid PRIMARY KEY,
            trading_day date NOT NULL,
            product text,
            version integer NOT NULL CHECK (version > 0)
        )
    """)
    op.execute("""
        CREATE TABLE trade_journal_plan_revisions (
            plan_id uuid NOT NULL REFERENCES trade_journal_plans(id),
            version integer NOT NULL CHECK (version > 0),
            content jsonb NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (plan_id, version)
        )
    """)
    op.execute("""
        CREATE TABLE trade_journal_cases (
            id uuid PRIMARY KEY,
            trading_day date NOT NULL,
            product text NOT NULL,
            contract text NOT NULL,
            direction text NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            plan_id uuid,
            plan_version integer,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            title text NOT NULL,
            closed boolean NOT NULL DEFAULT false,
            review jsonb,
            tags text[] NOT NULL DEFAULT '{}',
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (plan_id, plan_version)
                REFERENCES trade_journal_plan_revisions(plan_id, version) MATCH FULL
        )
    """)
    op.execute("""
        CREATE TABLE trade_journal_events (
            id uuid PRIMARY KEY,
            case_id uuid NOT NULL REFERENCES trade_journal_cases(id),
            kind text NOT NULL,
            occurred_at timestamptz NOT NULL,
            trading_day date NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            removed_at timestamptz,
            removal_reason text,
            manual jsonb,
            source text,
            scope text,
            native_id text,
            replaces_manual uuid REFERENCES trade_journal_events(id),
            CHECK (
                (manual IS NOT NULL AND source IS NULL AND scope IS NULL
                    AND native_id IS NULL AND replaces_manual IS NULL)
                OR (manual IS NULL AND source IS NOT NULL AND scope IS NOT NULL AND native_id IS NOT NULL)
            ),
            CHECK ((removed_at IS NULL) = (removal_reason IS NULL))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX trade_journal_fill_assignment
        ON trade_journal_events (source, scope, native_id)
        WHERE removed_at IS NULL AND kind = 'FILL'
    """)
    op.execute("""
        CREATE UNIQUE INDEX trade_journal_case_comparison
        ON trade_journal_events (case_id, source, scope, native_id)
        WHERE removed_at IS NULL AND kind = 'COMPARISON'
    """)
    op.execute("""
        CREATE UNIQUE INDEX trade_journal_manual_replacement
        ON trade_journal_events (replaces_manual)
        WHERE removed_at IS NULL AND replaces_manual IS NOT NULL
    """)
    op.execute("CREATE INDEX trade_journal_event_timeline ON trade_journal_events (case_id, occurred_at, id)")
    op.execute("""
        CREATE INDEX trade_journal_event_day ON trade_journal_events (case_id, trading_day)
        WHERE removed_at IS NULL AND kind <> 'COMPARISON'
    """)
    op.execute("CREATE INDEX trade_journal_case_day ON trade_journal_cases (trading_day DESC, id)")
    op.execute("CREATE INDEX trade_journal_plan_day ON trade_journal_plans (trading_day, id)")
    op.execute("""
        CREATE TABLE trade_journal_summaries (
            period text NOT NULL CHECK (period IN ('day', 'week')),
            anchor date NOT NULL,
            version integer NOT NULL CHECK (version > 0),
            content jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (period, anchor),
            CHECK (period = 'day' OR extract(isodow FROM anchor) = 1)
        )
    """)
    op.execute("""
        CREATE TABLE trade_journal_mutations (
            id uuid PRIMARY KEY,
            fingerprint text NOT NULL,
            result jsonb
        )
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            LOCK TABLE trade_journal_mutations, trade_journal_plans, trade_journal_summaries,
                trade_journal_cases, trade_journal_events, trade_journal_plan_revisions
                IN ACCESS EXCLUSIVE MODE;
            IF EXISTS (SELECT 1 FROM trade_journal_mutations)
                OR EXISTS (SELECT 1 FROM trade_journal_plans)
                OR EXISTS (SELECT 1 FROM trade_journal_cases)
                OR EXISTS (SELECT 1 FROM trade_journal_summaries)
            THEN
                RAISE EXCEPTION 'TRADE_JOURNAL_NOT_EMPTY';
            END IF;
        END $$
    """)
    for table in ("mutations", "summaries", "events", "cases", "plan_revisions", "plans"):
        op.execute(f"DROP TABLE trade_journal_{table}")
