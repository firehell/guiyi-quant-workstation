"""Alert application-domain ORM models.

These tables record rule scope and historical notification-attempt facts. They
are not part of the eight-table Market Catalog and never store market bars.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


_SCOPE_PRODUCTS_TYPE = ARRAY(String(32)).with_variant(JSON(), "sqlite")
_RESULT_CODES_TYPE = ARRAY(String(16)).with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for ORM-side defaults."""

    return datetime.now(UTC)


class AlertRule(Base):
    """A code-defined rule plus its server-side product scope."""

    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope_products: Mapped[list[str]] = mapped_column(
        _SCOPE_PRODUCTS_TYPE,
        default=list,
        nullable=False,
    )
    scope_product_frequencies: Mapped[dict[str, list[str]]] = mapped_column(
        JSON,
        default=dict,
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
            "cardinality(result_codes) BETWEEN 1 AND 2 "
            "AND result_codes <@ ARRAY["
            "'buy','sell','open_long','open_short','close_long','close_short'"
            "]::varchar[]",
            name="ck_alert_events_result_codes",
        ).ddl_if(dialect="postgresql"),
        Index("ix_alert_events_symbol_bar_end", "symbol", "bar_end"),
        Index(
            "ux_alert_events_action_id_not_null",
            "action_id",
            unique=True,
            postgresql_where=text("action_id IS NOT NULL"),
            sqlite_where=text("action_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    contract: Mapped[str] = mapped_column(String(64), nullable=False)
    trading_day: Mapped[date | None] = mapped_column(Date(), nullable=True)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_codes: Mapped[list[str]] = mapped_column(_RESULT_CODES_TYPE, nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    strategy_payload: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notification_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    rule: Mapped[AlertRule] = relationship(back_populates="events")
