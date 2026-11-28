"""Store immutable statistics and research task identities."""
from alembic import op

revision = "20261128_0058"
down_revision = "20261128_0057"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE statistics_research_tasks (
            id uuid PRIMARY KEY,
            request jsonb NOT NULL,
            rerun_of uuid REFERENCES statistics_research_tasks(id),
            status text NOT NULL CHECK (status IN ('RUNNING', 'CANCELING', 'SUCCEEDED', 'FAILED', 'CANCELED')),
            started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            deadline timestamptz NOT NULL,
            reason text,
            input_digest text NOT NULL,
            result_digest text,
            result jsonb,
            CHECK ((status = 'SUCCEEDED') = (result IS NOT NULL AND result_digest IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ON statistics_research_tasks (started_at DESC, id DESC)")


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM statistics_research_tasks LIMIT 1) THEN
                RAISE EXCEPTION 'RESEARCH_TASK_HISTORY_EXISTS';
            END IF;
        END $$
    """)
    op.drop_table("statistics_research_tasks")
