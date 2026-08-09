"""维护基础设施：Coverage 期望源与 RQData 适配器。

本模块为 maintenance.HistoricalDataManager 提供两类可替换实现，不包含维护编排逻辑本身。

DatabaseCoverageSource（CoverageSource）
    从 DB 日历、会话模板、品种窗口与 active history floor 推导确定性 expected_bar_ends。
    不读 Parquet、不调用 RQData；缺口与元数据不齐在此层显式失败或返回 False，禁止静默填充。

RQDataMarketAdapter（BarSource + MetadataPort）
    唯一固定的 RQData 边界：拉 bars、拉 metadata snapshot（合约/日历/会话/主力映射）。
    配额与凭证错误在此归一化为 InfrastructureError，由 manager 决定 partial 或中止。
    client 懒初始化，dry-run 路径不触发 rqdatac.init。

边界原则
    - 历史会话事实必须按交易日来自 provider，不可用当前 contract.trading_hours 回填旧日。
    - 日历上下文向前扩一月、向后扩一周，用于夜盘/首周 ISO 周完整性证明，非第二套 watermark。
    - 品种有效交易日 = 日历交易日 ∩ 当日有未到期挂牌合约，避免拉取无合约日行情。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import csv
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT, load_project_env
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    INTRADAY_FREQUENCIES,
    RQDATA_INTRADAY_HISTORY_START,
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
)
from app.market_data.maintenance import BarBatch
from app.market_data.metadata import MetadataSnapshot
from app.market_data.session_clock import (
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


SHANGHAI = ZoneInfo("Asia/Shanghai")
_SESSION = re.compile(r"(?P<start>\d{1,2}:\d{2})\s*[-~]\s*(?P<end>\d{1,2}:\d{2})")


class InfrastructureError(RuntimeError):
    """基础设施层可识别错误；code 供 maintenance 区分 fail-closed 与可隔离失败。"""

    def __init__(
        self, code: str, *, samples: tuple[Mapping[str, str], ...] = ()
    ) -> None:
        self.code = code
        self.samples = samples
        super().__init__(code)


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
                session_end = max(
                    window.end for window in self._sessions_for_day(symbol, value)
                )
                if current < session_end:
                    value = self.session.scalar(
                        select(func.max(TradingCalendar.trade_date)).where(
                            TradingCalendar.exchange_code == exchange,
                            TradingCalendar.is_trading_day.is_(True),
                            TradingCalendar.trade_date < today,
                        )
                    )
                    if value is None:
                        raise InfrastructureError("COMPLETE_TRADING_DAY_MISSING")
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


class RQDataMarketAdapter:
    """固定 RQData 适配器：bars 拉取与 metadata snapshot（实现 BarSource / MetadataPort）。"""

    def __init__(self, *, session: Session, client: Any | None = None) -> None:
        self.session = session
        self._client = client

    @property
    def client(self) -> Any:
        """仅在 apply 路径首次需要行情时初始化 rqdatac，dry-run 不触网。"""
        if self._client is None:
            self._client = RQDataClient()
        return self._client

    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch:
        """按 expected bar_end 拉取并归一化为 CanonicalBar；配额错误转为 PROVIDER_QUOTA_EXHAUSTED。"""
        if not expected:
            raise InfrastructureError("PROVIDER_WINDOW_EMPTY")
        if key.frequency is BarFrequency.W1:
            # 周线需扩到完整 ISO 周自然日范围，否则 provider 返回行与 expected 无法对齐。
            iso_days = tuple(value.astimezone(SHANGHAI).date() for value in expected)
            start_day = min(
                item - timedelta(days=item.isoweekday() - 1) for item in iso_days
            )
            end_day = max(
                item + timedelta(days=7 - item.isoweekday()) for item in iso_days
            )
        else:
            start_day = min(expected).date()
            end_day = max(expected).date()
        order_book_ids: tuple[str, ...]
        if key.kind is DatasetKind.CONTINUOUS:
            order_book_ids = (f"{key.symbol.upper()}88",)
        else:
            order_book_ids = (key.series_or_contract,)
        rows: tuple[dict[str, Any], ...] = ()
        for order_book_id in order_book_ids:
            try:
                frame = self.client.price(
                    order_book_id,
                    start_day,
                    end_day,
                    key.frequency.value,
                )
            except Exception as exc:  # noqa: BLE001 - normalize provider boundary
                if _is_rqdata_quota_error(exc):
                    raise InfrastructureError("PROVIDER_QUOTA_EXHAUSTED") from exc
                raise
            rows = _records(frame)
            if rows:
                break
        expected_by_day: dict[date, list[datetime]] = {}
        expected_by_iso_week: dict[tuple[int, int], datetime] = {}
        for value in expected:
            expected_by_day.setdefault(value.astimezone(SHANGHAI).date(), []).append(
                value
            )
            if key.frequency is BarFrequency.W1:
                iso = value.astimezone(SHANGHAI).date().isocalendar()
                expected_by_iso_week[(iso.year, iso.week)] = value
        bars: list[CanonicalBar] = []
        for row in rows:
            trading_day = _row_date(row)
            if key.frequency is BarFrequency.W1:
                iso = trading_day.isocalendar()
                bar_end = expected_by_iso_week.get((iso.year, iso.week))
                if bar_end is None:
                    continue
            elif key.frequency is BarFrequency.D1:
                candidates = expected_by_day.get(trading_day)
                if not candidates:
                    continue
                bar_end = candidates[-1]
            else:
                bar_end = _row_datetime(row)
                # 只接纳落在 expected 内的 bar，避免 provider 多返导致发布校验失败。
                if bar_end not in expected:
                    continue
            bars.append(_canonical_bar(row, bar_end, trading_day))
        bars.sort(key=lambda item: item.bar_end)
        return BarBatch(tuple(bars))

    def fetch_metadata(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot:
        """规划 metadata 拉取起点：兼顾映射缺口与近端刷新窗口，再调 RQData snapshot。"""
        requested_starts: dict[str, date] = {}
        for symbol in products:
            floor = starts[symbol]
            current = self.session.scalar(
                select(func.max(MainContractMap.trade_date)).where(
                    MainContractMap.symbol == symbol
                )
            )
            # 默认从最近映射日前 14 天刷新，映射缺口则前推到首个缺失日。
            refresh_start = (
                max(floor, current - timedelta(days=14)) if current else floor
            )
            exchange = self.session.scalar(
                select(Instrument.exchange_code).where(Instrument.symbol == symbol)
            )
            if exchange is not None:
                first_map_day = self.session.scalar(
                    select(func.min(MainContractMap.trade_date)).where(
                        MainContractMap.symbol == symbol,
                        MainContractMap.trade_date >= floor,
                        MainContractMap.trade_date <= through,
                    )
                )
                map_floor = first_map_day or floor
                calendar_days = _product_trading_days(
                    self.session,
                    symbol,
                    exchange,
                    map_floor,
                    through,
                )
                mapped_days = set(
                    self.session.scalars(
                        select(MainContractMap.trade_date).where(
                            MainContractMap.symbol == symbol,
                            MainContractMap.trade_date >= map_floor,
                            MainContractMap.trade_date <= through,
                        )
                    )
                )
                missing_map = next(
                    (day for day in calendar_days if day not in mapped_days), None
                )
                if missing_map is not None:
                    refresh_start = min(refresh_start, missing_map)
            requested_starts[symbol] = refresh_start
        return self.client.metadata_snapshot(products, through, requested_starts)


class RQDataClient:
    """rqdatac 薄封装：凭证初始化与 price / metadata 高层调用。"""

    def __init__(self) -> None:
        load_project_env()
        try:
            import rqdatac  # type: ignore[import-not-found, import-untyped]
        except ImportError as exc:
            raise InfrastructureError("RQDATA_NOT_INSTALLED") from exc
        uri = os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF")
        license_key = os.getenv("RQDATA_LICENSE_KEY")
        username = os.getenv("RQDATA_USERNAME")
        password = os.getenv("RQDATA_PASSWORD")
        if uri:
            rqdatac.init(uri=uri)
        elif license_key:
            rqdatac.init("license", license_key)
        elif username and password:
            rqdatac.init(
                username,
                password,
                os.getenv("RQDATA_ADDR", "rqdatad-pro.ricequant.com:16011"),
            )
        else:
            raise InfrastructureError("RQDATA_CREDENTIALS_MISSING")
        self.api = rqdatac

    def price(self, order_book_id: str, start: date, end: date, frequency: str):
        """调用 get_price；adjust_type=none 保持与 canonical 未复权语义一致。"""
        return self.api.get_price(
            order_book_id,
            start_date=start,
            end_date=end,
            frequency=frequency,
            adjust_type="none",
        )

    def is_future_data_ready(self, trading_day: date) -> bool:
        """确认日线与分钟线均已由 RQData 标记为可用。"""
        frame = self.api.is_data_ready(
            categories=["future_daybar", "future_minbar"],
            expected_date=trading_day,
            market="cn",
        )
        required = frame.loc[["future_daybar", "future_minbar"], "ready"]
        return bool(required.all())

    def dominant_for_day(self, symbol: str, trading_day: date) -> str:
        """返回指定交易日唯一的 rank=1 主力合约；异常结果显式拒绝。"""
        frame = _frame(
            self.api.futures.get_dominant(
                symbol.upper(),
                start_date=trading_day,
                end_date=trading_day,
                rule=2,
                rank=1,
            )
        )
        values = tuple(
            _row_text(
                row,
                "dominant",
                "order_book_id",
                "contract",
                "dominant_contract",
                0,
                "0",
            ).strip().upper()
            for row in frame.to_dict("records")
        )
        normalized = tuple(value for value in values if value)
        if len(normalized) != 1:
            raise InfrastructureError("RQDATA_DOMINANT_INVALID")
        return normalized[0]

    def live_market_client(self) -> Any:
        """创建 RQData Live client；仅由显式的前台 live Runtime 使用。"""
        return self.api.LiveMarketDataClient()

    def metadata_snapshot(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot:
        """组装 MetadataSnapshot：合约、日历、按日会话、主力 rank1 映射。"""
        frame = _frame(self.api.all_instruments(type="Future"))
        product_set = {item.upper() for item in products}
        if "underlying_symbol" not in frame.columns:
            raise InfrastructureError("RQDATA_INSTRUMENT_SCHEMA_INVALID")
        frame = frame[
            frame["underlying_symbol"].astype(str).str.upper().isin(product_set)
        ]
        exchanges: dict[str, dict[str, object]] = {}
        instruments: dict[str, dict[str, object]] = {}
        contracts: list[dict[str, object]] = []
        for row in frame.to_dict("records"):
            symbol = str(row["underlying_symbol"]).lower()
            exchange = str(row.get("exchange", row.get("exchange_code", ""))).upper()
            contract = str(row.get("order_book_id", "")).upper()
            if not exchange or not contract:
                continue
            listed = _optional_date(row.get("listed_date"))
            exchanges[exchange] = {"code": exchange, "name": exchange}
            instruments[symbol] = {
                "symbol": symbol,
                "name": str(row.get("underlying_symbol", symbol)),
                "exchange_code": exchange,
                "is_active": True,
            }
            contracts.append(
                {
                    "contract_code": contract,
                    "instrument_symbol": symbol,
                    "exchange_code": exchange,
                    "name": str(row.get("symbol", contract)),
                    "contract_multiplier": _optional_int(
                        row.get("contract_multiplier")
                    ),
                    "listed_date": listed,
                    "expired_date": _optional_date(row.get("de_listed_date")),
                    "maturity_date": _optional_date(row.get("maturity_date")),
                    "trading_hours": _optional_text(row.get("trading_hours")),
                    "provider": "rqdata",
                }
            )
        # Fetch one week past the bar watermark so a holiday-short ISO week can
        # still be proven complete without storing a second calendar watermark.
        # Calendar may start one natural month before the earliest effective_start
        # for previous-day / night-session / first ISO-week context only.
        # 日历向后多取一周：短假周仍可证明 ISO 周完整，无需第二套 calendar watermark。
        earliest = min(starts.values())
        calendar_start = _calendar_context_start(earliest)
        calendar_end = through + timedelta(days=7)
        trading_dates = tuple(
            pd.Timestamp(item).date()
            for item in self.api.get_trading_dates(
                start_date=calendar_start,
                end_date=calendar_end,
            )
        )
        main_contracts: list[tuple[str, date, str]] = []
        for symbol in products:
            values = _frame(
                self.api.futures.get_dominant(
                    symbol.upper(),
                    start_date=starts[symbol],
                    end_date=through,
                    rule=2,
                    rank=1,
                )
            )
            for row in values.to_dict("records"):
                day = _row_date(row)
                contract = _row_text(
                    row,
                    "dominant",
                    "order_book_id",
                    "contract",
                    "dominant_contract",
                    0,
                    "0",
                )
                main_contracts.append((symbol, day, contract.upper()))
        symbol_exchanges = {
            symbol: str(values["exchange_code"])
            for symbol, values in instruments.items()
        }
        # 按主力合约集合拉取按日 trading_periods，用于构建历史会话事实（非当前 trading_hours）。
        periods = _records(
            self.api.get_trading_periods(
                tuple(sorted({contract for _, _, contract in main_contracts})),
                start_date=calendar_start,
                end_date=through,
                frequency="1m",
            )
        )
        sessions = _historical_session_rows(
            periods,
            main_contracts,
            symbol_exchanges,
        )
        # 有夜盘或跨日的交易所，日历行标记 has_night_session。
        night_exchanges = {
            str(row["exchange_code"])
            for row in sessions
            if (isinstance(row["start_time"], time) and row["start_time"] >= time(18))
            or bool(row["crosses_midnight"])
        }
        trading_day_set = set(trading_dates)
        calendars = tuple(
            {
                "exchange_code": exchange,
                "trade_date": day,
                "is_trading_day": day in trading_day_set,
                "has_night_session": exchange in night_exchanges
                and day in trading_day_set,
                "provider": "rqdata",
            }
            for exchange in exchanges
            for day in _days(calendar_start, calendar_end)
        )
        return MetadataSnapshot(
            exchanges=tuple(exchanges.values()),
            instruments=tuple(instruments.values()),
            contracts=tuple(contracts),
            calendars=calendars,
            sessions=sessions,
            main_contracts=tuple(main_contracts),
            main_contract_starts=dict(starts),
        )


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


def _records(value: Any) -> tuple[dict[str, Any], ...]:
    """将 RQData 返回统一为 record 元组。"""
    return tuple(_frame(value).to_dict("records"))


def _frame(value: Any) -> pd.DataFrame:
    """将 Series/DataFrame/其他结构规范为带 RangeIndex 的 DataFrame。"""
    if isinstance(value, pd.DataFrame):
        result = value.copy()
        if not isinstance(result.index, pd.RangeIndex):
            result = result.reset_index()
        return result
    if isinstance(value, pd.Series):
        return value.reset_index()
    return pd.DataFrame(value)


def _row_date(row: dict[str, Any]) -> date:
    """从 provider 行解析 trading_day。"""
    value = _row_value(row, "trading_date", "trade_date", "date", "index")
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise InfrastructureError("RQDATA_TRADING_DAY_INVALID")
    return parsed.date()


def _row_datetime(row: dict[str, Any]) -> datetime:
    """从 provider 行解析 bar_end，统一转为 UTC。"""
    parsed = pd.Timestamp(_row_value(row, "datetime", "index"))
    if pd.isna(parsed):
        raise InfrastructureError("RQDATA_BAR_END_INVALID")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(SHANGHAI)
    return parsed.tz_convert(UTC).to_pydatetime()


def _canonical_bar(
    row: dict[str, Any], bar_end: datetime, trading_day: date
) -> CanonicalBar:
    """将 provider OHLCV 行映射为 CanonicalBar（Decimal 字段）。"""
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=_decimal(row, "open"),
        high=_decimal(row, "high"),
        low=_decimal(row, "low"),
        close=_decimal(row, "close"),
        volume=_decimal(row, "volume"),
        turnover=_optional_decimal(
            _row_value(row, "turnover", "total_turnover", "amount", required=False)
        ),
        open_interest=_optional_decimal(
            _row_value(row, "open_interest", "open_oi", "close_oi", required=False)
        ),
    )


def _decimal(row: dict[str, Any], field: str) -> Decimal:
    """必填 Decimal 字段；缺失时 fail-closed。"""
    value = _optional_decimal(_row_value(row, field))
    if value is None:
        raise InfrastructureError("RQDATA_DECIMAL_MISSING")
    return value


def _optional_decimal(value: Any) -> Decimal | None:
    """可空 Decimal 解析；非法值抛出 RQDATA_DECIMAL_INVALID。"""
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InfrastructureError("RQDATA_DECIMAL_INVALID") from exc


def _row_value(row: dict[str, Any], *fields: Any, required: bool = True) -> Any:
    """按候选字段名取首个非空值；required 时缺失抛 RQDATA_FIELD_MISSING。"""
    for field in fields:
        if field in row and row[field] is not None:
            return row[field]
    if required:
        raise InfrastructureError("RQDATA_FIELD_MISSING")
    return None


def _row_text(row: dict[str, Any], *fields: Any) -> str:
    """解析非空字符串字段。"""
    value = _row_value(row, *fields)
    if not isinstance(value, str) or not value.strip():
        raise InfrastructureError("RQDATA_TEXT_INVALID")
    return value.strip()


def _optional_date(value: Any) -> date | None:
    """可空日期；RQData 占位 0000 日期视为 None。"""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str) and value.strip().startswith("0000"):
        return None
    return pd.Timestamp(value).date()


def _optional_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _optional_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    result = str(value).strip()
    return result or None


def _historical_session_rows(
    periods: tuple[dict[str, Any], ...],
    main_contracts: list[tuple[str, date, str]],
    symbol_exchanges: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    """将 get_trading_periods 结果转为按日 TradingSession 行；须与主力映射日全集一致。"""
    expected = {(contract, day): symbol for symbol, day, contract in main_contracts}
    values: dict[tuple[str, date], str] = {}
    for row in periods:
        contract = _row_text(row, "order_book_id", "level_0").upper()
        trading_day = _row_date(row)
        key = (contract, trading_day)
        if key not in expected:
            continue
        hours = _optional_text(row.get("trading_hours"))
        if hours is None or key in values:
            raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
        values[key] = hours
    if set(values) != set(expected):
        raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
    rows: list[dict[str, object]] = []
    for contract, trading_day in sorted(values, key=lambda item: (item[1], item[0])):
        symbol = expected[(contract, trading_day)]
        exchange = symbol_exchanges.get(symbol)
        if exchange is None:
            raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
        matches = tuple(_SESSION.finditer(values[(contract, trading_day)]))
        if not matches:
            raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
        for index, match in enumerate(matches, start=1):
            start_time = time.fromisoformat(match.group("start"))
            end_time = time.fromisoformat(match.group("end"))
            rows.append(
                {
                    "exchange_code": exchange,
                    "instrument_symbol": symbol,
                    "session_name": f"session_{index}",
                    "start_time": start_time,
                    "end_time": end_time,
                    "effective_from": trading_day,
                    "effective_to": trading_day,
                    "crosses_midnight": end_time <= start_time,
                    "is_active": True,
                    "provider": "rqdata",
                }
            )
    return tuple(rows)


def _days(start: date, end: date):
    """闭区间自然日迭代。"""
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


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


def _is_rqdata_quota_error(exc: Exception) -> bool:
    """识别 RQData 配额/限流错误，供 fetch 转为可恢复的 PROVIDER_QUOTA_EXHAUSTED。"""
    code = str(getattr(exc, "code", "")).upper()
    if code in {"RQDATA_QUOTA_EXCEEDED", "RQDATA_DAILY_QUOTA_EXCEEDED"}:
        return True
    if not type(exc).__module__.startswith("rqdatac"):
        return False
    text = str(exc).lower()
    return "quota" in text or "rate limit" in text or "daily download limit" in text
