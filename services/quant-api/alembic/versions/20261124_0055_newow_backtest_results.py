"""Add isolated Newow RQAlpha historical result storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261124_0055"
down_revision = "20261028_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newow_backtest_series",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("product", sa.String(12), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("research_profile_id", sa.String(80), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("published_run_id", sa.String(64)),
        sa.Column("last_attempt_id", sa.String(64)),
        sa.UniqueConstraint(
            "product", "strategy", "frequency", "research_profile_id",
            name="uq_newow_backtest_series_key",
        ),
        sa.CheckConstraint("generation >= 0", name="ck_newow_backtest_series_generation"),
    )
    op.create_table(
        "newow_backtest_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column(
            "series_id", sa.BigInteger(),
            sa.ForeignKey("newow_backtest_series.id"), nullable=False,
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("as_of_trading_day", sa.Date(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("summary", postgresql.JSONB()),
        sa.Column("result_digest", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("series_id", "run_id", name="uq_newow_backtest_runs_series_id"),
        sa.UniqueConstraint("series_id", "generation", name="uq_newow_backtest_runs_generation"),
        sa.CheckConstraint(
            """generation > 0 AND (
                (status = 'RUNNING' AND finished_at IS NULL
                 AND error_code IS NULL AND result_digest IS NULL)
                OR (status = 'FAILED' AND finished_at IS NOT NULL
                    AND error_code IS NOT NULL AND result_digest IS NULL)
                OR (status = 'SUCCEEDED' AND finished_at IS NOT NULL
                    AND error_code IS NULL AND result_digest IS NOT NULL)
            )""",
            name="ck_newow_backtest_runs_status",
        ),
    )
    for pointer in ("published_run_id", "last_attempt_id"):
        op.create_foreign_key(
            f"fk_newow_backtest_series_{pointer}", "newow_backtest_series",
            "newow_backtest_runs", ["id", pointer], ["series_id", "run_id"],
        )
    op.create_table(
        "newow_backtest_trades",
        sa.Column("run_id", sa.String(64), sa.ForeignKey("newow_backtest_runs.run_id"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("physical_contract", sa.String(24), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("position_effect", sa.String(12), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(28, 8), nullable=False),
        sa.Column("fee", sa.Numeric(28, 8), nullable=False),
        sa.Column("commission", sa.Numeric(28, 8)),
        sa.Column("tax", sa.Numeric(28, 8)),
        sa.Column("gross_pnl", sa.Numeric(28, 8)),
        sa.Column("net_pnl", sa.Numeric(28, 8)),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "seq > 0 AND quantity > 0 AND price > 0 AND fee >= 0 "
            "AND side IN ('BUY', 'SELL') AND position_effect IN ('OPEN', 'CLOSE', 'CLOSE_TODAY')",
            name="ck_newow_backtest_trades_values",
        ),
    )
    op.create_table(
        "newow_backtest_equity",
        sa.Column("run_id", sa.String(64), sa.ForeignKey("newow_backtest_runs.run_id"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("trading_day", sa.Date(), nullable=False),
        *[
            sa.Column(field, sa.Numeric(28, 8), nullable=False)
            for field in ("equity", "cash", "margin", "fees", "unrealized_pnl", "drawdown")
        ],
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "seq >= 0 AND margin >= 0 AND fees >= 0 AND drawdown >= 0",
            name="ck_newow_backtest_equity_values",
        ),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM newow_backtest_runs LIMIT 1")).first():
        raise RuntimeError("NEWOW_BACKTEST_DOWNGRADE_REQUIRES_EMPTY_RESULTS")
    op.drop_table("newow_backtest_equity")
    op.drop_table("newow_backtest_trades")
    for pointer in ("published_run_id", "last_attempt_id"):
        op.drop_constraint(f"fk_newow_backtest_series_{pointer}", "newow_backtest_series", type_="foreignkey")
    op.drop_table("newow_backtest_runs")
    op.drop_table("newow_backtest_series")
