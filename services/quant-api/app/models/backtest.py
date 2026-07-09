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
    consistency_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
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

    @property
    def initial_capital(self) -> float:
        return _summary_float(self.summary, "initial_capital", "capital")

    @property
    def final_equity(self) -> float:
        return _summary_float(self.summary, "final_equity", "ending_equity", "end_balance")

    @property
    def total_return(self) -> float:
        return _summary_float(self.summary, "total_return")

    @property
    def annual_return(self) -> float:
        return _summary_float(self.summary, "annual_return")

    @property
    def max_drawdown(self) -> float:
        return _summary_float(self.summary, "max_drawdown", "max_drawdown_pct")

    @property
    def max_drawdown_amount(self) -> float:
        return _summary_float(self.summary, "max_drawdown_amount")

    @property
    def max_drawdown_pct(self) -> float:
        return _summary_float(self.summary, "max_drawdown_pct", "max_drawdown")

    @property
    def win_rate(self) -> float:
        return _summary_float(self.summary, "win_rate")

    @property
    def profit_loss_ratio(self) -> float:
        return _summary_float(self.summary, "profit_loss_ratio")

    @property
    def trade_count(self) -> int:
        return _summary_int(self.summary, "trade_count", "total_trades", "total_trade_count")

    @property
    def max_consecutive_losses(self) -> int:
        return _summary_int(self.summary, "max_consecutive_losses")

    @property
    def total_commission(self) -> float:
        return _summary_float(self.summary, "total_commission")

    @property
    def total_slippage(self) -> float:
        return _summary_float(self.summary, "total_slippage")

    @property
    def max_margin_required(self) -> float:
        return _summary_float(self.summary, "max_margin_required")

    @property
    def max_margin_usage_pct(self) -> float:
        return _summary_float(self.summary, "max_margin_usage_pct")

    @property
    def rollover_exit_count(self) -> int:
        return _summary_int(self.summary, "rollover_exit_count")

    @property
    def delivery_risk_exit_count(self) -> int:
        return _summary_int(self.summary, "delivery_risk_exit_count")

    @property
    def quality_status(self) -> dict[str, Any]:
        summary = self.summary or {}
        value = summary.get("quality_status")
        if isinstance(value, dict):
            return value
        metadata = summary.get("report_metadata")
        if isinstance(metadata, dict) and metadata.get("quality_status") is not None:
            return {"status": metadata.get("quality_status")}
        return {}

    @quality_status.setter
    def quality_status(self, value: dict[str, Any] | None) -> None:
        summary = dict(self.summary or {})
        summary["quality_status"] = dict(value or {})
        self.summary = summary


class BacktestTradeModel(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("backtest_reports.id", ondelete="CASCADE"), index=True)
    trade_no: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="", index=True)
    research_contract: Mapped[str] = mapped_column(String(64), default="", index=True)
    contract: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="", index=True)
    entry_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    exit_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    entry_contract_month: Mapped[str | None] = mapped_column(String(16))
    exit_contract_month: Mapped[str | None] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(16), index=True)
    entry_signal_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    entry_signal_source: Mapped[str | None] = mapped_column(String(64), index=True)
    entry_order_no: Mapped[str | None] = mapped_column(String(64), index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open_price: Mapped[float] = mapped_column(Float)
    exit_signal_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    exit_signal_source: Mapped[str | None] = mapped_column(String(64), index=True)
    exit_order_no: Mapped[str | None] = mapped_column(String(64), index=True)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    close_price: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    turnover: Mapped[float] = mapped_column(Float)
    contract_multiplier: Mapped[int | None] = mapped_column(Integer)
    price_tick: Mapped[float | None] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float)
    slippage: Mapped[float] = mapped_column(Float)
    margin_ratio: Mapped[float | None] = mapped_column(Float)
    margin_required: Mapped[float | None] = mapped_column(Float)
    parameter_source: Mapped[str | None] = mapped_column(String(32), index=True)
    fee_rule_source: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    main_contract_source: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    rollover_forced_exit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delivery_risk_exit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rollover_reason: Mapped[str | None] = mapped_column(Text)
    gross_pnl: Mapped[float] = mapped_column(Float)
    net_pnl: Mapped[float] = mapped_column(Float, index=True)
    return_pct: Mapped[float] = mapped_column(Float)
    holding_bars: Mapped[int] = mapped_column(Integer)
    stop_loss_price: Mapped[float | None] = mapped_column(Float)
    entry_reason: Mapped[str] = mapped_column(Text)
    exit_reason: Mapped[str] = mapped_column(Text)
    lineage_status: Mapped[str | None] = mapped_column(String(32), index=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    report: Mapped["BacktestReportModel"] = relationship(back_populates="trades")


class BacktestOrderModel(Base):
    __tablename__ = "backtest_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("backtest_reports.id", ondelete="CASCADE"), index=True)
    order_no: Mapped[str] = mapped_column(String(64), index=True)
    trade_no: Mapped[str | None] = mapped_column(String(64), index=True)
    leg: Mapped[str | None] = mapped_column(String(16), index=True)
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
    lineage_source: Mapped[str | None] = mapped_column(String(64), index=True)
    mapping_status: Mapped[str | None] = mapped_column(String(32), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    report: Mapped["BacktestReportModel"] = relationship(back_populates="order_rows")


def _summary_float(summary: dict[str, Any] | None, *keys: str) -> float:
    for key in keys:
        value = (summary or {}).get(key)
        if value is not None and value != "":
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _summary_int(summary: dict[str, Any] | None, *keys: str) -> int:
    for key in keys:
        value = (summary or {}).get(key)
        if value is not None and value != "":
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0
    return 0
