"""市场数据领域模型与查询契约（数据核心 V2）。

本模块定义 MarketDataService 及其上下游共用的**不可变值对象**与**输入校验边界**：
- ``DatasetKey``：物理 Parquet 数据集的四元组身份（kind / symbol / series / frequency）；
- ``SeriesQuery``：消费者查询意图（含 ``actual_dominant`` 逻辑序列，无独立物理数据集）；
- ``CanonicalBar``：canonical Parquet 行的内存表示，含 OHLCV 与交易日语义。

在 V2 链路中的位置：RQData → staging → canonical Parquet → 八表 Catalog →
``MarketDataService``；本文件不访问存储或数据库，只负责 fail-closed 契约校验，
确保非法身份、窗口或 bar 形态在进入服务层前即被拒绝。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping


class ContractError(ValueError):
    """市场数据公共契约校验失败。

    对外只暴露结构化 ``facts``（字段名、原因码、可选原始值），
    不携带 provider、存储路径或内部堆栈，便于 API/CLI 统一映射为客户端错误。
    """

    code = "MARKET_DATA_CONTRACT_INVALID"

    def __init__(self, *, field: str, reason: str, value: object | None = None) -> None:
        facts: dict[str, object] = {"field": field, "reason": reason}
        if value is not None:
            facts["value"] = str(value)
        self.facts: Mapping[str, object] = MappingProxyType(facts)
        super().__init__(self.code)


class DatasetKind(StrEnum):
    """物理数据集种类：连续主力（continuous）或具体合约（contract）。"""

    CONTINUOUS = "continuous"
    CONTRACT = "contract"


class SeriesKind(StrEnum):
    """查询序列种类。

    ``ACTUAL_DOMINANT`` 为查询时按 ``MainContractMap`` 拼接的逻辑序列，
    不对应单一物理 Parquet 根目录；其余种类可映射到 ``DatasetKey``。
    """

    CONTINUOUS = "continuous"
    ACTUAL_DOMINANT = "actual_dominant"
    CONTRACT = "contract"


class BarFrequency(StrEnum):
    """K 线频率枚举，与 canonical 分区目录及 Catalog 字段一致。"""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "60m"
    D1 = "1d"
    W1 = "1w"


# 基础 provider 数据：1m 由 get_price 获取，1d 由交易所日行情获取。
BASE_PROVIDER_FREQUENCIES = frozenset({BarFrequency.M1, BarFrequency.D1})
# 派生数据：日内频度由 Canonical 1m 聚合，1w 由完整同源 1d 聚合。
INTRADAY_DERIVED_FREQUENCIES = frozenset(
    {BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1}
)
DERIVED_FREQUENCIES = INTRADAY_DERIVED_FREQUENCIES | frozenset({BarFrequency.W1})
ALL_FREQUENCIES = BASE_PROVIDER_FREQUENCIES | DERIVED_FREQUENCIES
# HistoricalDataManager 需经 BarSource 取得的目标：1w 的 adapter 在此步骤内聚合日线。
PROVIDER_FETCH_FREQUENCIES = BASE_PROVIDER_FREQUENCIES | frozenset({BarFrequency.W1})
# RQData 连续/日内历史下限（get_dominant_price / A88 观测值），用于 coverage 边界校验
RQDATA_INTRADAY_HISTORY_START = date(2010, 1, 4)
INTRADAY_FREQUENCIES = frozenset(
    {
        BarFrequency.M1,
        BarFrequency.M5,
        BarFrequency.M15,
        BarFrequency.M30,
        BarFrequency.H1,
    }
)
_SYMBOL = re.compile(r"[A-Z]+\Z")
_CONTRACT = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")


def normalize_contract_for_symbol(symbol: str, value: object) -> str | None:
    """规范化真实期货合约，并拒绝跨品种、非法月份和非字符串输入。"""
    if not isinstance(value, str):
        return None
    contract = value.strip().upper()
    match = _CONTRACT.fullmatch(contract)
    if match is None or match.group(1) != symbol.strip().upper():
        return None
    month = int(contract[-2:])
    return contract if 1 <= month <= 12 else None


def parse_rfc3339_instant(value: str, *, field: str) -> datetime:
    """解析带时区 RFC3339 时间并规范化为 UTC。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(field=field, reason="rfc3339_required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(field=field, reason="timezone_required")
    return parsed.astimezone(UTC)


def _enum(enum_type: type[StrEnum], value: object, *, field: str) -> Any:
    """将字符串规范化为 StrEnum；类型或取值非法时抛出 ``ContractError``。"""
    if not isinstance(value, str):
        raise ContractError(field=field, reason="unsupported", value=value)
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(field=field, reason="unsupported", value=value) from exc


def _text(value: object, *, field: str, upper: bool = False) -> str:
    """要求非空字符串；可选转大写（合约代码）或小写（品种 symbol）。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(field=field, reason="nonempty_text_required")
    normalized = value.strip()
    return normalized.upper() if upper else normalized.lower()


def _window(start: object, end: object) -> tuple[datetime, datetime]:
    """校验查询窗口：两端须带时区，且 start < end（统一转为 UTC）。"""
    if not isinstance(start, datetime) or start.tzinfo is None or start.utcoffset() is None:
        raise ContractError(field="start", reason="timezone_required")
    if not isinstance(end, datetime) or end.tzinfo is None or end.utcoffset() is None:
        raise ContractError(field="end", reason="timezone_required")
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if start_utc >= end_utc:
        raise ContractError(field="window", reason="start_must_precede_end")
    return start_utc, end_utc


@dataclass(frozen=True, slots=True)
class DatasetKey:
    """物理 canonical 数据集身份（四字段 V2 目标模型的核心键）。

    - ``continuous``：``series_or_contract`` 固定为 ``MAIN``；
    - ``contract``：``series_or_contract`` 为具体合约代码，且品种前缀须与 ``symbol`` 一致。

    ``relative_root`` 决定 Parquet 在 canonical 根下的目录布局，消费者不得自行拼路径。
    """

    kind: DatasetKind
    symbol: str
    series_or_contract: str
    frequency: BarFrequency

    def __post_init__(self) -> None:
        kind = _enum(DatasetKind, self.kind, field="kind")
        symbol = _text(self.symbol, field="symbol")
        if _SYMBOL.fullmatch(symbol.upper()) is None:
            raise ContractError(field="symbol", reason="invalid", value=symbol)
        series = _text(self.series_or_contract, field="series_or_contract", upper=True)
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        if kind is DatasetKind.CONTINUOUS:
            # 连续主力在物理层只有 MAIN 序列，不允许其他 series 名
            if series != "MAIN":
                raise ContractError(
                    field="series_or_contract",
                    reason="continuous_requires_main",
                    value=series,
                )
        else:
            match = _CONTRACT.fullmatch(series)
            if match is None:
                raise ContractError(
                    field="series_or_contract",
                    reason="concrete_contract_required",
                    value=series,
                )
            # 防止 RB2501 挂到品种 hc 等跨品种误读
            if match.group(1) != symbol.upper():
                raise ContractError(
                    field="series_or_contract",
                    reason="contract_symbol_mismatch",
                    value=series,
                )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "series_or_contract", series)
        object.__setattr__(self, "frequency", frequency)

    def as_tuple(self) -> tuple[str, str, str, str]:
        """返回与 Catalog ``MarketDataset`` 四列对应的字符串元组。"""
        return (self.kind.value, self.symbol, self.series_or_contract, self.frequency.value)

    @property
    def relative_root(self) -> PurePosixPath:
        """canonical 根下的相对目录路径（POSIX，用于存储层拼接月分区）。"""
        return PurePosixPath(
            f"kind={self.kind.value}",
            f"symbol={self.symbol}",
            f"series={self.series_or_contract}",
            f"frequency={self.frequency.value}",
        )


@dataclass(frozen=True, slots=True)
class SeriesQuery:
    """消费者查询请求：逻辑序列种类 + 品种 + 频率 + 半开时间窗口 ``(start, end]``。

    ``physical_key`` 在 ``actual_dominant`` 时为 ``None``，由服务层按主力映射拼接；
    ``contract`` 仅在 ``SeriesKind.CONTRACT`` 时必填，且会经 ``DatasetKey`` 再校验一次。
    """

    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    start: datetime
    end: datetime
    contract: str | None = None

    def __post_init__(self) -> None:
        kind = _enum(SeriesKind, self.series_kind, field="series_kind")
        symbol = _text(self.symbol, field="symbol")
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        start, end = _window(self.start, self.end)
        contract = self.contract
        if kind is SeriesKind.CONTRACT:
            if contract is None:
                raise ContractError(field="contract", reason="required_for_contract_series")
            # 借 DatasetKey 规范化合约代码并校验品种前缀
            contract = DatasetKey(
                kind=DatasetKind.CONTRACT,
                symbol=symbol,
                series_or_contract=contract,
                frequency=frequency,
            ).series_or_contract
        elif contract is not None:
            raise ContractError(field="contract", reason="forbidden_for_series_kind")
        object.__setattr__(self, "series_kind", kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "contract", contract)

    @property
    def physical_key(self) -> DatasetKey | None:
        """映射到单一物理数据集；``actual_dominant`` 无物理键，返回 ``None``。"""
        if self.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return None
        if self.series_kind is SeriesKind.CONTINUOUS:
            return DatasetKey(
                kind=DatasetKind.CONTINUOUS,
                symbol=self.symbol,
                series_or_contract="MAIN",
                frequency=self.frequency,
            )
        assert self.contract is not None
        return DatasetKey(
            kind=DatasetKind.CONTRACT,
            symbol=self.symbol,
            series_or_contract=self.contract,
            frequency=self.frequency,
        )


@dataclass(frozen=True, slots=True)
class ActualDominantTradingDayQuery:
    """Research-only actual-dominant request with exact trading-day bounds.

    ``MarketDataService`` resolves the first and last historical Session windows
    before constructing the canonical instant-based ``SeriesQuery``.  Consumers
    therefore do not guess night-session boundaries from natural dates.
    """

    symbol: str
    frequency: BarFrequency
    since: date
    through: date

    def __post_init__(self) -> None:
        symbol = _text(self.symbol, field="symbol")
        if _SYMBOL.fullmatch(symbol.upper()) is None:
            raise ContractError(field="symbol", reason="invalid", value=symbol)
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ContractError(field="trading_day_window", reason="invalid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class ContractTradingDayQuery:
    """Research-only physical-contract request with exact trading-day bounds."""

    symbol: str
    contract: str
    frequency: BarFrequency
    since: date
    through: date

    def __post_init__(self) -> None:
        symbol = _text(self.symbol, field="symbol")
        if _SYMBOL.fullmatch(symbol.upper()) is None:
            raise ContractError(field="symbol", reason="invalid", value=symbol)
        contract = normalize_contract_for_symbol(symbol, self.contract)
        if contract is None:
            raise ContractError(field="contract", reason="invalid", value=self.contract)
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ContractError(field="trading_day_window", reason="invalid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class SeriesPageQuery:
    """历史游标分页请求：返回严格早于 ``before`` 的最新 bars。"""

    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    before: datetime | None = None
    limit: int = 1200
    contract: str | None = None

    def __post_init__(self) -> None:
        kind = _enum(SeriesKind, self.series_kind, field="series_kind")
        symbol = _text(self.symbol, field="symbol")
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        before = self.before
        if before is not None:
            if (
                not isinstance(before, datetime)
                or before.tzinfo is None
                or before.utcoffset() is None
            ):
                raise ContractError(field="before", reason="timezone_required")
            before = before.astimezone(UTC)
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise ContractError(field="limit", reason="integer_required")
        if not 1 <= self.limit <= 2000:
            raise ContractError(field="limit", reason="range_invalid")
        contract = self.contract
        if kind is SeriesKind.CONTRACT:
            if contract is None:
                raise ContractError(field="contract", reason="required_for_contract_series")
            contract = DatasetKey(
                kind=DatasetKind.CONTRACT,
                symbol=symbol,
                series_or_contract=contract,
                frequency=frequency,
            ).series_or_contract
        elif contract is not None:
            raise ContractError(field="contract", reason="forbidden_for_series_kind")
        object.__setattr__(self, "series_kind", kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "contract", contract)

    @property
    def physical_key(self) -> DatasetKey | None:
        """映射到单一物理数据集；``actual_dominant`` 无物理键。"""
        if self.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return None
        if self.series_kind is SeriesKind.CONTINUOUS:
            return DatasetKey(
                kind=DatasetKind.CONTINUOUS,
                symbol=self.symbol,
                series_or_contract="MAIN",
                frequency=self.frequency,
            )
        assert self.contract is not None
        return DatasetKey(
            kind=DatasetKind.CONTRACT,
            symbol=self.symbol,
            series_or_contract=self.contract,
            frequency=self.frequency,
        )


def _decimal(value: Decimal | int | str | None, *, field: str, optional: bool = False) -> Decimal | None:
    """解析有限 Decimal；可选字段允许 ``None``，否则缺失或非有限值 fail-closed。"""
    if value is None:
        if optional:
            return None
        raise ContractError(field=field, reason="required")
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ContractError(field=field, reason="decimal_required")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(field=field, reason="decimal_required") from exc
    if not result.is_finite():
        raise ContractError(field=field, reason="finite_required")
    return result


@dataclass(frozen=True, slots=True)
class CanonicalBar:
    """单根 canonical K 线：``bar_end`` 为 UTC 收盘时刻，``trading_day`` 为交易所交易日。

    构造时校验 OHLC 包络、非负成交量/持仓，并统一 ``bar_end`` 为 UTC。
    """

    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.bar_end, datetime) or self.bar_end.tzinfo is None or self.bar_end.utcoffset() is None:
            raise ContractError(field="bar_end", reason="timezone_required")
        if not isinstance(self.trading_day, date) or isinstance(self.trading_day, datetime):
            raise ContractError(field="trading_day", reason="date_required")
        values = {
            "open": _decimal(self.open, field="open"),
            "high": _decimal(self.high, field="high"),
            "low": _decimal(self.low, field="low"),
            "close": _decimal(self.close, field="close"),
            "volume": _decimal(self.volume, field="volume"),
            "turnover": _decimal(self.turnover, field="turnover", optional=True),
            "open_interest": _decimal(self.open_interest, field="open_interest", optional=True),
        }
        low = values["low"]
        high = values["high"]
        open_value = values["open"]
        close_value = values["close"]
        assert isinstance(low, Decimal) and isinstance(high, Decimal)
        assert isinstance(open_value, Decimal) and isinstance(close_value, Decimal)
        # low/high 须包住 open/close，防止脏数据静默进入 canonical
        if low > high or any(
            not low <= value <= high for value in (open_value, close_value)
        ):
            raise ContractError(field="ohlc", reason="price_envelope_invalid")
        for field in ("volume", "turnover", "open_interest"):
            value = values[field]
            if value is not None and value < 0:
                raise ContractError(field=field, reason="nonnegative_required")
        object.__setattr__(self, "bar_end", self.bar_end.astimezone(UTC))
        for field, value in values.items():
            object.__setattr__(self, field, value)

    def as_record(self) -> dict[str, object]:
        """转为与 Parquet schema 列名一致的字典，供 ``pyarrow`` 写盘。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TargetWindow:
    """维护/回填任务的目标数据集与时间窗口（已规范为 UTC 且 start < end）。"""

    dataset: DatasetKey
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start, end = _window(self.start, self.end)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class ResolvedContractSegment:
    """``actual_dominant`` 查询解析出的连续主力合约段（按交易日 contiguous 合并）。"""

    contract: str
    start_trading_day: date
    end_trading_day: date


@dataclass(frozen=True, slots=True)
class MarketSeriesResult:
    """``MarketDataService.query`` 的只读结果包。

    ``request_identity`` 记录请求指纹便于审计；``coverage`` 为实际返回 bar 的起止 ``bar_end``；
    ``resolved_contract_segments`` 仅在 ``actual_dominant`` 路径填充。
    """

    request_identity: Mapping[str, object]
    bars: tuple[CanonicalBar, ...]
    coverage: tuple[datetime, datetime] | None
    resolved_contract_segments: tuple[ResolvedContractSegment, ...]
    requested_trading_day_window: tuple[date, date] | None = None


@dataclass(frozen=True, slots=True)
class MarketSeriesPageResult:
    """``MarketDataService.query_page`` 的只读分页结果。"""

    request_identity: Mapping[str, object]
    bars: tuple[CanonicalBar, ...]
    canonical_coverage: tuple[datetime, datetime] | None
    has_more_before: bool
    next_before: datetime | None
    resolved_contract_segments: tuple[ResolvedContractSegment, ...]
