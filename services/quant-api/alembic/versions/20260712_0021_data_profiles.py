"""data profiles and active bindings

Revision ID: 20260712_0021
Revises: 20260710_0020
Create Date: 2026-07-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260712_0021"
down_revision = "20260710_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("contract_roles", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("periods", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("quality_policy", sa.String(length=32), nullable=False, server_default="passed_only"),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="rqdata"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("profile_id", name="uq_data_profiles_profile_id"),
    )
    op.create_index("ix_data_profiles_profile_id", "data_profiles", ["profile_id"], unique=True)

    op.create_table(
        "profile_active_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_symbol", sa.String(length=32), nullable=False),
        sa.Column("contract_code", sa.String(length=64), nullable=False),
        sa.Column("contract_role", sa.String(length=32), nullable=False, server_default="dominant_main"),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("market_data_file_id", sa.Integer(), sa.ForeignKey("market_data_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("binding_status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "profile_id",
            "instrument_symbol",
            "contract_code",
            "period",
            "binding_status",
            name="uq_profile_active_binding_identity_status",
        ),
    )
    op.create_index("ix_profile_active_bindings_lookup", "profile_active_bindings", ["profile_id", "binding_status", "instrument_symbol", "contract_code", "period"])

    op.execute(
        sa.text(
            """
            INSERT INTO data_profiles (profile_id, label, description, contract_roles, periods, quality_policy, provider, config_path)
            VALUES
            ('intraday_research_v1', 'Intraday Research V1', 'V1-B intraday research profile for backtest and signal strict reads.', '["dominant_main"]', '["1m","5m","15m","30m","60m","1d"]', 'passed_only', 'rqdata', 'configs/data_profiles/intraday_research_v1.json'),
            ('long_horizon_daily_v1', 'Long Horizon Daily V1', '2020+ daily and weekly dominant/actual research profile.', '["dominant_main","actual_contract"]', '["1d","1w"]', 'passed_only', 'rqdata', 'configs/data_profiles/long_horizon_daily_v1.json'),
            ('live_observation_v1', 'Live Observation V1', 'JM live runtime observation profile; historical active bindings are read-only references.', '["dominant_main"]', '["1m","5m","15m","30m","60m","1d","1w"]', 'active_entry', 'rqdata', 'configs/data_profiles/live_observation_v1.json')
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO profile_active_bindings (
                profile_id, instrument_symbol, contract_code, contract_role, period, data_version, market_data_file_id, binding_status
            )
            SELECT
                'intraday_research_v1',
                ranked.instrument_symbol,
                ranked.contract_code,
                'dominant_main',
                ranked.period,
                ranked.data_version,
                ranked.id,
                'active'
            FROM (
                SELECT
                    m.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY m.instrument_symbol, m.contract_code, m.period
                        ORDER BY m.end_time DESC, m.id DESC
                    ) AS rn
                FROM market_data_files m
                WHERE m.instrument_symbol = 'jm'
                  AND m.contract_code = 'jm.MAIN'
                  AND m.period IN ('1m', '5m', '15m', '30m', '60m', '1d')
                  AND m.data_role = 'primary'
                  AND m.quality_status = 'passed'
                  AND m.provider = 'rqdata'
            ) ranked
            WHERE ranked.rn = 1
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_profile_active_bindings_lookup", table_name="profile_active_bindings")
    op.drop_table("profile_active_bindings")
    op.drop_index("ix_data_profiles_profile_id", table_name="data_profiles")
    op.drop_table("data_profiles")
