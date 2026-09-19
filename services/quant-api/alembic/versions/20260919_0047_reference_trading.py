"""Add durable unified reference-trading schema.

Revision ID: 20260919_0047
Revises: 20260916_0046

Schema-only. It creates no enabled stream and performs no production data write.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260919_0047"
down_revision: str | Sequence[str] | None = "20260916_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "reference_streams",
        sa.Column("stream_id", sa.String(96), primary_key=True),
        sa.Column("identity_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("strategy_code", sa.String(96), nullable=False),
        sa.Column("formula_versions", JSONB(), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("reference_model_version", sa.String(128), nullable=False),
        sa.Column("futures_adaptation_version", sa.String(128), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("series_kind", sa.String(64), nullable=False),
        sa.Column("recording_mode", sa.String(32), nullable=False),
        sa.Column("observation_policy_version", sa.String(128)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active_revision_id", sa.String(64)),
        sa.Column("latest_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("health", sa.String(32), nullable=False, server_default="NOT_BUILT"),
        sa.CheckConstraint("row_version >= 0", name="ck_reference_streams_row_version"),
        sa.CheckConstraint(
            "recording_mode IN ('historical_replay','forward_observation')",
            name="ck_reference_streams_recording_mode",
        ),
        sa.CheckConstraint(
            "(recording_mode = 'forward_observation') = "
            "(observation_policy_version IS NOT NULL)",
            name="ck_reference_streams_observation_policy",
        ),
    )
    op.create_index(
        "ix_reference_streams_identity", "reference_streams",
        ["strategy_code", "product", "frequency", "recording_mode"],
    )
    op.create_table(
        "reference_revisions",
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("checkpoint_batch_id", sa.String(96)),
        sa.Column("dependency_digest", sa.String(64), nullable=False),
        sa.Column("parent_revision_id", sa.String(64)),
        sa.Column("invalid_reason", sa.String(256)),
        sa.PrimaryKeyConstraint("stream_id", "revision_id", name="pk_reference_revisions"),
        sa.UniqueConstraint("revision_id", name="uq_reference_revisions_global_id"),
        sa.ForeignKeyConstraint(["stream_id"], ["reference_streams.stream_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["stream_id", "parent_revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            name="fk_reference_revisions_parent", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('candidate','active','superseded','invalid')",
            name="ck_reference_revisions_status",
        ),
        sa.CheckConstraint("last_seq >= 0", name="ck_reference_revisions_last_seq"),
    )
    op.create_table(
        "reference_batches",
        sa.Column("batch_id", sa.String(96), primary_key=True),
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("batch_key", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("seq", sa.BigInteger()),
        sa.Column("expected_seq", sa.BigInteger(), nullable=False),
        sa.Column("pre_state_hash", sa.String(64)),
        sa.Column("post_state_hash", sa.String(64)),
        sa.Column("checkpoint_text", sa.Text()),
        sa.Column("strategy_schema", sa.String(128)),
        sa.Column("computed_through", sa.DateTime(timezone=True)),
        sa.Column("last_event_bar_end", sa.DateTime(timezone=True)),
        sa.Column("last_event_kind", sa.BigInteger()),
        sa.Column("last_event_sequence", sa.BigInteger()),
        sa.Column("dependency_manifest", JSONB(), nullable=False),
        sa.Column("source_evidence", JSONB(), nullable=False),
        sa.Column("projected_action_pks", JSONB(), nullable=False),
        sa.Column("diagnostics", JSONB(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed_chunk_index", sa.BigInteger()),
        sa.Column("seed_chunk_count", sa.BigInteger()),
        sa.Column("seed_root_hash", sa.String(64)),
        sa.Column("seed_chunk_text", sa.Text()),
        sa.UniqueConstraint("stream_id", "revision_id", "batch_key", name="uq_reference_batches_key"),
        sa.UniqueConstraint("stream_id", "revision_id", "batch_id", name="uq_reference_batches_owner"),
        sa.ForeignKeyConstraint(
            ["stream_id", "revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("expected_seq >= 0", name="ck_reference_batches_expected_seq"),
        sa.CheckConstraint("seq IS NULL OR seq > 0", name="ck_reference_batches_seq"),
        sa.CheckConstraint(
            "(kind = 'diagnostic' AND seq IS NULL) OR "
            "(kind = 'seed_chunk' AND seq IS NULL) OR "
            "(kind IN ('seed_seal','calculation') AND seq IS NOT NULL)",
            name="ck_reference_batches_kind_seq",
        ),
    )
    op.create_index(
        "uq_reference_batches_committed_seq", "reference_batches",
        ["stream_id", "revision_id", "seq"], unique=True,
        postgresql_where=sa.text("seq IS NOT NULL"),
    )
    op.create_table(
        "reference_actions",
        sa.Column("action_pk", sa.String(96), primary_key=True),
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("origin_revision_id", sa.String(64), nullable=False),
        sa.Column("batch_revision_id", sa.String(64), nullable=False),
        sa.Column("source_action_id", sa.String(160), nullable=False),
        sa.Column("recording_mode", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("physical_contract", sa.String(64), nullable=False),
        sa.Column("owner_segment_id", sa.String(160), nullable=False),
        sa.Column("calculation_segment_id", sa.String(160), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("reference_price", sa.Numeric(), nullable=False),
        sa.Column("reference_price_type", sa.String(64), nullable=False),
        sa.Column("entry_source_action_id", sa.String(160)),
        sa.Column("batch_id", sa.String(96), nullable=False),
        sa.Column("batch_seq", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("stream_id", "action_pk", name="uq_reference_actions_stream_pk"),
        sa.ForeignKeyConstraint(
            ["stream_id", "origin_revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "batch_revision_id", "batch_id"],
            ["reference_batches.stream_id", "reference_batches.revision_id", "reference_batches.batch_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_reference_actions_sequence"),
        sa.CheckConstraint("reference_price > 0", name="ck_reference_actions_price"),
        sa.CheckConstraint(
            "kind IN ('OPEN_LONG','OPEN_SHORT','CLOSE','HINT')",
            name="ck_reference_actions_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'CLOSE') = (entry_source_action_id IS NOT NULL)",
            name="ck_reference_actions_entry_link",
        ),
    )
    op.create_index(
        "ix_reference_actions_event", "reference_actions",
        ["stream_id", "bar_end", "sequence", "action_pk"],
    )
    op.create_index(
        "uq_reference_actions_historical_source", "reference_actions",
        ["stream_id", "origin_revision_id", "source_action_id"], unique=True,
    )
    op.create_index(
        "uq_reference_actions_forward_source", "reference_actions",
        ["stream_id", "source_action_id"], unique=True,
        postgresql_where=sa.text("recording_mode = 'forward_observation'"),
    )
    op.create_table(
        "reference_trades",
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("trade_id", sa.String(160), nullable=False),
        sa.Column("valid_from_seq", sa.BigInteger(), nullable=False),
        sa.Column("valid_to_seq", sa.BigInteger()),
        sa.Column("entry_action_pk", sa.String(96), nullable=False),
        sa.Column("exit_action_pk", sa.String(96)),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("physical_contract", sa.String(64), nullable=False),
        sa.Column("owner_segment_id", sa.String(160), nullable=False),
        sa.Column("calculation_segment_id", sa.String(160), nullable=False),
        sa.Column("entry_bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_trading_day", sa.Date(), nullable=False),
        sa.Column("entry_reference_price", sa.Numeric(), nullable=False),
        sa.Column("exit_bar_end", sa.DateTime(timezone=True)),
        sa.Column("exit_trading_day", sa.Date()),
        sa.Column("exit_reference_price", sa.Numeric()),
        sa.Column("reference_return", sa.Numeric()),
        sa.Column("holding_bars", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "stream_id", "revision_id", "trade_id", "valid_from_seq", name="pk_reference_trades",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "entry_action_pk"],
            ["reference_actions.stream_id", "reference_actions.action_pk"],
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "exit_action_pk"],
            ["reference_actions.stream_id", "reference_actions.action_pk"],
        ),
        sa.CheckConstraint("valid_to_seq IS NULL OR valid_to_seq > valid_from_seq", name="ck_reference_trades_validity"),
        sa.CheckConstraint("holding_bars >= 0", name="ck_reference_trades_holding"),
        sa.CheckConstraint("entry_reference_price > 0", name="ck_reference_trades_entry_price"),
        sa.CheckConstraint("side IN ('LONG','SHORT')", name="ck_reference_trades_side"),
        sa.CheckConstraint(
            "status IN ('OPEN','CLOSED','ROLLOVER_INTERRUPTED','DATA_INTERRUPTED','OBSERVATION_INTERRUPTED')",
            name="ck_reference_trades_status",
        ),
        sa.CheckConstraint(
            "(status = 'CLOSED' AND exit_action_pk IS NOT NULL AND exit_bar_end IS NOT NULL "
            "AND exit_trading_day IS NOT NULL AND exit_reference_price IS NOT NULL AND reference_return IS NOT NULL) "
            "OR (status <> 'CLOSED' AND exit_action_pk IS NULL AND exit_bar_end IS NULL "
            "AND exit_trading_day IS NULL AND exit_reference_price IS NULL AND reference_return IS NULL)",
            name="ck_reference_trades_exit_complete",
        ),
    )
    op.create_index(
        "uq_reference_trades_current", "reference_trades",
        ["stream_id", "revision_id", "trade_id"], unique=True,
        postgresql_where=sa.text("valid_to_seq IS NULL"),
    )
    op.create_index(
        "ix_reference_trades_entry", "reference_trades",
        ["stream_id", "revision_id", "entry_bar_end", "trade_id"],
    )
    op.create_table(
        "reference_marks",
        sa.Column("stream_id", sa.String(96), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("trade_id", sa.String(160), nullable=False),
        sa.Column("trade_valid_from_seq", sa.BigInteger(), nullable=False),
        sa.Column("batch_seq", sa.BigInteger(), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_action_pk", sa.String(96), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("reference_price", sa.Numeric(), nullable=False),
        sa.Column("holding_bars", sa.BigInteger(), nullable=False),
        sa.Column("reference_return", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint(
            "stream_id", "revision_id", "trade_id", "batch_seq", "bar_end", name="pk_reference_marks",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "revision_id", "trade_id", "trade_valid_from_seq"],
            ["reference_trades.stream_id", "reference_trades.revision_id", "reference_trades.trade_id", "reference_trades.valid_from_seq"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "entry_action_pk"],
            ["reference_actions.stream_id", "reference_actions.action_pk"],
        ),
        sa.CheckConstraint("holding_bars >= 0", name="ck_reference_marks_holding"),
        sa.CheckConstraint("reference_price > 0", name="ck_reference_marks_price"),
    )
    op.create_index(
        "ix_reference_marks_cutoff", "reference_marks",
        ["stream_id", "revision_id", "trade_id", "batch_seq", "bar_end"],
    )
    op.create_foreign_key(
        "fk_reference_streams_active_revision", "reference_streams", "reference_revisions",
        ["stream_id", "active_revision_id"], ["stream_id", "revision_id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reference_revisions_checkpoint_batch", "reference_revisions", "reference_batches",
        ["stream_id", "revision_id", "checkpoint_batch_id"],
        ["stream_id", "revision_id", "batch_id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise RuntimeError("REFERENCE_TRADING_DOWNGRADE_UNSUPPORTED")
