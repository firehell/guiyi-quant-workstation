"""由 1m canonical 聚合派生频率（数据核心 V2 派生层）。

维护管道在 direct ``1m`` 落盘后，用本模块生成 ``5m/15m/30m/60m`` 分区。
聚合规则：
- 仅在给定的 ``SessionWindow`` 内操作，session 外 1m 视为非法；
- 每个 session 内 1m 必须分钟连续且与 session 长度一致，否则 fail-closed；
- 桶边界按 session 起点对齐的固定宽度向上取整（``ceil``），持仓取桶内最后一根。

本模块不参与查询路径，仅供 historical 维护/回填使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil

from app.market_data.domain import BarFrequency, CanonicalBar, DERIVED_FREQUENCIES


class AggregationError(RuntimeError):
    """聚合失败：session/源 1m 不完整、频率非法或桶外残留 bar。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """单个交易 session 的半开时间窗 ``(start, end]``，须为 UTC 且分钟对齐。"""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if (
            self.start.tzinfo is None
            or self.start.utcoffset() is None
            or self.end.tzinfo is None
            or self.end.utcoffset() is None
        ):
            raise AggregationError("SESSION_TIMEZONE_REQUIRED")
        start = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        if start >= end:
            raise AggregationError("SESSION_WINDOW_INVALID")
        # 分钟边界对齐，避免亚分钟 session 导致桶划分歧义
        if (end - start).total_seconds() % 60:
            raise AggregationError("SESSION_MINUTE_BOUNDARY_REQUIRED")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


_MINUTES = {
    BarFrequency.M5: 5,
    BarFrequency.M15: 15,
    BarFrequency.M30: 30,
    BarFrequency.H1: 60,
}


def aggregate_from_1m(
    bars: tuple[CanonicalBar, ...],
    *,
    target_frequency: BarFrequency | str,
    sessions: tuple[SessionWindow, ...],
) -> tuple[CanonicalBar, ...]:
    """将严格完整的 1m 序列聚合为目标派生频率。

    参数:
        bars: 已按 ``bar_end`` 升序的 1m canonical bar。
        target_frequency: 须为 ``DERIVED_FREQUENCIES`` 之一。
        sessions: 不重叠、升序的 session 列表；源 1m 必须恰好覆盖这些 session。

    失败模式: 源不完整、session 重叠、或存在 session 外 1m 时抛出 ``AggregationError``。
    """
    try:
        frequency = BarFrequency(target_frequency)
    except ValueError as exc:
        raise AggregationError("TARGET_FREQUENCY_INVALID") from exc
    if frequency not in DERIVED_FREQUENCIES:
        raise AggregationError("TARGET_FREQUENCY_NOT_DERIVED")
    _validate_sessions(sessions)
    source = tuple(bars)
    if any(
        previous.bar_end >= current.bar_end
        for previous, current in zip(source, source[1:])
    ):
        raise AggregationError("SOURCE_1M_NOT_ORDERED")

    assigned: set[datetime] = set()
    output: list[CanonicalBar] = []
    width = _MINUTES[frequency]
    for session in sessions:
        session_bars = tuple(bar for bar in source if session.start < bar.bar_end <= session.end)
        expected_count = int((session.end - session.start).total_seconds() // 60)
        expected_ends = tuple(
            session.start + timedelta(minutes=minute)
            for minute in range(1, expected_count + 1)
        )
        # session 内每一分钟都必须有一根 1m，缺一分钟则整次聚合失败
        if tuple(bar.bar_end for bar in session_bars) != expected_ends:
            raise AggregationError("SOURCE_1M_INCOMPLETE")
        assigned.update(expected_ends)
        buckets: dict[datetime, list[CanonicalBar]] = {}
        for bar in session_bars:
            elapsed = int((bar.bar_end - session.start).total_seconds() // 60)
            # 按 session 内经过分钟数分桶，末桶不超过 session 末分钟
            bucket_minutes = min(ceil(elapsed / width) * width, expected_count)
            bucket_end = session.start + timedelta(minutes=bucket_minutes)
            buckets.setdefault(bucket_end, []).append(bar)
        for bucket_end in sorted(buckets):
            output.append(_aggregate_bucket(tuple(buckets[bucket_end]), bucket_end=bucket_end))
    # 所有源 1m 必须落在某个 session 内，禁止跨夜或未声明时段的 bar
    if {bar.bar_end for bar in source} != assigned:
        raise AggregationError("SOURCE_1M_OUTSIDE_SESSION")
    return tuple(output)


def _validate_sessions(sessions: tuple[SessionWindow, ...]) -> None:
    """要求至少一个 session，且相邻 session 不重叠、按时间升序。"""
    if not sessions:
        raise AggregationError("SESSIONS_REQUIRED")
    for previous, current in zip(sessions, sessions[1:]):
        if previous.end > current.start:
            raise AggregationError("SESSIONS_OVERLAP_OR_UNORDERED")


def _aggregate_bucket(
    bars: tuple[CanonicalBar, ...],
    *,
    bucket_end: datetime,
) -> CanonicalBar:
    """单桶 OHLCV 聚合：open=首根、close/OI=末根、高低极值、量额求和。"""
    first = bars[0]
    last = bars[-1]
    turnovers = tuple(bar.turnover for bar in bars)
    return CanonicalBar(
        bar_end=bucket_end,
        trading_day=last.trading_day,
        open=first.open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=last.close,
        volume=sum((bar.volume for bar in bars), start=Decimal(0)),
        turnover=(
            None
            if all(value is None for value in turnovers)
            else sum((value or Decimal(0) for value in turnovers), start=Decimal(0))
        ),
        open_interest=last.open_interest,
    )
