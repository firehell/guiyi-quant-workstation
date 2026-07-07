from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.data_center import utc_now


class SignalScanTask(Base):
    __tablename__ = "signal_scan_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    watchlist_code: Mapped[str] = mapped_column(String(32), index=True)
    periods: Mapped[list[str]] = mapped_column(JSON, default=list)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StrategySignal(Base):
    __tablename__ = "strategy_signals"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key",
            name="uq_strategy_signals_dedupe_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_no: Mapped[str | None] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), default="su_bing_ema21", index=True)
    strategy_version: Mapped[str] = mapped_column(String(32), default="v0", index=True)
    watchlist_code: Mapped[str | None] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    contract: Mapped[str] = mapped_column(String(64), index=True)
    product: Mapped[str | None] = mapped_column(String(32), index=True)
    continuous_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    actual_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    dominant_mapping_date: Mapped[date | None] = mapped_column(Date, index=True)
    exchange: Mapped[str | None] = mapped_column(String(16), index=True)
    period: Mapped[str] = mapped_column(String(16), index=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bar_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bar_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trigger_price: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    source: Mapped[str | None] = mapped_column(String(64), index=True)
    data_role: Mapped[str] = mapped_column(String(32), default="primary", server_default="primary", index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    signal_level: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_bucket: Mapped[int] = mapped_column(Integer, default=0, index=True)
    bucket_label: Mapped[str] = mapped_column(String(32), default="过滤", index=True)
    current_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float | None] = mapped_column(Float)
    stop_loss_price: Mapped[float | None] = mapped_column(Float)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float)
    open_volume: Mapped[int] = mapped_column(Integer, default=0)
    margin_required: Mapped[float] = mapped_column(Float, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    account_equity: Mapped[float] = mapped_column(Float, default=100000.0)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_status: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    research_contract: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    spec_source: Mapped[str | None] = mapped_column(String(64))
    alert_status: Mapped[str] = mapped_column(String(32), default="unread", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SignalNotification(Base):
    __tablename__ = "signal_notifications"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_signal_notifications_dedupe_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    task_no: Mapped[str | None] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(180), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="websocket", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignalEvent(Base):
    __tablename__ = "signal_events"
    __table_args__ = (UniqueConstraint("event_key", name="uq_signal_events_event_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(240), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    task_no: Mapped[str | None] = mapped_column(String(64), index=True)
    source_mode: Mapped[str] = mapped_column(String(32), index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str] = mapped_column(String(32), index=True)
    watchlist_code: Mapped[str | None] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    contract: Mapped[str] = mapped_column(String(64), index=True)
    product: Mapped[str | None] = mapped_column(String(32), index=True)
    continuous_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    actual_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    dominant_mapping_date: Mapped[date | None] = mapped_column(Date, index=True)
    exchange: Mapped[str | None] = mapped_column(String(16), index=True)
    period: Mapped[str] = mapped_column(String(16), index=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bar_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bar_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trigger_price: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    source: Mapped[str | None] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    signal_status: Mapped[str] = mapped_column(String(32), index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), index=True)
    score_bucket: Mapped[int] = mapped_column(Integer, default=0, index=True)
    data_role: Mapped[str] = mapped_column(String(32), default="primary", index=True)
    quality_status: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
