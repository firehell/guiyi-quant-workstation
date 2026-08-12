"""Database-backed expected coverage and TradingSession facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    INTRADAY_FREQUENCIES,
    RQDATA_INTRADAY_HISTORY_START,
    BarFrequency,
    CanonicalBar,
    DatasetKey,
)
from app.market_data.errors import InfrastructureError
from app.market_data.session_clock import (
    SHANGHAI,
    SessionClockError,
    session_windows_for_trading_day,
)
from app.models import (
    Contract,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)


class DatabaseCoverageSource:
    """基于交易所元数据构建确定性 expected bar_end；实现 CoverageSource 契约。"""

    def __init__(
        self,
        session: Session,
        product_starts_path: Path,
        *,
        history_floor_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.starts = _load_product_starts(product_starts_path)
        floor_path = (
            history_floor_path
            if history_floor_path is not None
            else PROJECT_ROOT / "data/universe/active_history_floor.txt"
        )
        self.history_floor = _load_history_floor(floor_path)
        self._now = now or (lambda: datetime.now(SHANGHAI))

    def product_start(self, symbol: str) -> date:
        """品种有效维护起点：provider 窗口起点与 active history floor 的较大值。"""
        try:
            provider_start = self.starts[symbol.strip().lower()]
        except KeyError as exc:
            raise InfrastructureError("PRODUCT_WINDOW_START_MISSING") from exc
        return max(provider_start, self.history_floor)

    def provider_start(self, symbol: str) -> date:
        """返回 RQData/挂牌长周期起点，不套用 active history floor。"""
        try:
            return self.starts[symbol.strip().lower()]
        except KeyError as exc:
            raise InfrastructureError("PRODUCT_WINDOW_START_MISSING") from exc

    def dataset_start(self, key: DatasetKey) -> date:
        """单数据集起点：日内频度受 RQDATA_INTRADAY_HISTORY_START 约束。"""
        start = self.product_start(key.symbol)
        if key.frequency in INTRADAY_FREQUENCIES:
            return max(start, RQDATA_INTRADAY_HISTORY_START)
        return start

    def latest_complete_day(self, products: tuple[str, ...]) -> date:
        """各品种最近「交易日已收盘」的日期，取多品种最小值作为统一 through 上界。"""
        values: list[date] = []
        current = self._now().astimezone(SHANGHAI)
        today = current.date()
        for symbol in products:
            exchange = self._exchange(symbol)
            value = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                    TradingCalendar.trade_date <= today,
                )
            )
            if value is None:
                raise InfrastructureError("TRADING_CALENDAR_MISSING")
            # 若最大交易日是今天但会话尚未结束，回退到上一交易日，避免拉未完成日 bar。
            if value == today:
                try:
                    session_end = max(
                        window.end for window in self._sessions_for_day(symbol, value)
                    )
                except InfrastructureError as exc:
                    if exc.code != "TRADING_SESSION_MISSING":
                        raise
                    # 当天日历先于会话 metadata 到达时，只读路径退到已知历史日；
                    # 历史窗口仍由 require_historical_session_facts 严格验证。
                    value = self._previous_trading_day(exchange, today)
                else:
                    if current < session_end:
                        value = self._previous_trading_day(exchange, today)
            values.append(value)
        return min(values)

    def latest_metadata_day(self, products: tuple[str, ...]) -> date:
        """metadata bootstrap 可安全同步到的最近已知交易日，不依赖 SessionClock。"""
        current_day = self._now().astimezone(SHANGHAI).date()
        values: list[date] = []
        for symbol in products:
            exchange = self._exchange(symbol)
            value = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                    TradingCalendar.trade_date <= current_day,
                )
            )
            if value is None:
                raise InfrastructureError("TRADING_CALENDAR_MISSING")
            values.append(value)
        return min(values)

    def metadata_complete(self, products: tuple[str, ...], through: date) -> bool:
        """快速判断日历/会话/主力映射是否已覆盖 through；不齐时返回 False 触发 synchronize。"""
        for symbol in products:
            try:
                exchange = self._exchange(symbol)
            except InfrastructureError as exc:
                if exc.code == "INSTRUMENT_EXCHANGE_MISSING":
                    return False
                raise
            calendar_end = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                )
            )
            if calendar_end is None or calendar_end < through:
                return False
            if (
                self.session.scalar(
                    select(TradingSession.id)
                    .where(
                        TradingSession.exchange_code == exchange,
                        TradingSession.instrument_symbol == symbol,
                        TradingSession.is_active.is_(True),
                        TradingSession.effective_from <= through,
                        (
                            TradingSession.effective_to.is_(None)
                            | (TradingSession.effective_to >= through)
                        ),
                    )
                    .limit(1)
                )
                is None
            ):
                return False
            last_trading_day = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date <= through,
                    TradingCalendar.is_trading_day.is_(True),
                )
            )
            if last_trading_day is None:
                return False
            first_map_day = self.session.scalar(
                select(func.min(MainContractMap.trade_date)).where(
                    MainContractMap.symbol == symbol,
                    MainContractMap.trade_date >= self.product_start(symbol),
                    MainContractMap.trade_date <= through,
                )
            )
            if first_map_day is None:
                return False
            expected_days = self._trading_days(symbol, first_map_day, through)
            mapped_days = tuple(
                self.session.scalars(
                    select(MainContractMap.trade_date)
                    .where(
                        MainContractMap.symbol == symbol,
                        MainContractMap.trade_date >= first_map_day,
                        MainContractMap.trade_date <= through,
                    )
                    .order_by(MainContractMap.trade_date)
                )
            )
            # 主力映射须与有效交易日一一对应，缺口会导致 contract 序列 expected 错误。
            if mapped_days != expected_days:
                return False
            session_days = set(
                self.session.scalars(
                    select(TradingSession.effective_from)
                    .where(
                        TradingSession.exchange_code == exchange,
                        TradingSession.instrument_symbol == symbol,
                        TradingSession.provider == "rqdata",
                        TradingSession.is_active.is_(True),
                        TradingSession.effective_from >= first_map_day,
                        TradingSession.effective_from <= through,
                        TradingSession.effective_to == TradingSession.effective_from,
                    )
                    .distinct()
                )
            )
            if session_days != set(expected_days):
                return False
        return True

    def require_historical_session_facts(
        self, products: tuple[str, ...], through: date
    ) -> None:
        """要求历史维护窗口内每个交易日均有 provider 会话事实（fail-closed）。

        日历上下文从有效窗口前一月起算，供首周/夜盘计算；会话按日快照，
        禁止用当前 contract.trading_hours 回填历史日。
        """
        samples: list[Mapping[str, str]] = []
        for symbol in tuple(dict.fromkeys(item.strip().lower() for item in products)):
            exchange = self._exchange(symbol)
            context_start = _calendar_context_start(self.product_start(symbol))
            calendar_through = _iso_week_end(through)
            expected_calendar_days = (calendar_through - context_start).days + 1
            observed_calendar_days = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(TradingCalendar)
                    .where(
                        TradingCalendar.exchange_code == exchange,
                        TradingCalendar.trade_date >= context_start,
                        TradingCalendar.trade_date <= calendar_through,
                        TradingCalendar.provider == "rqdata",
                    )
                )
                or 0
            )
            missing = observed_calendar_days != expected_calendar_days
            if not missing:
                for trading_day in self._trading_days(
                    symbol, self.product_start(symbol), through
                ):
                    fact = self.session.scalar(
                        select(TradingSession.id)
                        .where(
                            TradingSession.exchange_code == exchange,
                            TradingSession.instrument_symbol == symbol,
                            TradingSession.provider == "rqdata",
                            TradingSession.is_active.is_(True),
                            TradingSession.effective_from == trading_day,
                            TradingSession.effective_to == trading_day,
                        )
                        .limit(1)
                    )
                    if fact is None:
                        missing = True
                        break
            if missing and len(samples) < 20:
                samples.append(_session_coverage_sample(symbol, context_start, through))
        if samples:
            raise InfrastructureError(
                "HISTORICAL_SESSION_FACT_MISSING", samples=tuple(samples)
            )

    def expected_bar_ends(
        self,
        key: DatasetKey,
        year: int,
        month: int,
        start: date,
        end: date,
    ) -> tuple[datetime, ...]:
        """给定自然月与品种窗口，返回该月内应有 bar_end（UTC）序列。"""
        lower = max(start, date(year, month, 1), self.dataset_start(key))
        upper = min(end, _month_end(year, month))
        if lower > upper:
            return ()
        days = self._trading_days(key.symbol, lower, upper)
        return self.expected_bar_ends_for_trading_days(key, days)

    def expected_bar_ends_for_trading_days(
        self,
        key: DatasetKey,
        trading_days: tuple[date, ...],
    ) -> tuple[datetime, ...]:
        """按频度与会话模板，将交易日列表展开为 bar_end 时间戳序列。"""
        days = tuple(sorted(dict.fromkeys(trading_days)))
        if not days:
            return ()
        sessions_by_day = {day: self._sessions_for_day(key.symbol, day) for day in days}
        if key.frequency is BarFrequency.M1:
            return tuple(
                window.start + timedelta(minutes=minute)
                for day in days
                for window in sessions_by_day[day]
                for minute in range(1, _minutes(window) + 1)
            )
        if key.frequency in {
            BarFrequency.M5,
            BarFrequency.M15,
            BarFrequency.M30,
            BarFrequency.H1,
        }:
            width = {
                BarFrequency.M5: 5,
                BarFrequency.M15: 15,
                BarFrequency.M30: 30,
                BarFrequency.H1: 60,
            }[key.frequency]
            result: list[datetime] = []
            for day in days:
                for window in sessions_by_day[day]:
                    count = _minutes(window)
                    result.extend(
                        window.start + timedelta(minutes=min(offset, count))
                        for offset in range(width, count + width, width)
                    )
            return tuple(dict.fromkeys(result))
        daily = tuple(sessions_by_day[day][-1].end for day in days)
        if key.frequency is BarFrequency.D1:
            return daily
        # W1：仅当 ISO 周内最后一个交易日落在该周时才产生周线 bar_end。
        result = []
        grouped: dict[tuple[int, int], list[tuple[date, datetime]]] = {}
        for day, bar_end in zip(days, daily, strict=True):
            iso = day.isocalendar()
            grouped.setdefault((iso.year, iso.week), []).append((day, bar_end))
        for values in grouped.values():
            candidate_day, bar_end = values[-1]
            monday = candidate_day - timedelta(days=candidate_day.isoweekday() - 1)
            sunday = monday + timedelta(days=6)
            full_week = self._trading_days(key.symbol, monday, sunday)
            if full_week and full_week[-1] == candidate_day:
                result.append(bar_end)
        return tuple(result)

    def sessions(
        self,
        key: DatasetKey,
        year: int,
        month: int,
        through: date | None = None,
    ) -> tuple[SessionWindow, ...]:
        """返回月内 SessionWindow 列表，供 derived 聚合对齐会话边界。"""
        lower = max(date(year, month, 1), self.dataset_start(key))
        upper = _month_end(year, month)
        if through is not None:
            upper = min(upper, through)
        return tuple(
            window
            for day in self._trading_days(key.symbol, lower, upper)
            for window in self._sessions_for_day(key.symbol, day)
        )

    def valid_boundary(self, key: DatasetKey, bar: CanonicalBar) -> bool:
        """单 bar 是否落在 coverage 期望边界内（store 发布时的 boundary_validator）。"""
        expected = self.expected_bar_ends(
            key,
            bar.trading_day.year,
            bar.trading_day.month,
            bar.trading_day,
            bar.trading_day,
        )
        return bar.bar_end in expected

    def _exchange(self, symbol: str) -> str:
        """品种所属交易所代码；缺失时 fail-closed。"""
        value = self.session.scalar(
            select(Instrument.exchange_code).where(
                Instrument.symbol == symbol.strip().lower(),
                Instrument.is_active.is_(True),
            )
        )
        if value is None:
            raise InfrastructureError("INSTRUMENT_EXCHANGE_MISSING")
        return value

    def _previous_trading_day(self, exchange: str, today: date) -> date:
        value = self.session.scalar(
            select(func.max(TradingCalendar.trade_date)).where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.is_trading_day.is_(True),
                TradingCalendar.trade_date < today,
            )
        )
        if value is None:
            raise InfrastructureError("COMPLETE_TRADING_DAY_MISSING")
        return value

    def _trading_days(self, symbol: str, start: date, end: date) -> tuple[date, ...]:
        """品种在 [start,end] 内有效交易日（日历 ∩ 有挂牌未到期合约）。"""
        normalized = symbol.strip().lower()
        exchange = self._exchange(symbol)
        return _product_trading_days(self.session, normalized, exchange, start, end)

    def _sessions_for_day(
        self, symbol: str, trading_day: date
    ) -> tuple[SessionWindow, ...]:
        """将 DB 会话模板转为当日实际 SessionWindow（处理夜盘与跨日）。"""
        exchange = self._exchange(symbol)
        try:
            return session_windows_for_trading_day(
                self.session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_day,
            )
        except SessionClockError as exc:
            raise InfrastructureError(exc.code) from exc


def _product_trading_days(
    session: Session,
    symbol: str,
    exchange: str,
    start: date,
    end: date,
) -> tuple[date, ...]:
    """日历交易日 ∩ 当日存在挂牌且未到期合约的日期序列。"""
    return tuple(
        session.scalars(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date >= start,
                TradingCalendar.trade_date <= end,
                TradingCalendar.is_trading_day.is_(True),
                exists().where(
                    Contract.instrument_symbol == symbol.strip().lower(),
                    Contract.listed_date.is_not(None),
                    Contract.listed_date <= TradingCalendar.trade_date,
                    Contract.expired_date.is_not(None),
                    Contract.expired_date > TradingCalendar.trade_date,
                ),
            )
            .order_by(TradingCalendar.trade_date)
        )
    )


def _load_product_starts(path: Path) -> dict[str, date]:
    """加载品种窗口起点 CSV；拒绝 symlink 与空表（防误读外部路径）。"""
    if not path.is_file() or path.is_symlink():
        raise InfrastructureError("PRODUCT_WINDOW_STARTS_INVALID")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        result = {
            str(row["product"]).strip().lower(): date.fromisoformat(row["window_start"])
            for row in rows
        }
    if not result:
        raise InfrastructureError("PRODUCT_WINDOW_STARTS_INVALID")
    return result


def _load_history_floor(path: Path) -> date:
    """加载 active history floor 单行日期，界定全品种维护下界。"""
    if not path.is_file() or path.is_symlink():
        raise InfrastructureError("ACTIVE_HISTORY_FLOOR_INVALID")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) != 1:
        raise InfrastructureError("ACTIVE_HISTORY_FLOOR_INVALID")
    try:
        return date.fromisoformat(lines[0])
    except ValueError as exc:
        raise InfrastructureError("ACTIVE_HISTORY_FLOOR_INVALID") from exc


def _calendar_context_start(effective_start: date) -> date:
    """日历上下文起点：有效月起始日再向前一个自然月。"""
    month_start = date(effective_start.year, effective_start.month, 1)
    if month_start.month == 1:
        return date(month_start.year - 1, 12, 1)
    return date(month_start.year, month_start.month - 1, 1)


def _iso_week_end(day: date) -> date:
    """给定日期所在 ISO 周的周日（含）。"""
    return day + timedelta(days=7 - day.isoweekday())


def _month_end(year: int, month: int) -> date:
    """自然月最后一天。"""
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _minutes(window: SessionWindow) -> int:
    """会话窗口内的分钟数（用于 1m/多分钟频度展开）。"""
    return int((window.end - window.start).total_seconds() // 60)


def _session_coverage_sample(symbol: str, start: date, end: date) -> Mapping[str, str]:
    """会话覆盖失败时的审计样本（限制条数避免错误体过大）。"""
    return {
        "kind": "continuous",
        "symbol": symbol.upper(),
        "series_or_contract": "MAIN",
        "frequency": "1d",
        "start": f"{start.isoformat()}T00:00:00Z",
        "end": f"{end.isoformat()}T23:59:59Z",
        "reason_code": "HISTORICAL_SESSION_FACT_MISSING",
    }
