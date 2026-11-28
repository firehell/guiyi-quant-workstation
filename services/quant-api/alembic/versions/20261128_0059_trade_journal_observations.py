"""Keep each chart observation and its original image together."""

from alembic import op

revision = "20261128_0059"
down_revision = "20261128_0058"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE trade_journal_observations (
            id uuid PRIMARY KEY,
            trading_day date NOT NULL,
            note text NOT NULL,
            snapshot jsonb NOT NULL,
            png bytea NOT NULL CHECK (octet_length(png) BETWEEN 1 AND 6291456),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute("CREATE INDEX trade_journal_observation_day ON trade_journal_observations (trading_day DESC, recorded_at DESC, id)")


def downgrade():
    op.execute("""
        DO $$ BEGIN
            LOCK TABLE trade_journal_observations IN ACCESS EXCLUSIVE MODE;
            IF EXISTS (SELECT 1 FROM trade_journal_observations) THEN
                RAISE EXCEPTION 'TRADE_JOURNAL_OBSERVATIONS_NOT_EMPTY';
            END IF;
        END $$
    """)
    op.drop_table("trade_journal_observations")
