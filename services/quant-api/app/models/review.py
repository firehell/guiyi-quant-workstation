from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.data_center import TimestampMixin, utc_now


class ReviewNote(Base, TimestampMixin):
    __tablename__ = "review_notes"
    __table_args__ = (UniqueConstraint("source_type", "source_id", name="uq_review_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    contract: Mapped[str | None] = mapped_column(String(64), index=True)
    period: Mapped[str | None] = mapped_column(String(16), index=True)
    direction: Mapped[str | None] = mapped_column(String(16), index=True)
    strategy_name: Mapped[str | None] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(32), index=True)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    open_price: Mapped[float | None] = mapped_column(Float)
    close_price: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    net_pnl: Mapped[float | None] = mapped_column(Float, index=True)
    entry_reason: Mapped[str | None] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    market_phase: Mapped[str | None] = mapped_column(String(32), index=True)
    is_system_compliant: Mapped[bool | None] = mapped_column(Boolean, index=True)
    mistake_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    rule_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    emotion_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    lesson: Mapped[str | None] = mapped_column(Text)
    screenshot_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    kline_focus_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kline_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kline_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_score: Mapped[int | None] = mapped_column(Integer)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_status: Mapped[str] = mapped_column(String(32), default="reserved", index=True)
    ai_model: Mapped[str | None] = mapped_column(String(64))
    ai_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReviewTag(Base, TimestampMixin):
    __tablename__ = "review_tags"
    __table_args__ = (UniqueConstraint("tag_type", "name", name="uq_review_tag_type_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ReviewAttachment(Base):
    __tablename__ = "review_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(Integer, index=True)
    file_path: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
