from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Exchange(Base, TimestampMixin):
    __tablename__ = "exchanges"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(16), default="CN")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    instruments: Mapped[list[Instrument]] = relationship(back_populates="exchange")
    contracts: Mapped[list[Contract]] = relationship(back_populates="exchange")


class Instrument(Base, TimestampMixin):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    sector: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[Exchange] = relationship(back_populates="instruments")
    contracts: Mapped[list[Contract]] = relationship(back_populates="instrument")


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
    provider: Mapped[str | None] = mapped_column(String(32), default="rqdata")
    exchange: Mapped[Exchange] = relationship(back_populates="contracts")
    instrument: Mapped[Instrument] = relationship(back_populates="contracts")


class TradingCalendar(Base):
    __tablename__ = "trading_calendars"
    __table_args__ = (
        UniqueConstraint("exchange_code", "trade_date", name="uq_trading_calendar_exchange_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_night_session: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), default="rqdata")
    remark: Mapped[str | None] = mapped_column(Text)


class TradingSession(Base):
    __tablename__ = "trading_sessions"
    __table_args__ = (
        UniqueConstraint(
            "exchange_code", "instrument_symbol", "session_name", "start_time", "end_time",
            "effective_from",
            name="uq_trading_sessions_identity",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from <= effective_to",
            name="ck_trading_sessions_effective_window",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"), index=True)
    instrument_symbol: Mapped[str] = mapped_column(String(32), index=True)
    session_name: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), default="rqdata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MainContractMap(Base, TimestampMixin):
    __tablename__ = "main_contract_map"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_main_contract_map_symbol_date"),
        CheckConstraint("rank = 1", name="ck_main_contract_map_rank1"),
        CheckConstraint("rule = 'volume_open_interest'", name="ck_main_contract_map_rule"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    contract_code: Mapped[str] = mapped_column(String(64), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    rule: Mapped[str] = mapped_column(String(64), default="volume_open_interest", nullable=False)

    @property
    def instrument_symbol(self) -> str:
        return self.symbol
