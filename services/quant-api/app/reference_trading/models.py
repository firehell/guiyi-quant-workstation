"""Six-table PostgreSQL schema for durable reference projections."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    JSON,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


JsonType = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
REFERENCE_TABLES = {
    "reference_streams",
    "reference_revisions",
    "reference_batches",
    "reference_actions",
    "reference_trades",
    "reference_marks",
}


class ReferenceStream(Base):
    __tablename__ = "reference_streams"
    __table_args__ = (
        ForeignKeyConstraint(
            ["stream_id", "active_revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            name="fk_reference_streams_active_revision",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        CheckConstraint("row_version >= 0", name="ck_reference_streams_row_version"),
        CheckConstraint(
            "recording_mode IN ('historical_replay','forward_observation')",
            name="ck_reference_streams_recording_mode",
        ),
        CheckConstraint(
            "(recording_mode = 'forward_observation') = (observation_policy_version IS NOT NULL)",
            name="ck_reference_streams_observation_policy",
        ),
        Index(
            "ix_reference_streams_identity",
            "strategy_code", "product", "frequency", "recording_mode",
        ),
    )

    stream_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    strategy_code: Mapped[str] = mapped_column(String(96), nullable=False)
    formula_versions: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    futures_adaptation_version: Mapped[str] = mapped_column(String(128), nullable=False)
    product: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    series_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    recording_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_policy_version: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    active_revision_id: Mapped[str | None] = mapped_column(String(64))
    latest_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"), nullable=False)
    health: Mapped[str] = mapped_column(String(32), default="NOT_BUILT", server_default=text("'NOT_BUILT'"), nullable=False)


class ReferenceRevision(Base):
    __tablename__ = "reference_revisions"
    __table_args__ = (
        PrimaryKeyConstraint("stream_id", "revision_id", name="pk_reference_revisions"),
        UniqueConstraint("revision_id", name="uq_reference_revisions_global_id"),
        ForeignKeyConstraint(["stream_id"], ["reference_streams.stream_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["stream_id", "parent_revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            name="fk_reference_revisions_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["stream_id", "revision_id", "checkpoint_batch_id"],
            ["reference_batches.stream_id", "reference_batches.revision_id", "reference_batches.batch_id"],
            name="fk_reference_revisions_checkpoint_batch",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('candidate','active','superseded','invalid')", name="ck_reference_revisions_status"),
        CheckConstraint("last_seq >= 0", name="ck_reference_revisions_last_seq"),
    )

    stream_id: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"), nullable=False)
    checkpoint_batch_id: Mapped[str | None] = mapped_column(String(96))
    dependency_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(String(64))
    invalid_reason: Mapped[str | None] = mapped_column(String(256))


class ReferenceBatch(Base):
    __tablename__ = "reference_batches"
    __table_args__ = (
        UniqueConstraint("stream_id", "revision_id", "batch_key", name="uq_reference_batches_key"),
        UniqueConstraint("stream_id", "revision_id", "batch_id", name="uq_reference_batches_owner"),
        ForeignKeyConstraint(
            ["stream_id", "revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("seq IS NULL OR seq > 0", name="ck_reference_batches_seq"),
        CheckConstraint("expected_seq >= 0", name="ck_reference_batches_expected_seq"),
        CheckConstraint(
            "(kind = 'diagnostic' AND seq IS NULL) OR "
            "(kind = 'seed_chunk' AND seq IS NULL) OR "
            "(kind IN ('seed_seal','calculation') AND seq IS NOT NULL)",
            name="ck_reference_batches_kind_seq",
        ),
        Index(
            "uq_reference_batches_committed_seq", "stream_id", "revision_id", "seq",
            unique=True, postgresql_where=text("seq IS NOT NULL"), sqlite_where=text("seq IS NOT NULL"),
        ),
    )

    batch_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    seq: Mapped[int | None] = mapped_column(BigInteger)
    expected_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pre_state_hash: Mapped[str | None] = mapped_column(String(64))
    post_state_hash: Mapped[str | None] = mapped_column(String(64))
    checkpoint_text: Mapped[str | None] = mapped_column(Text)
    strategy_schema: Mapped[str | None] = mapped_column(String(128))
    computed_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_bar_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_kind: Mapped[int | None] = mapped_column(BigInteger)
    last_event_sequence: Mapped[int | None] = mapped_column(BigInteger)
    dependency_manifest: Mapped[dict[str, object]] = mapped_column(JsonType, nullable=False)
    source_evidence: Mapped[dict[str, object]] = mapped_column(JsonType, nullable=False)
    projected_action_pks: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    diagnostics: Mapped[list[str]] = mapped_column(JsonType, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seed_chunk_index: Mapped[int | None] = mapped_column(BigInteger)
    seed_chunk_count: Mapped[int | None] = mapped_column(BigInteger)
    seed_root_hash: Mapped[str | None] = mapped_column(String(64))
    seed_chunk_text: Mapped[str | None] = mapped_column(Text)


class ReferenceActionRow(Base):
    __tablename__ = "reference_actions"
    __table_args__ = (
        UniqueConstraint("stream_id", "action_pk", name="uq_reference_actions_stream_pk"),
        ForeignKeyConstraint(
            ["stream_id", "origin_revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["stream_id", "batch_revision_id", "batch_id"],
            ["reference_batches.stream_id", "reference_batches.revision_id", "reference_batches.batch_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence >= 0", name="ck_reference_actions_sequence"),
        CheckConstraint("reference_price > 0", name="ck_reference_actions_price"),
        CheckConstraint("kind IN ('OPEN_LONG','OPEN_SHORT','CLOSE','HINT')", name="ck_reference_actions_kind"),
        CheckConstraint(
            "(kind = 'CLOSE') = (entry_source_action_id IS NOT NULL)",
            name="ck_reference_actions_entry_link",
        ),
        Index("ix_reference_actions_event", "stream_id", "bar_end", "sequence", "action_pk"),
        Index(
            "uq_reference_actions_historical_source", "stream_id", "origin_revision_id", "source_action_id",
            unique=True,
        ),
        Index(
            "uq_reference_actions_forward_source", "stream_id", "source_action_id",
            unique=True,
            postgresql_where=text("recording_mode = 'forward_observation'"),
            sqlite_where=text("recording_mode = 'forward_observation'"),
        ),
    )

    action_pk: Mapped[str] = mapped_column(String(96), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(96), nullable=False)
    origin_revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_action_id: Mapped[str] = mapped_column(String(160), nullable=False)
    recording_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    physical_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_segment_id: Mapped[str] = mapped_column(String(160), nullable=False)
    calculation_segment_id: Mapped[str] = mapped_column(String(160), nullable=False)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reference_price: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    reference_price_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_source_action_id: Mapped[str | None] = mapped_column(String(160))
    batch_id: Mapped[str] = mapped_column(String(96), nullable=False)
    batch_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReferenceTradeRow(Base):
    __tablename__ = "reference_trades"
    __table_args__ = (
        PrimaryKeyConstraint("stream_id", "revision_id", "trade_id", "valid_from_seq", name="pk_reference_trades"),
        ForeignKeyConstraint(
            ["stream_id", "revision_id"],
            ["reference_revisions.stream_id", "reference_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["stream_id", "entry_action_pk"], ["reference_actions.stream_id", "reference_actions.action_pk"]),
        ForeignKeyConstraint(["stream_id", "exit_action_pk"], ["reference_actions.stream_id", "reference_actions.action_pk"]),
        CheckConstraint("valid_to_seq IS NULL OR valid_to_seq > valid_from_seq", name="ck_reference_trades_validity"),
        CheckConstraint("holding_bars >= 0", name="ck_reference_trades_holding"),
        CheckConstraint("entry_reference_price > 0", name="ck_reference_trades_entry_price"),
        CheckConstraint("side IN ('LONG','SHORT')", name="ck_reference_trades_side"),
        CheckConstraint(
            "status IN ('OPEN','CLOSED','ROLLOVER_INTERRUPTED','DATA_INTERRUPTED',"
            "'OBSERVATION_INTERRUPTED')",
            name="ck_reference_trades_status",
        ),
        CheckConstraint(
            "(status = 'CLOSED' AND exit_action_pk IS NOT NULL AND exit_bar_end IS NOT NULL "
            "AND exit_trading_day IS NOT NULL AND exit_reference_price IS NOT NULL AND reference_return IS NOT NULL) "
            "OR (status <> 'CLOSED' AND exit_action_pk IS NULL AND exit_bar_end IS NULL "
            "AND exit_trading_day IS NULL AND exit_reference_price IS NULL AND reference_return IS NULL)",
            name="ck_reference_trades_exit_complete",
        ),
        Index(
            "uq_reference_trades_current", "stream_id", "revision_id", "trade_id",
            unique=True, postgresql_where=text("valid_to_seq IS NULL"), sqlite_where=text("valid_to_seq IS NULL"),
        ),
        Index("ix_reference_trades_entry", "stream_id", "revision_id", "entry_bar_end", "trade_id"),
    )

    stream_id: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_id: Mapped[str] = mapped_column(String(160), nullable=False)
    valid_from_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valid_to_seq: Mapped[int | None] = mapped_column(BigInteger)
    entry_action_pk: Mapped[str] = mapped_column(String(96), nullable=False)
    exit_action_pk: Mapped[str | None] = mapped_column(String(96))
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    physical_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_segment_id: Mapped[str] = mapped_column(String(160), nullable=False)
    calculation_segment_id: Mapped[str] = mapped_column(String(160), nullable=False)
    entry_bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    entry_reference_price: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    exit_bar_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_trading_day: Mapped[date | None] = mapped_column(Date)
    exit_reference_price: Mapped[Decimal | None] = mapped_column(Numeric())
    reference_return: Mapped[Decimal | None] = mapped_column(Numeric())
    holding_bars: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReferenceMarkRow(Base):
    __tablename__ = "reference_marks"
    __table_args__ = (
        PrimaryKeyConstraint("stream_id", "revision_id", "trade_id", "batch_seq", "bar_end", name="pk_reference_marks"),
        ForeignKeyConstraint(
            ["stream_id", "revision_id", "trade_id", "trade_valid_from_seq"],
            ["reference_trades.stream_id", "reference_trades.revision_id", "reference_trades.trade_id", "reference_trades.valid_from_seq"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["stream_id", "entry_action_pk"], ["reference_actions.stream_id", "reference_actions.action_pk"]),
        CheckConstraint("holding_bars >= 0", name="ck_reference_marks_holding"),
        CheckConstraint("reference_price > 0", name="ck_reference_marks_price"),
        Index("ix_reference_marks_cutoff", "stream_id", "revision_id", "trade_id", "batch_seq", "bar_end"),
    )

    stream_id: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_id: Mapped[str] = mapped_column(String(160), nullable=False)
    trade_valid_from_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    batch_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_action_pk: Mapped[str] = mapped_column(String(96), nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    holding_bars: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_return: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
