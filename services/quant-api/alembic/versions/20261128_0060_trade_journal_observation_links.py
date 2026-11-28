"""Relate immutable chart observations to journal case identities and exact plan revisions."""
from alembic import op

revision = "20261128_0060"
down_revision = "20261128_0059"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE trade_journal_observation_links (
            observation_id uuid NOT NULL REFERENCES trade_journal_observations(id),
            plan_id uuid,
            plan_version integer,
            case_id uuid REFERENCES trade_journal_cases(id),
            linked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK (num_nonnulls(plan_id,case_id) = 1),
            FOREIGN KEY (plan_id,plan_version) REFERENCES trade_journal_plan_revisions(plan_id,version) MATCH FULL,
            UNIQUE NULLS NOT DISTINCT (observation_id,plan_id,plan_version,case_id)
        )
    """)
    op.execute("CREATE INDEX trade_journal_observation_cases ON trade_journal_observation_links(case_id) WHERE case_id IS NOT NULL")
    op.execute("CREATE INDEX trade_journal_observation_plans ON trade_journal_observation_links(plan_id, plan_version) WHERE plan_id IS NOT NULL")


def downgrade():
    op.execute("""
        DO $$ BEGIN
            LOCK TABLE trade_journal_observation_links IN ACCESS EXCLUSIVE MODE;
            IF EXISTS (SELECT 1 FROM trade_journal_observation_links) THEN
                RAISE EXCEPTION 'TRADE_JOURNAL_OBSERVATION_LINKS_NOT_EMPTY';
            END IF;
        END $$
    """)
    op.drop_table("trade_journal_observation_links")
