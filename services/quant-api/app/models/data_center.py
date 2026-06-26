from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="disabled", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    remark: Mapped[str | None] = mapped_column(Text)


class Exchange(Base, TimestampMixin):
    __tablename__ = "exchanges"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(16), default="CN")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="exchange")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="exchange")


class Instrument(Base, TimestampMixin):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    sector: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text)

    exchange: Mapped["Exchange"] = relationship(back_populates="instruments")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="instrument")


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    instrument_symbol: Mapped[str] = mapped_column(ForeignKey("instruments.symbol"), index=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    name: Mapped[str | None] = mapped_column(String(64))
    contract_month: Mapped[str | None] = mapped_column(String(16))
    contract_multiplier: Mapped[int | None] = mapped_column(Integer)
    trading_code: Mapped[str | None] = mapped_column(String(64), index=True)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    start_delivery_date: Mapped[date | None] = mapped_column(Date)
    end_delivery_date: Mapped[date | None] = mapped_column(Date)
    product: Mapped[str | None] = mapped_column(String(32), index=True)
    trading_hours: Mapped[str | None] = mapped_column(Text)
    listed_date: Mapped[date | None] = mapped_column(Date)
    expired_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    raw_symbol: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32), index=True)

    exchange: Mapped["Exchange"] = relationship(back_populates="contracts")
    instrument: Mapped["Instrument"] = relationship(back_populates="contracts")


class TradingCalendar(Base):
    __tablename__ = "trading_calendars"
    __table_args__ = (UniqueConstraint("exchange_code", "trade_date", name="uq_trading_calendar_exchange_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean)
    has_night_session: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    remark: Mapped[str | None] = mapped_column(Text)


class TradingSession(Base):
    __tablename__ = "trading_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    session_name: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FeeMarginRule(Base, TimestampMixin):
    __tablename__ = "fee_margin_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    contract_code: Mapped[str | None] = mapped_column(String(64), index=True)
    price_tick: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    volume_multiple: Mapped[int | None] = mapped_column(Integer)
    margin_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    open_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    close_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    close_today_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    fee_type: Mapped[str | None] = mapped_column(String(32))
    effective_date: Mapped[date | None] = mapped_column(Date, index=True)
    source: Mapped[str | None] = mapped_column(String(64))


class MainContractMap(Base, TimestampMixin):
    __tablename__ = "main_contract_map"
    __table_args__ = (
        UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "rank",
            "rule",
            "provider",
            "data_version",
            name="uq_main_contract_map_rank_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    rank: Mapped[int] = mapped_column(Integer, default=1, index=True)
    contract_code: Mapped[str] = mapped_column(String(64), index=True)
    rule: Mapped[str] = mapped_column(String(64), default="volume_open_interest", index=True)
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesExFactor(Base, TimestampMixin):
    __tablename__ = "futures_ex_factors"
    __table_args__ = (
        UniqueConstraint("instrument_symbol", "trade_date", "contract_code", "provider", "data_version", name="uq_futures_ex_factors_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    contract_code: Mapped[str | None] = mapped_column(String(64), index=True)
    prev_close_spread: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    open_spread: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    prev_close_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    open_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesTradingParameter(Base, TimestampMixin):
    __tablename__ = "futures_trading_parameters"
    __table_args__ = (
        UniqueConstraint("contract_code", "trade_date", "provider", "data_version", name="uq_futures_trading_parameters_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_code: Mapped[str] = mapped_column(String(64), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    exchange_code: Mapped[str | None] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    long_margin_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    short_margin_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    open_commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    close_commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    close_today_commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    commission_type: Mapped[str | None] = mapped_column(String(32))
    price_tick: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    contract_multiplier: Mapped[int | None] = mapped_column(Integer)
    min_order_quantity: Mapped[int | None] = mapped_column(Integer)
    max_order_quantity: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesWarehouseStock(Base, TimestampMixin):
    __tablename__ = "futures_warehouse_stocks"
    __table_args__ = (
        UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "warehouse",
            "provider",
            "data_version",
            name="uq_futures_warehouse_stocks_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse: Mapped[str] = mapped_column(String(128), default="", index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesRollYield(Base, TimestampMixin):
    __tablename__ = "futures_roll_yields"
    __table_args__ = (
        UniqueConstraint("instrument_symbol", "trade_date", "near_contract", "far_contract", "provider", "data_version", name="uq_futures_roll_yields_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    near_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    far_contract: Mapped[str | None] = mapped_column(String(64), index=True)
    roll_yield: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesBasis(Base, TimestampMixin):
    __tablename__ = "futures_basis"
    __table_args__ = (
        UniqueConstraint("contract_code", "trade_date", "provider", "data_version", name="uq_futures_basis_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_code: Mapped[str] = mapped_column(String(64), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    spot_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    futures_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    basis: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesContractUniverse(Base, TimestampMixin):
    __tablename__ = "futures_contract_universe"
    __table_args__ = (
        UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "contract_code",
            "provider",
            "data_version",
            name="uq_futures_contract_universe_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    contract_code: Mapped[str] = mapped_column(String(64), index=True)
    sort_order: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FuturesContinuousContractMap(Base, TimestampMixin):
    __tablename__ = "futures_continuous_contract_map"
    __table_args__ = (
        UniqueConstraint(
            "instrument_symbol",
            "trade_date",
            "continuous_type",
            "provider",
            "data_version",
            name="uq_futures_continuous_contract_map_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    continuous_type: Mapped[str] = mapped_column(String(32), index=True)
    contract_code: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="rqdata", index=True)
    data_version: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DataDownloadTask(Base):
    __tablename__ = "data_download_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    data_type: Mapped[str] = mapped_column(String(32), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    contract_code: Mapped[str | None] = mapped_column(String(64), index=True)
    period: Mapped[str | None] = mapped_column(String(16), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketDataFile(Base, TimestampMixin):
    __tablename__ = "market_data_files"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "data_type",
            "instrument_symbol",
            "contract_code",
            "period",
            "start_time",
            "end_time",
            "data_version",
            name="uq_market_data_file_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("data_download_tasks.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(32), index=True)
    data_type: Mapped[str] = mapped_column(String(32), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    contract_code: Mapped[str | None] = mapped_column(String(64), index=True)
    period: Mapped[str | None] = mapped_column(String(16), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(128))
    data_version: Mapped[str | None] = mapped_column(String(64), index=True)
    data_role: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    quality_status: Mapped[str] = mapped_column(String(32), default="unchecked", index=True)


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("market_data_files.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("data_download_tasks.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(32), index=True)
    data_type: Mapped[str] = mapped_column(String(32), index=True)
    instrument_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    contract_code: Mapped[str | None] = mapped_column(String(64), index=True)
    period: Mapped[str | None] = mapped_column(String(16), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    missing_bars: Mapped[int] = mapped_column(Integer, default=0)
    duplicated_bars: Mapped[int] = mapped_column(Integer, default=0)
    abnormal_price_count: Mapped[int] = mapped_column(Integer, default=0)
    abnormal_volume_count: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
