"""Execution Review application-domain ORM models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.alerts.models import AlertEvent
from app.db.base import Base


_REASON_ARRAY_TYPE = ARRAY(String(64)).with_variant(JSON(), "sqlite")
_REVIEW_ARRAY_TYPE = ARRAY(String(64)).with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for ORM-side defaults."""

    return datetime.now(UTC)


class TradeDecision(Base):
    """One human disposition for one immutable eligible AlertEvent."""

    __tablename__ = "trade_decisions"
    __table_args__ = (
        UniqueConstraint(
            "alert_event_id",
            name="uq_trade_decisions_alert_event",
        ),
        CheckConstraint(
            "disposition IN ('EXECUTED','NOT_EXECUTED')",
            name="ck_trade_decisions_disposition",
        ),
        CheckConstraint(
            "planned_stop_price IS NULL OR planned_stop_price > 0",
            name="ck_trade_decisions_stop_price_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_event_id: Mapped[int] = mapped_column(
        ForeignKey("alert_events.id"), nullable=False
    )
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    first_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    primary_not_execute_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    secondary_not_execute_reasons: Mapped[list[str]] = mapped_column(
        _REASON_ARRAY_TYPE, default=list, nullable=False
    )
    decision_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    execution_reason_tags: Mapped[list[str]] = mapped_column(
        _REASON_ARRAY_TYPE, default=list, nullable=False
    )
    planned_stop_price: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8), nullable=True
    )
    stop_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    alert_event: Mapped[AlertEvent] = relationship()


class TradeEpisode(Base):
    """One immutable symbol/contract/direction execution lifecycle."""

    __tablename__ = "trade_episodes"
    __table_args__ = (
        UniqueConstraint(
            "origin_decision_id",
            name="uq_trade_episodes_origin_decision",
        ),
        CheckConstraint(
            "direction IN ('LONG','SHORT')",
            name="ck_trade_episodes_direction",
        ),
        CheckConstraint(
            "contract_multiplier_snapshot IS NULL "
            "OR contract_multiplier_snapshot > 0",
            name="ck_trade_episodes_multiplier_positive",
        ),
        CheckConstraint(
            "((contract_multiplier_snapshot IS NULL "
            "AND multiplier_policy_id IS NULL) "
            "OR (contract_multiplier_snapshot IS NOT NULL "
            "AND multiplier_policy_id IS NOT NULL "
            "AND multiplier_policy_id = 'product_trade_multipliers_v1'))",
            name="ck_trade_episodes_multiplier_lineage",
        ),
        CheckConstraint(
            "((closed_at IS NULL AND close_reason IS NULL "
            "AND roll_reference_exit_price IS NULL "
            "AND roll_reference_bar_end IS NULL) "
            "OR (closed_at IS NOT NULL AND close_reason IS NOT NULL "
            "AND close_reason = 'DOMINANT_ROLL' "
            "AND roll_reference_exit_price IS NOT NULL "
            "AND roll_reference_bar_end IS NOT NULL) "
            "OR (closed_at IS NOT NULL AND close_reason IS NOT NULL "
            "AND close_reason = 'EXECUTION_NET_ZERO' "
            "AND roll_reference_exit_price IS NULL "
            "AND roll_reference_bar_end IS NULL))",
            name="ck_trade_episodes_lifecycle",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="ck_trade_episodes_closed_at",
        ),
        Index(
            "uq_trade_episodes_symbol_open",
            "symbol",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origin_decision_id: Mapped[int] = mapped_column(
        ForeignKey("trade_decisions.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    contract: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    roll_reference_exit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8), nullable=True
    )
    roll_reference_bar_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contract_multiplier_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8), nullable=True
    )
    multiplier_policy_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    origin_decision: Mapped[TradeDecision] = relationship()


class TradeExecution(Base):
    """One manually recorded execution fact in deterministic sequence order."""

    __tablename__ = "trade_executions"
    __table_args__ = (
        UniqueConstraint(
            "episode_id",
            "sequence_no",
            name="uq_trade_executions_episode_sequence",
        ),
        UniqueConstraint(
            "trigger_decision_id",
            name="uq_trade_executions_trigger_decision",
        ),
        CheckConstraint(
            "sequence_no > 0",
            name="ck_trade_executions_sequence_positive",
        ),
        CheckConstraint(
            "execution_type IN ('OPEN','ADD','REDUCE','CLOSE')",
            name="ck_trade_executions_type",
        ),
        CheckConstraint(
            "((execution_type = 'OPEN' AND sequence_no = 1) "
            "OR (execution_type <> 'OPEN' AND sequence_no > 1))",
            name="ck_trade_executions_open_sequence",
        ),
        CheckConstraint("price > 0", name="ck_trade_executions_price_positive"),
        CheckConstraint(
            "quantity > 0", name="ck_trade_executions_quantity_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("trade_episodes.id"), nullable=False
    )
    trigger_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("trade_decisions.id"), nullable=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer(), nullable=False)
    execution_type: Mapped[str] = mapped_column(String(16), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer(), nullable=False)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    episode: Mapped[TradeEpisode] = relationship(foreign_keys=[episode_id])
    trigger_decision: Mapped[TradeDecision | None] = relationship(
        foreign_keys=[trigger_decision_id]
    )


class TradeReview(Base):
    """One structured review for one closed TradeEpisode."""

    __tablename__ = "trade_reviews"
    __table_args__ = (
        UniqueConstraint("episode_id", name="uq_trade_reviews_episode"),
        CheckConstraint(
            "signal_execution_adherence IN ('ALIGNED','DEVIATED')",
            name="ck_trade_reviews_adherence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("trade_episodes.id"), nullable=False
    )
    signal_execution_adherence: Mapped[str] = mapped_column(
        String(16), nullable=False
    )
    entry_tags: Mapped[list[str]] = mapped_column(
        _REVIEW_ARRAY_TYPE, default=list, nullable=False
    )
    holding_tags: Mapped[list[str]] = mapped_column(
        _REVIEW_ARRAY_TYPE, default=list, nullable=False
    )
    exit_tags: Mapped[list[str]] = mapped_column(
        _REVIEW_ARRAY_TYPE, default=list, nullable=False
    )
    market_context_tags: Mapped[list[str]] = mapped_column(
        _REVIEW_ARRAY_TYPE, default=list, nullable=False
    )
    psychology_tags: Mapped[list[str]] = mapped_column(
        _REVIEW_ARRAY_TYPE, default=list, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    episode: Mapped[TradeEpisode] = relationship()
