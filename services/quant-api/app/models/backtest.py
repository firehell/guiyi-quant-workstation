from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.data_center import TimestampMixin, utc_now


class Watchlist(Base, TimestampMixin):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    items: Mapped[list["WatchlistItem"]] = relationship(back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_code", "symbol", name="uq_watchlist_item_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_code: Mapped[str] = mapped_column(ForeignKey("watchlists.code", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(64))
    exchange_code: Mapped[str | None] = mapped_column(String(16), index=True)
    default_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    watchlist: Mapped["Watchlist"] = relationship(back_populates="items")


class BacktestTask(Base):
    __tablename__ = "backtest_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_type: Mapped[str] = mapped_column(String(32), default="batch", index=True)
    engine_type: Mapped[str] = mapped_column(String(32), default="custom_v0", index=True)
    vnpy_strategy_class: Mapped[str | None] = mapped_column(String(256))
    vnpy_setting_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_source: Mapped[str | None] = mapped_column(String(32), index=True)
    data_role: Mapped[str | None] = mapped_column(String(32), index=True)
    data_version: Mapped[str | None] = mapped_column(String(64), index=True)
    research_only: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_result_path: Mapped[str | None] = mapped_column(Text)
    normalized_result_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reports: Mapped[list["BacktestReportModel"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class BacktestReportModel(Base):
    __tablename__ = "backtest_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("backtest_tasks.id", ondelete="CASCADE"), index=True)
    task_no: Mapped[str] = mapped_column(String(64), index=True)
    report_no: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    template_name: Mapped[str] = mapped_column(String(64), index=True)
    template_label: Mapped[str | None] = mapped_column(String(64))
    engine_type: Mapped[str] = mapped_column(String(32), default="custom_v0", index=True)
    engine_version: Mapped[str | None] = mapped_column(String(64))
    strategy_code: Mapped[str | None] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    contract: Mapped[str] = mapped_column(String(64), index=True)
    period: Mapped[str] = mapped_column(String(16), index=True)
    data_source: Mapped[str | None] = mapped_column(String(32), index=True)
    data_role: Mapped[str | None] = mapped_column(String(32), index=True)
    data_version: Mapped[str | None] = mapped_column(String(64), index=True)
    research_only: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    suitability_label: Mapped[str] = mapped_column(String(32), default="数据不足", index=True)
    suitability_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    initial_capital: Mapped[float] = mapped_column(Float, default=0.0)
    final_equity: Mapped[float] = mapped_column(Float, default=0.0)
    total_return: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    annual_return: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    profit_loss_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    trade_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    total_commission: Mapped[float] = mapped_column(Float, default=0.0)
    total_slippage: Mapped[float] = mapped_column(Float, default=0.0)
    quality_status: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    orders: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    fills: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    equity_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    drawdown_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw_result_path: Mapped[str | None] = mapped_column(Text)
    normalized_result_path: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    task: Mapped["BacktestTask"] = relationship(back_populates="reports")
    trades: Mapped[list["BacktestTradeModel"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    order_rows: Mapped[list["BacktestOrderModel"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    equity_points: Mapped[list["BacktestEquityCurvePointModel"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    drawdown_points: Mapped[list["BacktestDrawdownCurvePointModel"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class BacktestTradeModel(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("backtest_reports.id", ondelete="CASCADE"), index=True)
    trade_no: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    contract: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open_price: Mapped[float] = mapped_column(Float)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    close_price: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    turnover: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float)
    slippage: Mapped[float] = mapped_column(Float)
    gross_pnl: Mapped[float] = mapped_column(Float)
    net_pnl: Mapped[float] = mapped_column(Float, index=True)
    return_pct: Mapped[float] = mapped_column(Float)
    holding_bars: Mapped[int] = mapped_column(Integer)
    entry_reason: Mapped[str] = mapped_column(Text)
    exit_reason: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    report: Mapped["BacktestReportModel"] = relationship(back_populates="trades")


class BacktestOrderModel(Base):
    __tablename__ = "backtest_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("backtest_reports.id", ondelete="CASCADE"), index=True)
    order_no: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    contract: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    offset: Mapped[str | None] = mapped_column(String(16))
    order_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    order_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    traded: Mapped[float] = mapped_column(Float, default=0.0)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    report: Mapped["BacktestReportModel"] = relationship(back_populates="order_rows")


class BacktestEquityCurvePointModel(Base):
    __tablename__ = "backtest_equity_curve"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("backtest_reports.id", ondelete="CASCADE"), index=True)
    point_index: Mapped[int] = mapped_column(Integer, index=True)
    point_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    report: Mapped["BacktestReportModel"] = relationship(back_populates="equity_points")


class BacktestDrawdownCurvePointModel(Base):
    __tablename__ = "backtest_drawdown_curve"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("backtest_reports.id", ondelete="CASCADE"), index=True)
    point_index: Mapped[int] = mapped_column(Integer, index=True)
    point_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    report: Mapped["BacktestReportModel"] = relationship(back_populates="drawdown_points")
