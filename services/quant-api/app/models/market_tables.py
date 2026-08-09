"""数据核心 V2 八表 ORM 定义。

八表构成 Catalog 元数据层，与 Canonical Parquet 物理文件通过 ``market_datasets``
+ ``market_partitions`` 关联；``MarketDataService`` 查询时依赖本层而非自行 glob。

表与 V2 角色：
- exchanges / instruments / contracts：品种与合约主数据
- trading_calendars / trading_sessions：交易日与会话边界（覆盖校验、bar 对齐）
- main_contract_map：每日主力合约映射（actual_dominant 查询拼接）
- market_datasets / market_partitions：逻辑数据集键与月分区物理指针
"""

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
    """ORM 默认时间戳：当前 UTC 时刻。"""
    return datetime.now(UTC)


class TimestampMixin:
    """为实体提供 created_at / updated_at 审计列。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Exchange(Base, TimestampMixin):
    """交易所主数据。

    V2 角色：Catalog 根节点；instruments/contracts 通过 exchange_code 关联。
    提供时区与国家等交易所级属性，供会话与日历查询。
    """

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
    """品种（产品）主数据，如 rb、IF。

    V2 角色：DatasetKey 中的 symbol；与 continuous 序列及 MainContractMap 的
    symbol 字段对应；关联该品种下全部合约行。
    """

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
    """具体合约主数据，如 rb2501。

    V2 角色：kind=contract 时 DatasetKey 的 series_or_contract；存储交割月、
    乘数、上市/到期日等；provider 标记数据来源（默认 rqdata）。
    """

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
    """交易所交易日历。

    V2 角色：判断 trade_date 是否为交易日、是否含夜盘；覆盖校验与 bar 交易日
    归属依赖本表，不得用自然日静默替代。
    """

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
    """品种交易时段定义（含生效日期窗口）。

    V2 角色：定义日内 session 边界与跨午夜标记；分钟 bar 对齐与 session 校验
    读取本表，支持按 instrument 与 effective_from/to 版本化。
    """

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
    """每日主力合约映射（rank=1，规则 volume_open_interest）。

    V2 角色：actual_dominant 查询模式的核心；按 symbol + trade_date 指向
    当日主力 contract_code，查询时动态拼接分段而非物理 continuous 文件切换。
    """

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
        """与 Instrument.symbol 对齐的别名属性。"""
        return self.symbol


class MarketDataset(Base):
    """逻辑市场数据集注册（DatasetKey 四元组之一行）。

    V2 角色：Catalog 核心索引。kind 仅 continuous / contract；frequency 为
    允许频度集合；与 partitions 一对多，消费者通过本表定位 Parquet 而非 glob。
    """

    __tablename__ = "market_datasets"
    __table_args__ = (
        UniqueConstraint(
            "kind", "symbol", "series_or_contract", "frequency",
            name="uq_market_datasets_key",
        ),
        CheckConstraint("kind IN ('continuous', 'contract')", name="ck_market_datasets_kind"),
        CheckConstraint(
            "frequency IN ('1m', '5m', '15m', '30m', '60m', '1d', '1w')",
            name="ck_market_datasets_frequency",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    series_or_contract: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MarketPartition(Base):
    """数据集月分区物理指针（Canonical Parquet part.parquet）。

    V2 角色：记录 coverage 窗口、行数与 file_uri；MarketDataService 按分区
    读取并校验物理完整性；月粒度与 staging 发布原子替换策略对齐。
    """

    __tablename__ = "market_partitions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "year", "month", name="uq_market_partitions_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_market_partitions_month"),
        CheckConstraint("coverage_start < coverage_end", name="ck_market_partitions_window"),
        CheckConstraint("row_count >= 0", name="ck_market_partitions_row_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("market_datasets.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    coverage_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_uri: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
