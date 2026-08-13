"""Alert V1 application-domain ORM models.

These tables record rule scope and historical notification-attempt facts. They
are not part of the eight-table Market Catalog and never store market bars.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for ORM-side defaults."""

    return datetime.now(UTC)


class AlertRule(Base):
    """A code-defined rule plus its server-side product scope."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(
            "frequency IN ('1m','5m','15m','30m','60m','1d','1w')",
            name="ck_alert_rules_frequency",
        ),
        CheckConstraint(
            "scope_mode IN ('watchlist','operational_all')",
            name="ck_alert_rules_scope_mode",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope_mode: Mapped[str] = mapped_column(
        String(32), default="watchlist", nullable=False
    )
    scope_products: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)),
        default=list,
        server_default=text("'{}'::varchar[]"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    events: Mapped[list[AlertEvent]] = relationship(back_populates="rule")


class AlertEvent(Base):
    """Immutable fact that one rule triggered for one completed bar."""

    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "symbol",
            "frequency",
            "bar_end",
            name="uq_alert_events_rule_symbol_frequency_bar_end",
        ),
        CheckConstraint(
            "frequency IN ('1m','5m','15m','30m','60m','1d','1w')",
            name="ck_alert_events_frequency",
        ),
        CheckConstraint(
            "cardinality(observation_types) BETWEEN 1 AND 2 "
            "AND observation_types <@ ARRAY['buy','sell']::varchar[]",
            name="ck_alert_events_observation_types",
        ),
        Index("ix_alert_events_symbol_bar_end", "symbol", "bar_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    contract: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_types: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    rule: Mapped[AlertRule] = relationship(back_populates="events")
