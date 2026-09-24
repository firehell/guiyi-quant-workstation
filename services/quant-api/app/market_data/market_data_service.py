"""MarketDataService：数据核心 V2 唯一历史读入口。

``MarketDataService`` 是消费者（Market API、CLI 等）访问 canonical 数据的**唯一门面**：
- 物理序列（``continuous`` / ``contract``）：经八表 Catalog 定位月分区，再读 Parquet；
- 逻辑序列 ``actual_dominant``：按 ``MainContractMap`` 逐日映射到具体合约数据集后拼接，
  周线另按「完整交易周」规则选取映射日。

本模块强制执行分区连续性、行数一致、bar 严格递增等 fail-closed 校验；
映射或物理数据缺失时不回退、不插值，直接 ``MarketDataError``。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from app.core.env import PROJECT_ROOT
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.errors import InfrastructureError
from app.market_data.diagnostics import DATA_REASONS, data_reason, safe_context

from app.market_data.catalog import (
    CatalogError,
    CatalogPartition,
    MainMapFact,
    MarketCatalog,
)
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    ActualDominantRecentBarsQuery,
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    DatasetKey,
    DatasetKind,
    INTRADAY_FREQUENCIES,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageCursorMode,
    SeriesPageQuery,
    SeriesQuery,
)
from app.market_data.product_retirement import (
    ProductRetiredError,
    assert_not_retired,
    is_retired,
    load_retired_products,
)
from app.market_data.product_taxonomy import load_product_taxonomy
from app.market_data.session_clock import (
    SessionClockError,
    session_windows_for_trading_day,
)
from app.market_data.storage import CanonicalMonthlyStore, StorageError
from app.market_data.source_quality import PriceUnavailableFact, SourceQualityFact
from app.market_data.weekly_quality import (
    WeeklySourceInterruption,
    WEEKLY_SOURCE_CLASSIFICATION_VERSION,
    WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2,
    classify_weekly_source,
    weekly_daily_revision_sha256,
)
from app.models import Instrument, MainContractMap, TradingCalendar, TradingSession


SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketDataError(RuntimeError):
    """服务层业务失败：以稳定 ``code`` 字符串标识，不含存储内部细节。"""

    def __init__(
        self, code: str, *, reason: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.reason = reason if reason in DATA_REASONS else data_reason(code)
        self.context = safe_context(context)
        super().__init__(code)


class ActualDominantSourceTradingDayMissingError(MarketDataError):
    """The recent actual-dominant page has no Bar for its exact source day."""

    def __init__(self) -> None:
        super().__init__("ACTUAL_DOMINANT_SOURCE_TRADING_DAY_MISSING")


@dataclass(frozen=True, slots=True)
class DominantContractSummary:
    """各品种最新主力映射一行摘要（映射日 + 实际合约代码）。"""

    symbol: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


@dataclass(frozen=True, slots=True)
class DominantContractSegmentSummary:
    """品种当前连续 rank-1 主力区段。"""

    symbol: str
    contract: str
    start_trading_day: date
    end_trading_day: date


class MarketDataService:
    """V2 历史市场数据查询服务：Catalog 定位 + Parquet 读取 + 主力拼接。

    依赖注入 ``MarketCatalog`` 与 ``CanonicalMonthlyStore``，自身无全局状态。
    """

    def __init__(self, catalog: MarketCatalog, store: CanonicalMonthlyStore) -> None:
        self.catalog = catalog
        self.store = store

    def query(self, request: SeriesQuery) -> MarketSeriesResult:
        """执行序列查询；``actual_dominant`` 走拼接路径，其余读单一物理数据集。"""
        try:
            assert_not_retired(request.symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return self._actual_dominant(request)
        assert request.physical_key is not None
        bars, _ = self._read_physical(request.physical_key, request)
        try:
            days = self.catalog.trading_days_overlapping_window(
                request.symbol, request.start, request.end
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        self._validate_actual_endpoints(
            request.symbol,
            request.frequency,
            {day: request.physical_key.series_or_contract for day in days},
            bars,
            request.start,
            request.end,
            missing_code="DATASET_OR_PARTITION_MISSING",
            dataset_kind=request.physical_key.kind,
        )
        return self._result(
            request,
            bars,
            (),
        )

    def query_maintenance_expected(
        self, request: SeriesQuery, expected: tuple[datetime, ...]
    ) -> MarketSeriesResult:
        """Strict publication readback against the maintainer's frozen target.

        The maintenance plan already proved its Calendar/Session endpoints. Reading
        those same facts through MDS must not depend on a second Calendar query.
        """
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT or request.physical_key is None:
            raise MarketDataError("MAINTENANCE_READ_SCOPE_INVALID")
        bars, _ = self._read_physical(request.physical_key, request)
        if tuple(bar.bar_end for bar in bars) != expected:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        return self._result(request, bars, ())

    def read_physical_daily_quality(
        self, request: SeriesQuery, *, require_window_coverage: bool = True,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[PriceUnavailableFact, ...]]:
        """Existing quality seam: accept only the original PRICE_UNAVAILABLE type."""
        bars, facts = self.read_physical_daily_quality_union(
            request, require_window_coverage=require_window_coverage,
        )
        if any(not isinstance(item, PriceUnavailableFact) for item in facts):
            raise MarketDataError("SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED")
        return bars, tuple(item for item in facts if isinstance(item, PriceUnavailableFact))

    def read_physical_daily_quality_union(
        self, request: SeriesQuery, *, require_window_coverage: bool = True,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceQualityFact, ...]]:
        """Opt-in D1 seam returning the approved typed source-quality union."""
        if request.frequency is not BarFrequency.D1 or request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            raise MarketDataError("SOURCE_QUALITY_SCOPE_INVALID")
        key = request.physical_key
        if key is None:
            raise MarketDataError("SOURCE_QUALITY_SCOPE_INVALID")
        partitions = self.catalog.partitions(key, request.start, request.end)
        if not partitions or {(p.year, p.month) for p in partitions} != _months_between(
            (partitions[0].year, partitions[0].month),
            (partitions[-1].year, partitions[-1].month),
        ):
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        if require_window_coverage and (
            min((p.source_coverage_start or p.coverage_start) for p in partitions) > request.start
            or max((p.source_coverage_end or p.coverage_end) for p in partitions) < request.end
        ):
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        bars: list[CanonicalBar] = []
        exceptions: list[SourceQualityFact] = []
        try:
            for partition in partitions:
                valid, unavailable = self.store.read_catalog_partition_quality(partition)
                bars.extend(bar for bar in valid if request.start < bar.bar_end <= request.end)
                exceptions.extend(item for item in unavailable if request.start < item.bar_end <= request.end)
        except StorageError as exc:
            raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
        if not bars and not exceptions:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        return tuple(bars), tuple(exceptions)

    def contract_daily_bars_as_of(
        self,
        *,
        symbol: str,
        contract: str,
        as_of: datetime,
        limit: int = 5,
    ) -> tuple[CanonicalBar, ...]:
        """Read recent physical D1 bars and reject any fact beyond the read cutoff."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise MarketDataError("MARKET_HOME_LIVE_CUTOFF_INVALID")
        result = self.query_page(
            SeriesPageQuery(
                SeriesKind.CONTRACT,
                symbol,
                BarFrequency.D1,
                limit=limit,
                contract=contract,
            )
        )
        cutoff = as_of.astimezone(UTC)
        if any(bar.bar_end > cutoff for bar in result.bars):
            raise MarketDataError("MARKET_HOME_LIVE_DAILY_AFTER_CUTOFF")
        return result.bars

    def query_physical_daily_quality_as_of(
        self, *, symbol: str, contract: str, trading_day: date, limit: int,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[PriceUnavailableFact, ...]]:
        """A bounded completed D1 window, counting source gaps as endpoints.

        This explicit quality consumer must never shorten its promised window
        to committed coverage or backfill missing prices with older valid Bars.
        Ordinary series/page readers remain strict.
        """
        bars, gaps = self._query_physical_daily_quality_as_of(
            symbol=symbol, contract=contract, trading_day=trading_day, limit=limit,
            include_nonpositive_close=False,
        )
        if any(not isinstance(item, PriceUnavailableFact) for item in gaps):
            raise MarketDataError("SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED")
        return bars, tuple(item for item in gaps if isinstance(item, PriceUnavailableFact))

    def query_physical_daily_quality_union_as_of(
        self, *, symbol: str, contract: str, trading_day: date, limit: int,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceQualityFact, ...]]:
        """Read a bounded D1 window while preserving every approved quality fact."""
        return self._query_physical_daily_quality_as_of(
            symbol=symbol, contract=contract, trading_day=trading_day, limit=limit,
            include_nonpositive_close=True,
        )

    def _query_physical_daily_quality_as_of(
        self, *, symbol: str, contract: str, trading_day: date, limit: int,
        include_nonpositive_close: bool,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceQualityFact, ...]]:
        page = SeriesPageQuery(
            SeriesKind.CONTRACT, symbol, BarFrequency.D1,
            contract=contract, limit=limit,
        )
        assert page.contract is not None
        _, cutoff = self._trading_day_window(
            symbol=page.symbol, since=trading_day, through=trading_day,
        )
        expected = self.expected_contract_replay_endpoints(
            symbol=page.symbol, contract=page.contract, frequency=BarFrequency.D1,
            trading_day=trading_day, cutoff=cutoff,
        )[-page.limit:]
        if not expected or expected[-1] != (cutoff, trading_day):
            raise MarketDataError("CONTRACT_REPLAY_COVERAGE_UNAVAILABLE")
        request = SeriesQuery(
            SeriesKind.CONTRACT, page.symbol, BarFrequency.D1,
            expected[0][0] - timedelta(microseconds=1), cutoff,
            contract=page.contract,
        )
        if include_nonpositive_close:
            bars, gaps = self.read_physical_daily_quality_union(
                request, require_window_coverage=False,
            )
        else:
            bars, legacy_gaps = self.read_physical_daily_quality(
                request, require_window_coverage=False,
            )
            gaps = tuple(legacy_gaps)
        actual = tuple(sorted(
            [(bar.bar_end, bar.trading_day) for bar in bars]
            + [(gap.bar_end, gap.trading_day) for gap in gaps]
        ))
        if actual != expected:
            if len(set(actual)) != len(actual) or set(actual) - set(expected):
                raise MarketDataError("BAR_IDENTITY_CONFLICT")
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        return bars, gaps

    def query_physical_bars_as_of(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency,
        trading_day: date,
        limit: int,
    ) -> tuple[CanonicalBar, ...]:
        """Bound a physical D1/W1 history page by an authoritative completed day."""
        frequency = BarFrequency(frequency)
        if frequency not in (BarFrequency.D1, BarFrequency.W1):
            raise MarketDataError("MARKET_HOME_FREQUENCY_INVALID")
        key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, frequency)
        lower_day = trading_day
        if frequency is BarFrequency.W1:
            lower_day = trading_day - timedelta(days=35)
            try:
                lower_day = max(lower_day, self.catalog.contract_fact(symbol, contract).listed_date)
            except CatalogError as exc:
                raise MarketDataError(exc.code) from exc
        try:
            days = self.catalog.trading_days(symbol, lower_day, trading_day)
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if trading_day not in days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        source = DatabaseCoverageSource(
            self.catalog.session,
            PROJECT_ROOT / "data/universe/product_window_starts.csv",
        )
        try:
            endpoints = source.expected_bar_end_pairs_for_trading_days(key, days)
        except InfrastructureError as exc:
            raise MarketDataError(exc.code) from exc
        if not endpoints:
            return ()
        cutoff = max(end for end, _ in endpoints)
        partitions = self.catalog.partitions_before(key, cutoff)
        if not partitions:
            return ()
        committed = tuple(
            partition.source_coverage_end or partition.coverage_end
            for partition in partitions
            if partition.source_coverage_end is not None or partition.coverage_end is not None
        )
        if not committed:
            raise MarketDataError("PRICE_UNAVAILABLE")
        cutoff = min(cutoff, max(committed))
        return self.query_page_inclusive(SeriesPageQuery(
            SeriesKind.CONTRACT, symbol, frequency,
            limit=limit, contract=contract, before=cutoff,
        )).bars

    def previous_trading_day(self, symbol: str, trading_day: date) -> date:
        """Resolve and prove the exact Calendar trading day before one quote day."""

        try:
            previous = DatabaseCoverageSource(
                self.catalog.session,
                PROJECT_ROOT / "data/universe/product_window_starts.csv",
            ).previous_trading_day(symbol, trading_day)
            calendar = self.catalog.calendar_days(
                symbol, previous, trading_day - timedelta(days=1)
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        except InfrastructureError as exc:
            raise MarketDataError(exc.code) from exc
        expected = tuple(
            previous + timedelta(days=offset)
            for offset in range((trading_day - previous).days)
        )
        if tuple(day for day, _ in calendar) != expected:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        return previous

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
    ) -> tuple[SessionWindow, ...]:
        """Read the authoritative Catalog TradingSession windows for one day."""

        try:
            assert_not_retired(symbol)
            exchange = self.catalog.exchange_for_symbol(symbol)
            windows = session_windows_for_trading_day(
                self.catalog.session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_day,
            )
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        except (CatalogError, SessionClockError) as exc:
            raise MarketDataError(exc.code) from exc
        if not windows:
            raise MarketDataError("TRADING_SESSION_MISSING")
        return windows

    def historical_metadata_evidence(
        self, *, symbol: str, since: date, through: date,
    ) -> dict[str, object]:
        """Return exact authoritative Calendar/Session rows for a replay window."""
        if since > through:
            raise MarketDataError("QUERY_WINDOW_INVALID")
        try:
            exchange = self.catalog.exchange_for_symbol(symbol)
            calendars = tuple(self.catalog.session.scalars(
                select(TradingCalendar).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date >= since,
                    TradingCalendar.trade_date <= through,
                ).order_by(TradingCalendar.trade_date)
            ))
            sessions = tuple(self.catalog.session.scalars(
                select(TradingSession).where(
                    TradingSession.exchange_code == exchange,
                    TradingSession.instrument_symbol == symbol.strip().lower(),
                    TradingSession.is_active.is_(True),
                    TradingSession.effective_from <= through,
                    (
                        TradingSession.effective_to.is_(None)
                        | (TradingSession.effective_to >= since)
                    ),
                ).order_by(
                    TradingSession.effective_from,
                    TradingSession.session_name,
                    TradingSession.start_time,
                )
            ))
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        expected_days = (through - since).days + 1
        if len(calendars) != expected_days or not sessions:
            raise MarketDataError("HISTORICAL_METADATA_EVIDENCE_MISSING")
        return {
            "schema_version": "historical_metadata_evidence_v1",
            "exchange": exchange,
            "symbol": symbol.strip().lower(),
            "since": since.isoformat(),
            "through": through.isoformat(),
            "calendar": [
                [
                    row.trade_date.isoformat(), row.is_trading_day,
                    row.has_night_session, row.provider, row.remark,
                ]
                for row in calendars
            ],
            "sessions": [
                [
                    row.session_name, row.start_time.isoformat(),
                    row.end_time.isoformat(), row.effective_from.isoformat(),
                    None if row.effective_to is None else row.effective_to.isoformat(),
                    row.crosses_midnight, row.provider,
                    row.created_at.isoformat(),
                ]
                for row in sessions
            ],
        }

    def trading_days_overlapping_window(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[date, ...]:
        """Resolve as-of Calendar/Session overlap without leaking Catalog errors."""
        try:
            assert_not_retired(symbol)
            return self.catalog.trading_days_overlapping_window(symbol, start, end)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc

    def completed_trading_days(
        self,
        *,
        symbol: str,
        start: datetime,
        as_of: datetime,
        latest: date,
        calendar_since: date | None = None,
    ) -> tuple[date, ...]:
        """Resolve completed days; optionally prove the entire Calendar horizon."""
        if calendar_since is not None:
            if type(calendar_since) is not date or calendar_since > latest:
                raise MarketDataError("TRADING_CALENDAR_MISSING")
            self._exact_calendar(symbol, calendar_since, latest)
        try:
            assert_not_retired(symbol)
            windows = (
                self.catalog.session_windows_overlapping_window(
                    symbol, start, as_of + timedelta(microseconds=1),
                    earliest=calendar_since, latest=latest,
                )
                if calendar_since is not None
                else self.catalog.session_windows_overlapping_window(symbol, start, as_of + timedelta(microseconds=1))
            )
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        return tuple(
            day
            for day, sessions in windows
            if day <= latest and max(window.end for window in sessions) <= as_of
        )

    def completed_calendar_week(
        self, *, symbol: str, week_monday: date, as_of: datetime,
    ) -> tuple[date, datetime] | None:
        """Return the last Session cutoff only after an entire ISO week is known."""
        if week_monday.isoweekday() != 1 or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        calendar = self._exact_calendar(
            symbol, week_monday, week_monday + timedelta(days=6),
        )
        trading_days = tuple(day for day, trades in calendar if trades)
        if not trading_days:
            return None
        last_day = trading_days[-1]
        last_end = max(
            window.end for window in self.session_windows(
                symbol=symbol, trading_day=last_day,
            )
        )
        cutoff = last_end.astimezone(UTC) + timedelta(microseconds=1)
        return (last_day, cutoff) if cutoff <= as_of.astimezone(UTC) else None

    def weekly_tail_unpublished(self, *, symbol: str, week_end: date) -> bool:
        """Prove the completed tail week has no rank1 facts at all.

        A partly published week is an internal mapping gap, never a fallback.
        """
        monday = week_end - timedelta(days=week_end.isoweekday() - 1)
        days = tuple(day for day, trades in self._exact_calendar(
            symbol, monday, monday + timedelta(days=6),
        ) if trades)
        if not days or days[-1] != week_end:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        try:
            mappings = self.catalog.main_map(symbol, days[0], week_end)
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        mapped_days = {mapping.trade_date for mapping in mappings}
        if mapped_days and mapped_days != set(days):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        return not mapped_days

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        """按精确交易日读取 actual-dominant，不由消费者猜自然时间边界。"""
        start, end = self._trading_day_window(
            symbol=request.symbol,
            since=request.since,
            through=request.through,
        )
        return replace(
            self.query(
                SeriesQuery(
                    SeriesKind.ACTUAL_DOMINANT,
                    request.symbol,
                    request.frequency,
                    start,
                    end,
                )
            ),
            requested_trading_day_window=(request.since, request.through),
        )

    def query_actual_dominant_trading_days_quality(
        self,
        request: ActualDominantTradingDayQuery,
        *,
        weekly_classification_version: str = WEEKLY_SOURCE_CLASSIFICATION_VERSION,
    ) -> tuple[MarketSeriesResult, tuple[tuple[str, PriceUnavailableFact | WeeklySourceInterruption], ...]]:
        """D1/W1 rank-1 read with exact source interruptions."""
        if request.frequency is BarFrequency.W1:
            return self._actual_dominant_weekly_quality(
                request, classification_version=weekly_classification_version,
            )
        if request.frequency is not BarFrequency.D1:
            raise MarketDataError("SOURCE_QUALITY_SCOPE_INVALID")
        if weekly_classification_version != WEEKLY_SOURCE_CLASSIFICATION_VERSION:
            raise MarketDataError("SOURCE_QUALITY_SCOPE_INVALID")
        start, end = self._trading_day_window(
            symbol=request.symbol, since=request.since, through=request.through,
        )
        try:
            windows = self.catalog.session_windows_overlapping_window(
                request.symbol, start, end,
            )
            mappings = self.catalog.main_map(
                request.symbol, request.since, request.through,
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        days = tuple(day for day, _ in windows if request.since <= day <= request.through)
        by_day = {mapping.trade_date: mapping.contract for mapping in mappings}
        if not days or set(days) != set(by_day):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        query = SeriesQuery(
            SeriesKind.ACTUAL_DOMINANT, request.symbol, request.frequency,
            start, end,
        )
        bars: list[CanonicalBar] = []
        exceptions: list[tuple[str, PriceUnavailableFact]] = []
        for contract in dict.fromkeys(by_day.values()):
            physical = SeriesQuery(
                SeriesKind.CONTRACT, request.symbol, request.frequency,
                start, end, contract=contract,
            )
            contract_bars, unavailable = self.read_physical_daily_quality(
                physical, require_window_coverage=False,
            )
            bars.extend(
                bar for bar in contract_bars
                if by_day.get(bar.trading_day) == contract
            )
            exceptions.extend(
                (contract, item) for item in unavailable
                if by_day.get(item.trading_day) == contract
            )
        bars.sort(key=lambda item: item.bar_end)
        exceptions.sort(key=lambda item: item[1].bar_end)
        price_days = {bar.trading_day for bar in bars}
        unavailable_days = {item.trading_day for _, item in exceptions}
        if (
            price_days & unavailable_days
            or price_days | unavailable_days != set(days)
            or len(bars) + len(exceptions) != len(days)
        ):
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        valid_mappings = tuple(mapping for mapping in mappings if mapping.trade_date in price_days)
        return (
            replace(
                self._result(query, tuple(bars), _segments(valid_mappings)),
                requested_trading_day_window=(request.since, request.through),
            ),
            tuple(exceptions),
        )

    def _actual_dominant_weekly_quality(
        self,
        request: ActualDominantTradingDayQuery,
        *,
        classification_version: str,
    ) -> tuple[MarketSeriesResult, tuple[tuple[str, WeeklySourceInterruption], ...]]:
        start, end = self._trading_day_window(
            symbol=request.symbol, since=request.since, through=request.through,
        )
        try:
            windows = self.catalog.session_windows_overlapping_window(
                request.symbol, start, end,
            )
            mappings = self.catalog.main_map(
                request.symbol, request.since, request.through,
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        days = tuple(
            day for day, _ in windows if request.since <= day <= request.through
        )
        by_day = {item.trade_date: item for item in mappings}
        if not days or set(days) != set(by_day):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        query = SeriesQuery(
            SeriesKind.ACTUAL_DOMINANT, request.symbol, BarFrequency.W1,
            start, end,
        )
        completed = tuple(
            by_day[day] for day, sessions in windows
            if day in by_day and max(window.end for window in sessions) <= end
        )
        try:
            selected = self._weekly_mappings(query, completed)
        except MarketDataError as exc:
            if exc.code != "COMPLETE_WEEK_MISSING":
                raise
            return (
                replace(
                    self._result(query, (), ()),
                    requested_trading_day_window=(request.since, request.through),
                ),
                (),
            )
        weekly_owner = {item.trade_date: item.contract for item in selected}
        session_end = {
            day: max(window.end for window in sessions) for day, sessions in windows
        }
        bars: list[CanonicalBar] = []
        interruptions: list[tuple[str, WeeklySourceInterruption]] = []
        for contract in dict.fromkeys(item.contract for item in selected):
            through = max(day for day, owner in weekly_owner.items() if owner == contract)
            physical, gaps = self.query_contract_weekly_replay_quality(
                symbol=request.symbol, contract=contract, through=through,
                cutoff=session_end[through],
                classification_version=classification_version,
                since=request.since - timedelta(days=request.since.weekday()),
            )
            bars.extend(
                bar for bar in physical
                if weekly_owner.get(bar.trading_day) == contract
            )
            interruptions.extend(
                (contract, gap) for gap in gaps
                if weekly_owner.get(gap.expected_daily_endpoints[-1][1]) == contract
            )
        bars.sort(key=lambda bar: bar.bar_end)
        interruptions.sort(key=lambda item: item[1].week_end)
        bar_days = {bar.trading_day for bar in bars}
        gap_days = {gap.expected_daily_endpoints[-1][1] for _, gap in interruptions}
        if (bar_days & gap_days or bar_days | gap_days != set(weekly_owner)
            or len(bars) + len(interruptions) != len(selected)):
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        valid_mappings = tuple(item for item in selected if item.trade_date in bar_days)
        return (
            replace(
                self._result(query, tuple(bars), _segments(valid_mappings)),
                requested_trading_day_window=(request.since, request.through),
            ),
            tuple(interruptions),
        )

    def query_actual_dominant_recent_bars(
        self,
        request: ActualDominantRecentBarsQuery,
    ) -> MarketSeriesPageResult:
        """Return the latest actual-dominant bars through one exact trading day."""
        _, session_end = self._trading_day_window(
            symbol=request.symbol,
            since=request.through,
            through=request.through,
        )
        result = self.query_page(
            SeriesPageQuery(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol=request.symbol,
                frequency=request.frequency,
                before=session_end + timedelta(microseconds=1),
                limit=request.limit,
            )
        )
        bars = result.bars
        if any(bar.trading_day > request.through for bar in bars) or any(
            current.bar_end <= previous.bar_end
            for previous, current in zip(bars, bars[1:], strict=False)
        ):
            raise MarketDataError("ACTUAL_DOMINANT_RECENT_BARS_INVALID")
        if not bars or bars[-1].trading_day < request.through:
            raise ActualDominantSourceTradingDayMissingError
        if bars[-1].trading_day != request.through:
            raise MarketDataError("ACTUAL_DOMINANT_RECENT_BARS_INVALID")
        return result

    def query_contract_trading_days(
        self,
        request: ContractTradingDayQuery,
    ) -> MarketSeriesResult:
        """按合约有效期内的精确交易日读取单一物理合约。"""
        try:
            assert_not_retired(request.symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        try:
            fact = self.catalog.contract_fact(request.symbol, request.contract)
        except CatalogError as exc:
            code = (
                "CONTRACT_METADATA_MISSING"
                if exc.code
                in {
                    "CONTRACT_NOT_FOUND",
                    "CONTRACT_SYMBOL_MISMATCH",
                    "CONTRACT_METADATA_MISSING",
                }
                else exc.code
            )
            raise MarketDataError(code) from exc
        since = max(request.since, fact.listed_date)
        through = min(request.through, fact.expired_date - timedelta(days=1))
        if since > through:
            raise MarketDataError("CONTRACT_ACTIVE_WINDOW_MISSING")
        start, end = self._trading_day_window(
            symbol=request.symbol,
            since=since,
            through=through,
        )
        query = SeriesQuery(
            SeriesKind.CONTRACT,
            request.symbol,
            request.frequency,
            start,
            end,
            contract=request.contract,
        )
        assert query.physical_key is not None
        bars, _ = self._read_physical(
            query.physical_key, query, require_window_coverage=False,
        )
        try:
            days = tuple(
                day for day, _ in self.catalog.session_windows_overlapping_window(
                    request.symbol, start, end, earliest=since, latest=through,
                )
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        self._validate_actual_endpoints(
            request.symbol,
            request.frequency,
            {day: request.contract for day in days},
            bars,
            start,
            end,
            missing_code="DATASET_OR_PARTITION_MISSING",
        )
        return replace(
            self._result(query, bars, ()),
            requested_trading_day_window=(since, through),
        )

    def query_contract_replay_quality(
        self, *, symbol: str, contract: str, through: date, cutoff: datetime,
        since: date | None = None,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[PriceUnavailableFact, ...]]:
        """Existing replay seam; new quality classifications remain unsupported."""
        bars, facts = self._query_contract_replay_quality_union(
            symbol=symbol, contract=contract, through=through, cutoff=cutoff,
            union=False, since=since,
        )
        return bars, tuple(item for item in facts if isinstance(item, PriceUnavailableFact))

    def query_contract_replay_quality_union(
        self, *, symbol: str, contract: str, through: date, cutoff: datetime,
        since: date | None = None,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceQualityFact, ...]]:
        """SuBing D1 opt-in replay over ValidBar or a proved typed break."""
        return self._query_contract_replay_quality_union(
            symbol=symbol, contract=contract, through=through, cutoff=cutoff,
            union=True, since=since,
        )

    def _query_contract_replay_quality_union(
        self, *, symbol: str, contract: str, through: date, cutoff: datetime,
        union: bool, since: date | None,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceQualityFact, ...]]:
        try:
            fact = self.catalog.contract_fact(symbol, contract)
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if not fact.listed_date <= through < fact.expired_date or (
            since is not None and since > through
        ):
            raise MarketDataError("CONTRACT_ACTIVE_WINDOW_MISSING")
        start, end = self._trading_day_window(
            symbol=symbol, since=max(fact.listed_date, since or fact.listed_date), through=through,
        )
        if cutoff > end or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise MarketDataError("CONTRACT_REPLAY_CUTOFF_INVALID")
        reader = (
            self.read_physical_daily_quality_union
            if union else self.read_physical_daily_quality
        )
        bars, exceptions = reader(SeriesQuery(
            SeriesKind.CONTRACT, symbol, BarFrequency.D1,
            start, end, contract=contract,
        ), require_window_coverage=False)
        bars = tuple(bar for bar in bars if bar.bar_end <= cutoff)
        exceptions = tuple(item for item in exceptions if item.bar_end <= cutoff)
        expected = self.expected_contract_replay_endpoints(
            symbol=symbol, contract=contract, frequency=BarFrequency.D1,
            trading_day=through, cutoff=cutoff, since=since,
        )
        actual = tuple(sorted((bar.bar_end, bar.trading_day) for bar in bars))
        combined = tuple(sorted((*actual, *((item.bar_end, item.trading_day) for item in exceptions))))
        if combined != expected:
            context: dict[str, object] = {
                "symbol": symbol, "contract": contract, "frequency": BarFrequency.D1,
                "trading_day": through, "cutoff": cutoff,
                "expected_count": len(expected), "actual_count": len(combined),
            }
            if any(b[0] <= a[0] or b[1] < a[1] for a, b in zip(combined, combined[1:])):
                reason = "REPLAY_ORDER_INVALID"
            elif set(combined) - set(expected):
                reason = "REPLAY_ENDPOINTS_EXTRA"
            else:
                present = set(combined)
                missing = tuple(point for point in expected if point not in present)
                reason = (
                    "REPLAY_PREFIX_MISSING"
                    if combined and combined == expected[-len(combined):]
                    else "REPLAY_ENDPOINTS_MISSING"
                )
                context.update(
                    missing_count=len(missing), first_missing_at=missing[0][0],
                    first_missing_day=missing[0][1],
                )
            raise MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason=reason, context=context,
            )
        return bars, exceptions

    def query_contract_weekly_replay_quality(
        self, *, symbol: str, contract: str, through: date, cutoff: datetime,
        classification_version: str = WEEKLY_SOURCE_CLASSIFICATION_VERSION,
        since: date | None = None,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[WeeklySourceInterruption, ...]]:
        """Read stored W1 Bars and explain absent complete weeks using pinned D1 facts.

        The ordinary series API remains strict. No W1 Bar is synthesized here.
        """
        weekly_since = since - timedelta(days=since.weekday()) if since is not None else None
        if classification_version == WEEKLY_SOURCE_CLASSIFICATION_VERSION:
            daily_bars, daily_gaps = self.query_contract_replay_quality(
                symbol=symbol, contract=contract, through=through, cutoff=cutoff,
                since=weekly_since,
            )
        elif classification_version == WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2:
            daily_bars, daily_gaps = self.query_contract_replay_quality_union(
                symbol=symbol, contract=contract, through=through, cutoff=cutoff,
                since=weekly_since,
            )
        else:
            raise MarketDataError("SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED")
        weekly_expected = self.expected_contract_replay_endpoints(
            symbol=symbol, contract=contract, frequency=BarFrequency.W1,
            trading_day=through, cutoff=cutoff, since=weekly_since,
        )
        if not weekly_expected:
            return (), ()
        daily_expected = self.expected_contract_replay_endpoints(
            symbol=symbol, contract=contract, frequency=BarFrequency.D1,
            trading_day=through, cutoff=cutoff, since=weekly_since,
        )
        daily_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
        weekly_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
        daily_rows = self.catalog.all_partitions(daily_key)
        daily_partitions = {(row.year, row.month): row for row in daily_rows}
        if len(daily_partitions) != len(daily_rows):
            raise MarketDataError("PARTITION_INTEGRITY_INVALID")
        weekly_months = {(day.year, day.month) for _, day in weekly_expected}
        stored: list[CanonicalBar] = []
        weekly_rows = self.catalog.all_partitions(weekly_key)
        if len({(row.year, row.month) for row in weekly_rows}) != len(weekly_rows):
            raise MarketDataError("PARTITION_INTEGRITY_INVALID")
        try:
            for row in weekly_rows:
                if (row.year, row.month) in weekly_months:
                    stored.extend(
                        bar for bar in self.store.read_catalog_partition(row)
                        if bar.bar_end <= cutoff
                        and (weekly_since is None or bar.trading_day >= weekly_since)
                    )
        except StorageError as exc:
            raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
        by_end = {bar.bar_end: bar for bar in stored}
        if len(by_end) != len(stored) or set(by_end) - {end for end, _ in weekly_expected}:
            raise MarketDataError("WEEKLY_SOURCE_BAR_CONFLICT")
        normal: list[CanonicalBar] = []
        interruptions: list[WeeklySourceInterruption] = []
        for week_end, week_day in weekly_expected:
            week = week_day.isocalendar()[:2]
            expected = tuple(
                point for point in daily_expected
                if point[1].isocalendar()[:2] == week
            )
            bars = tuple(
                bar for bar in daily_bars
                if bar.trading_day.isocalendar()[:2] == week
            )
            gaps = tuple(
                gap for gap in daily_gaps
                if gap.trading_day.isocalendar()[:2] == week
            )
            months = sorted({(day.year, day.month) for _, day in expected})
            if any(month not in daily_partitions for month in months):
                raise MarketDataError(
                    "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
                    reason="DATASET_OR_PARTITION_MISSING",
                    context={"contract": contract, "trading_day": week_day},
                )
            revision = weekly_daily_revision_sha256(
                tuple((daily_partitions[month].file_path.name,
                       daily_partitions[month].source_quality_sha256) for month in months),
                bars,
            )
            try:
                coverage = classify_weekly_source(
                    product=symbol, physical_contract=contract,
                    expected_daily_endpoints=expected,
                    daily_bars=bars, price_unavailable=gaps,
                    daily_revision_sha256=revision,
                    classification_version=classification_version,
                )
            except ValueError as exc:
                reason = (
                    "REPLAY_ENDPOINTS_MISSING"
                    if str(exc) == "WEEKLY_SOURCE_ENDPOINTS_MISSING"
                    else "DATA_INTEGRITY_INVALID"
                )
                raise MarketDataError(
                    "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
                    reason=reason,
                    context={"contract": contract, "trading_day": week_day},
                ) from exc
            persisted = by_end.get(week_end)
            if coverage.interruption is not None:
                if persisted is not None:
                    raise MarketDataError(
                        "WEEKLY_SOURCE_BAR_CONFLICT",
                        context={"contract": contract, "trading_day": week_day},
                    )
                interruptions.append(coverage.interruption)
                continue
            if persisted is None:
                raise MarketDataError(
                    "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
                    reason="REPLAY_ENDPOINTS_MISSING",
                    context={"contract": contract, "trading_day": week_day},
                )
            # Reuse the writer's source aggregation only for equality validation.
            from app.market_data.rqdata_adapter import _aggregate_daily_rows

            expected_bar = _aggregate_daily_rows(tuple(
                (bar.trading_day, {
                    "open": bar.open, "high": bar.high, "low": bar.low,
                    "close": bar.close, "volume": bar.volume,
                    "turnover": bar.turnover, "open_interest": bar.open_interest,
                }) for bar in bars
            ), bar_end=week_end)
            if persisted != expected_bar:
                raise MarketDataError(
                    "WEEKLY_SOURCE_BAR_CONFLICT",
                    context={"contract": contract, "trading_day": week_day},
                )
            normal.append(persisted)
        return tuple(normal), tuple(interruptions)

    def validate_contract_replay_coverage(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency,
        trading_day: date,
        cutoff: datetime,
        after: datetime | None,
        bars: tuple[CanonicalBar, ...],
    ) -> None:
        """Prove a physical replay against the same lifecycle/session coverage authority.

        Live can complete today's suffix, but cannot supply missing prior-day history.
        The caller has already checked overlap and physical provenance.
        """
        expected = self.expected_contract_replay_endpoints(
            symbol=symbol,
            contract=contract,
            frequency=frequency,
            trading_day=trading_day,
            cutoff=cutoff,
            after=after,
        )
        actual = tuple((bar.bar_end, bar.trading_day) for bar in bars)
        if expected and expected[-1] == (cutoff, trading_day) and actual == expected:
            return
        context: dict[str, object] = {
            "symbol": symbol, "contract": contract, "frequency": frequency,
            "trading_day": trading_day, "cutoff": cutoff,
            "expected_count": len(expected), "actual_count": len(actual),
        }
        if not expected or expected[-1] != (cutoff, trading_day):
            reason = "REPLAY_CUTOFF_MISMATCH"
        elif any(b[0] <= a[0] or b[1] < a[1] for a, b in zip(actual, actual[1:])):
            reason = "REPLAY_ORDER_INVALID"
        elif set(actual) - set(expected):
            reason = "REPLAY_ENDPOINTS_EXTRA"
        else:
            actual_set = set(actual)
            missing = tuple(point for point in expected if point not in actual_set)
            reason = (
                "REPLAY_PREFIX_MISSING"
                if actual and actual == expected[-len(actual):]
                else "REPLAY_ENDPOINTS_MISSING"
            )
            context.update(
                missing_count=len(missing), first_missing_at=missing[0][0],
                first_missing_day=missing[0][1],
            )
        raise MarketDataError(
            "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason=reason, context=context
        )

    def expected_contract_replay_endpoints(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency | str,
        trading_day: date,
        cutoff: datetime,
        after: datetime | None = None,
        since: date | None = None,
    ) -> tuple[tuple[datetime, date], ...]:
        """Shared lifecycle/session authority for validation and read-only diagnosis."""
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise MarketDataError("CONTRACT_REPLAY_CUTOFF_INVALID")
        try:
            fact = self.catalog.contract_fact(symbol, contract)
            if not fact.listed_date <= trading_day < fact.expired_date:
                raise MarketDataError("CONTRACT_ACTIVE_WINDOW_MISSING")
            coverage = DatabaseCoverageSource(
                self.catalog.session,
                PROJECT_ROOT / "data/universe/product_window_starts.csv",
            )
            days = coverage.contract_trading_days(
                fact, max(fact.listed_date, since or fact.listed_date), trading_day
            )
            key = DatasetKey(
                DatasetKind.CONTRACT, symbol, contract, BarFrequency(frequency)
            )
            return tuple(
                (bar_end, day)
                for bar_end, day in coverage.expected_bar_end_pairs_for_trading_days(
                    key, days
                )
                if bar_end <= cutoff and (after is None or bar_end > after)
            )
        except (CatalogError, InfrastructureError) as exc:
            raise MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason=data_reason(exc.code),
                context={"symbol": symbol, "contract": contract, "frequency": frequency,
                         "trading_day": trading_day, "cutoff": cutoff},
            ) from exc

    def validate_actual_dominant_alert_window(
        self,
        *,
        symbol: str,
        frequency: BarFrequency | str,
        trading_day: date,
        current_contract: str,
        cutoff: datetime,
        bars: tuple[CanonicalBar, ...],
        bar_contracts: tuple[str, ...],
    ) -> None:
        """Prove an owned intraday Alert window against Calendar/Session endpoints."""
        try:
            normalized_frequency = BarFrequency(frequency)
            if (
                normalized_frequency not in INTRADAY_FREQUENCIES
                or not bars
                or len(bars) != len(bar_contracts)
                or bars[-1].bar_end != cutoff
                or bars[-1].trading_day != trading_day
                or bar_contracts[-1] != current_contract
            ):
                raise ValueError
            first_day = bars[0].trading_day
            if first_day > trading_day:
                raise ValueError
            calendar = self._exact_calendar(symbol, first_day, trading_day)
            days = tuple(day for day, is_trading in calendar if is_trading)
            if not days or days[-1] != trading_day:
                raise ValueError

            historical_days = tuple(day for day in days if day < trading_day)
            mappings = (
                self.catalog.main_map(symbol, historical_days[0], historical_days[-1])
                if historical_days
                else ()
            )
            owner_by_day = {item.trade_date: item.contract for item in mappings}
            if set(owner_by_day) != set(historical_days):
                raise ValueError
            current_mapping = self.catalog.main_map(symbol, trading_day, trading_day)
            if current_mapping and (
                len(current_mapping) != 1
                or current_mapping[0].contract != current_contract
            ):
                raise ValueError
            owner_by_day[trading_day] = current_contract

            expected: list[tuple[datetime, date, str]] = []
            for day in days:
                owner = owner_by_day.get(day)
                if owner is None:
                    raise ValueError
                expected.extend(
                    (bar_end, endpoint_day, owner)
                    for bar_end, endpoint_day in self.expected_contract_replay_endpoints(
                        symbol=symbol,
                        contract=owner,
                        frequency=normalized_frequency,
                        trading_day=day,
                        cutoff=cutoff,
                        since=day,
                    )
                    if bar_end >= bars[0].bar_end
                )
            actual = tuple(
                (bar.bar_end, bar.trading_day, owner)
                for bar, owner in zip(bars, bar_contracts, strict=True)
            )
            if actual != tuple(expected):
                raise ValueError
        except (CatalogError, MarketDataError, ValueError) as exc:
            raise MarketDataError("ACTUAL_DOMINANT_ALERT_WINDOW_UNAVAILABLE") from exc

    def _trading_day_window(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
    ) -> tuple[datetime, datetime]:
        """Resolve inclusive trading-day bounds to the exact outer Session window."""
        calendar_days = self._exact_calendar(symbol, since, through)
        trading_days = tuple(
            day for day, is_trading_day in calendar_days if is_trading_day
        )
        if not trading_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        try:
            exchange = self.catalog.exchange_for_symbol(symbol)
            first_windows = session_windows_for_trading_day(
                self.catalog.session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_days[0],
            )
            last_windows = session_windows_for_trading_day(
                self.catalog.session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_days[-1],
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        except SessionClockError as exc:
            raise MarketDataError(exc.code) from exc
        if not first_windows or not last_windows:
            raise MarketDataError("TRADING_SESSION_MISSING")
        return (
            min(window.start for window in first_windows),
            max(window.end for window in last_windows),
        )

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        """按历史游标返回一页 Canonical bars，游标严格排除自身。"""
        try:
            assert_not_retired(request.symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return self._actual_dominant_page(request)
        assert request.physical_key is not None
        bars, has_more = self._physical_page_bars(request.physical_key, request)
        return self._page_result(
            request,
            bars,
            (),
            has_more_before=has_more,
        )

    def query_alert_history_prefix(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        """Read a published intraday prefix for subsequent Canonical/Live validation.

        The event cutoff bounds selection, not Canonical publication. Only the
        merged Alert window can prove coverage through that completed Live bar.
        Ordinary historical page queries retain their exact endpoint contract.
        """
        try:
            assert_not_retired(request.symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        if (
            request.series_kind is not SeriesKind.ACTUAL_DOMINANT
            or request.frequency not in INTRADAY_FREQUENCIES
            or request.before is None
        ):
            raise MarketDataError("MARKET_READ_IDENTITY_UNSUPPORTED")
        return self._actual_dominant_page(request, published_prefix=True)

    def query_page_inclusive(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        """Return one physical page including its exact completed-bar endpoint.

        This narrow seam is for a replay prefix whose first cursor is an
        observed completed Bar, not an artificial timestamp beyond Catalog
        coverage. Later pages continue through the ordinary exclusive cursor.
        """
        try:
            assert_not_retired(request.symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            raise MarketDataError("INCLUSIVE_PAGE_PHYSICAL_REQUIRED")
        assert request.physical_key is not None
        bars, has_more = self._physical_page_bars(
            request.physical_key,
            request,
            inclusive_before=True,
        )
        return self._page_result(
            request,
            bars,
            (),
            cursor_mode=SeriesPageCursorMode.INCLUSIVE,
            has_more_before=has_more,
        )

    def _physical_page_bars(
        self,
        key: DatasetKey,
        request: SeriesPageQuery,
        *,
        inclusive_before: bool = False,
    ) -> tuple[list[CanonicalBar], bool]:
        partitions = self.catalog.partitions_before(key, request.before)
        if not partitions:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        quality_aware = key.frequency is BarFrequency.D1
        if not quality_aware and any(partition.source_quality for partition in partitions):
            raise MarketDataError("PRICE_UNAVAILABLE")
        selected: list[CanonicalBar] = []
        previous_end: datetime | None = None
        newer_partition: CatalogPartition | None = None
        for partition in partitions:
            partition_end = partition.source_coverage_end or partition.coverage_end
            if (
                newer_partition is None
                and request.before is not None
                and (partition_end is None or partition_end < request.before)
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
            if (
                newer_partition is not None
                and len(
                    _months_between(
                        (partition.year, partition.month),
                        (newer_partition.year, newer_partition.month),
                    )
                )
                > 2
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
            if newer_partition is not None:
                self._validate_partition_coverage_gap(
                    key.symbol,
                    partition,
                    newer_partition,
                )
            values, unavailable = (
                self._partition_quality(partition)
                if quality_aware else (self._partition_bars(partition), ())
            )
            events = sorted((*values, *unavailable), key=lambda item: item.bar_end, reverse=True)
            for event in events:
                if request.before is not None and (
                    event.bar_end > request.before
                    or (not inclusive_before and event.bar_end == request.before)
                ):
                    continue
                if len(selected) == request.limit:
                    self._validate_physical_page_endpoints(
                        key, selected, has_sentinel=True,
                        upper=request.before, inclusive_upper=inclusive_before,
                    )
                    return selected, True
                if isinstance(event, SourceQualityFact):
                    raise MarketDataError(
                        "PRICE_UNAVAILABLE"
                        if isinstance(event, PriceUnavailableFact)
                        else "SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED"
                    )
                if previous_end is not None and event.bar_end >= previous_end:
                    raise MarketDataError("BAR_IDENTITY_CONFLICT")
                selected.append(event)
                previous_end = event.bar_end
            newer_partition = partition
        if not selected:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        self._validate_physical_page_endpoints(
            key, selected, has_sentinel=False,
            upper=request.before, inclusive_upper=inclusive_before,
        )
        return selected, False

    def _validate_physical_page_endpoints(
        self,
        key: DatasetKey,
        selected: list[CanonicalBar],
        *,
        has_sentinel: bool,
        upper: datetime | None,
        inclusive_upper: bool,
    ) -> None:
        upper_end = (
            upper if inclusive_upper else upper - timedelta(microseconds=1)
        ) if upper is not None else max(bar.bar_end for bar in selected)
        lower = (
            min(bar.bar_end for bar in selected) - timedelta(microseconds=1)
            if has_sentinel
            else datetime.min.replace(tzinfo=UTC)
        )
        try:
            listed = (
                self.catalog.contract_fact(key.symbol, key.series_or_contract).listed_date
                if key.kind is DatasetKind.CONTRACT else min(bar.trading_day for bar in selected)
            )
            window_start = (
                min(bar.bar_end for bar in selected) - timedelta(microseconds=1)
                if has_sentinel else
                datetime.combine(listed - timedelta(days=7), time.min, SHANGHAI).astimezone(UTC)
            )
            days = tuple(
                day for day, _ in self.catalog.session_windows_overlapping_window(
                    key.symbol,
                    window_start,
                    upper_end,
                    earliest=(min(bar.trading_day for bar in selected) if has_sentinel else listed),
                )
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        self._validate_actual_endpoints(
            key.symbol,
            key.frequency,
            {day: key.series_or_contract for day in days},
            selected,
            lower,
            upper_end,
            missing_code="DATASET_OR_PARTITION_MISSING",
            dataset_kind=key.kind,
        )

    def _validate_partition_coverage_gap(
        self,
        symbol: str,
        older: CatalogPartition,
        newer: CatalogPartition,
    ) -> None:
        """用完整 TradingCalendar 事实判断相邻 coverage 之间是否漏过交易日。"""
        older_end = older.source_coverage_end or older.coverage_end
        newer_start = newer.source_coverage_start or newer.coverage_start
        if older_end is None or newer_start is None:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        start_day = _local_date(older_end)
        end_day = _local_date(newer_start)
        if end_day <= start_day + timedelta(days=1):
            return
        expected_days = tuple(
            start_day + timedelta(days=offset)
            for offset in range(1, (end_day - start_day).days)
        )
        try:
            calendar_days = self.catalog.calendar_days(
                symbol,
                expected_days[0],
                expected_days[-1],
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if tuple(day for day, _ in calendar_days) != expected_days:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING", reason="TRADING_CALENDAR_MISSING")
        if any(is_trading_day for _, is_trading_day in calendar_days):
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")

    def _actual_dominant_page(
        self,
        request: SeriesPageQuery,
        *,
        published_prefix: bool = False,
    ) -> MarketSeriesPageResult:
        # ``before`` limits physical bars by ``bar_end`` below.  It must not
        # limit map facts by natural date because a Friday-night bar belongs
        # to the next trading day (for example Monday) and needs that owner.
        mappings = self.catalog.main_map_before(request.symbol, None)
        mapping_by_day = {item.trade_date: item for item in mappings}
        partitions = self.catalog.contract_partitions_before(
            request.symbol,
            request.frequency,
            request.before,
        )
        if not partitions:
            if request.frequency is BarFrequency.W1:
                raise MarketDataError("ACTUAL_DOMINANT_WEEKLY_DATASET_ABSENT")
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        # Scope calendar reuse to this page read; later reads must see new facts.
        weekly_calendar: dict[date, tuple[date, ...]] = {}
        selected: list[CanonicalBar] = []
        available_contract_days: set[tuple[str, date]] = set()
        for _, month_partitions in _partition_month_groups(partitions):
            candidates: list[CanonicalBar | SourceQualityFact] = []
            month_events: list[tuple[CatalogPartition, CanonicalBar | SourceQualityFact]] = []
            for partition in month_partitions:
                bars, unavailable = (
                    self._partition_quality(partition)
                    if request.frequency is BarFrequency.D1
                    else (self._partition_bars(partition), ())
                )
                month_events.extend(
                    (partition, event)
                    for event in (*bars, *unavailable)
                    if request.before is None or event.bar_end < request.before
                )
            if request.frequency is BarFrequency.W1:
                self._prime_weekly_calendar(
                    request.symbol,
                    (event.trading_day for _, event in month_events),
                    weekly_calendar,
                )
            for partition, event in month_events:
                available_contract_days.add(
                    (partition.dataset.series_or_contract, event.trading_day)
                )
                owner = (
                    self._page_weekly_owner(
                        request.symbol,
                        event.trading_day,
                        mapping_by_day,
                        weekly_calendar,
                        strict_mapping=False,
                    )
                    if request.frequency is BarFrequency.W1
                    else mapping_by_day.get(event.trading_day)
                )
                if (
                    owner is not None
                    and owner.contract == partition.dataset.series_or_contract
                ):
                    candidates.append(event)
            for event in sorted(candidates, key=lambda item: item.bar_end, reverse=True):
                if len(selected) == request.limit:
                    return self._actual_page_result(
                        request,
                        selected,
                        mapping_by_day,
                        available_contract_days,
                        weekly_calendar,
                        published_prefix=published_prefix,
                        has_more_before=True,
                    )
                if isinstance(event, SourceQualityFact):
                    raise MarketDataError(
                        "PRICE_UNAVAILABLE"
                        if isinstance(event, PriceUnavailableFact)
                        else "SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED"
                    )
                if any(item.bar_end == event.bar_end for item in selected):
                    raise MarketDataError("BAR_IDENTITY_CONFLICT")
                selected.append(event)
        if not selected:
            available_days = {day for _, day in available_contract_days}
            if any(day not in mapping_by_day for day in available_days):
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            if request.frequency is BarFrequency.W1:
                for day in available_days:
                    self._page_weekly_owner(
                        request.symbol,
                        day,
                        mapping_by_day,
                        weekly_calendar,
                    )
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        return self._actual_page_result(
            request,
            selected,
            mapping_by_day,
            available_contract_days,
            weekly_calendar,
            published_prefix=published_prefix,
            has_more_before=False,
        )

    def _actual_page_result(
        self,
        request: SeriesPageQuery,
        selected: list[CanonicalBar],
        mapping_by_day: dict[date, MainMapFact],
        available_contract_days: set[tuple[str, date]],
        weekly_calendar: dict[date, tuple[date, ...]],
        *,
        published_prefix: bool = False,
        has_more_before: bool | None = None,
    ) -> MarketSeriesPageResult:
        page = selected[: request.limit]
        has_more = len(selected) > request.limit if has_more_before is None else has_more_before
        self._validate_actual_page_boundary(
            request,
            page,
            mapping_by_day,
            available_contract_days,
            weekly_calendar,
        )
        try:
            missing_days = self.catalog.missing_main_map_days(
                request.symbol,
                min(bar.trading_day for bar in page),
                max(bar.trading_day for bar in page),
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if missing_days:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        if request.frequency is BarFrequency.W1:
            upper_day = (
                request.before.astimezone(SHANGHAI).date()
                if request.before is not None else max(bar.trading_day for bar in selected)
            )
            try:
                days = self.catalog.trading_days(
                    request.symbol, min(bar.trading_day for bar in selected), upper_day
                )
            except CatalogError as exc:
                raise MarketDataError(exc.code) from exc
            owners: dict[date, str] = {}
            for day in days:
                if request.before is not None and day == upper_day:
                    try:
                        windows = session_windows_for_trading_day(
                            self.catalog.session,
                            exchange=self.catalog.exchange_for_symbol(request.symbol),
                            symbol=request.symbol,
                            trading_day=day,
                        )
                    except (CatalogError, SessionClockError) as exc:
                        raise MarketDataError(exc.code) from exc
                    if not windows or windows[-1].end >= request.before:
                        continue
                owner = self._page_weekly_owner(
                    request.symbol, day, mapping_by_day, weekly_calendar
                )
                if owner is not None:
                    owners[day] = owner.contract
            self._validate_actual_endpoints(
                request.symbol, request.frequency, owners, selected,
                min(bar.bar_end for bar in selected) - timedelta(microseconds=1),
                request.before - timedelta(microseconds=1)
                if request.before is not None else max(bar.bar_end for bar in selected),
            )
        else:
            upper_end = (
                request.before - timedelta(microseconds=1)
                if request.before is not None and not published_prefix
                else max(bar.bar_end for bar in selected)
            )
            try:
                days = self.catalog.trading_days_overlapping_window(
                    request.symbol,
                    min(bar.bar_end for bar in selected) - timedelta(microseconds=1),
                    upper_end,
                )
            except CatalogError as exc:
                raise MarketDataError(exc.code) from exc
            if any(day not in mapping_by_day for day in days):
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            self._validate_actual_endpoints(
                request.symbol,
                request.frequency,
                {
                    day: mapping_by_day[day].contract
                    for day in days
                },
                selected,
                (
                    min(bar.bar_end for bar in selected) - timedelta(microseconds=1)
                    if has_more
                    else datetime.min.replace(tzinfo=UTC)
                ),
                upper_end,
            )
        segments = _segments(
            tuple(mapping_by_day[bar.trading_day] for bar in reversed(page))
        )
        return self._page_result(
            request,
            selected,
            segments,
            has_more_before=has_more,
        )

    def _validate_actual_page_boundary(
        self,
        request: SeriesPageQuery,
        page: list[CanonicalBar],
        mapping_by_day: dict[date, MainMapFact],
        available_contract_days: set[tuple[str, date]],
        weekly_calendar: dict[date, tuple[date, ...]],
    ) -> None:
        """在决定分页边界前验证映射日没有被静默跳过。"""
        page_start = min(bar.trading_day for bar in page)
        cursor_day = (
            request.before.astimezone(SHANGHAI).date()
            if request.before is not None
            else None
        )
        relevant_days = {
            trading_day
            for _, trading_day in available_contract_days
            if trading_day >= page_start
        }
        if not relevant_days:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        end_day = max(relevant_days)
        try:
            expected_days = self.catalog.trading_days(
                request.symbol, page_start, end_day
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if not expected_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        if request.frequency is BarFrequency.W1:
            self._prime_weekly_calendar(
                request.symbol, expected_days, weekly_calendar
            )
        for day in expected_days:
            if cursor_day is not None and day == cursor_day:
                continue
            owner = mapping_by_day.get(day)
            if owner is None:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            if request.frequency is BarFrequency.W1:
                weekly_owner = self._page_weekly_owner(
                    request.symbol,
                    day,
                    mapping_by_day,
                    weekly_calendar,
                )
                if weekly_owner is None:
                    continue
                if (weekly_owner.contract, day) not in available_contract_days:
                    raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
            elif (
                owner.contract,
                day,
            ) not in available_contract_days:
                raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")

    def _prime_weekly_calendar(
        self,
        symbol: str,
        days: Iterable[date],
        weekly_calendar: dict[date, tuple[date, ...]],
    ) -> None:
        """Read missing ISO weeks together, scoped to one page request."""
        mondays = {
            day - timedelta(days=day.isoweekday() - 1) for day in days
        } - weekly_calendar.keys()
        if not mondays:
            return
        try:
            trading_days = self.catalog.trading_days(
                symbol,
                min(mondays),
                max(mondays) + timedelta(days=6),
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        grouped: dict[date, list[date]] = {monday: [] for monday in mondays}
        for day in trading_days:
            monday = day - timedelta(days=day.isoweekday() - 1)
            if monday in grouped:
                grouped[monday].append(day)
        weekly_calendar.update(
            (monday, tuple(week_days))
            for monday, week_days in grouped.items()
        )

    def _page_weekly_owner(
        self,
        symbol: str,
        trading_day: date,
        mapping_by_day: dict[date, MainMapFact],
        weekly_calendar: dict[date, tuple[date, ...]],
        *,
        strict_mapping: bool = True,
    ) -> MainMapFact | None:
        """仅将完整 ISO 交易周最后交易日的正式 owner 用于周线拼接。"""
        monday = trading_day - timedelta(days=trading_day.isoweekday() - 1)
        try:
            if monday not in weekly_calendar:
                weekly_calendar[monday] = self.catalog.trading_days(
                    symbol, monday, monday + timedelta(days=6)
                )
            week_days = weekly_calendar[monday]
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if not week_days or week_days[-1] != trading_day:
            return None
        if any(day not in mapping_by_day for day in week_days):
            if strict_mapping:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            return None
        return mapping_by_day.get(trading_day)

    def _partition_bars(self, partition: CatalogPartition) -> tuple[CanonicalBar, ...]:
        """读取并验证单一 Catalog 分区，复用正常查询的完整性边界。"""
        if partition.source_quality:
            raise MarketDataError("PRICE_UNAVAILABLE")
        try:
            values = self.store.read_catalog_partition(partition)
        except StorageError as exc:
            raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
        if any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(values, values[1:])
        ):
            raise MarketDataError("BAR_IDENTITY_CONFLICT")
        return values

    def _partition_quality(
        self, partition: CatalogPartition,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceQualityFact, ...]]:
        """Read one validated D1 partition without collapsing source facts into bars."""
        try:
            values, unavailable = self.store.read_catalog_partition_quality(partition)
        except StorageError as exc:
            raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
        if any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(values, values[1:])
        ):
            raise MarketDataError("BAR_IDENTITY_CONFLICT")
        return values, unavailable

    def _actual_dominant(self, request: SeriesQuery) -> MarketSeriesResult:
        """按交易日主力映射拼接多合约物理数据，得到逻辑连续序列。

        关键约束：
        - 窗口内每个交易日须有 ``MainContractMap`` 行（与交易日历对齐）；
        - 周线仅使用「完整交易周」最后交易日的映射；
        - 映射指向的合约分区缺失或交易日缺 bar 时整体失败，不部分返回。
        """
        try:
            session_windows = self.catalog.session_windows_overlapping_window(
                request.symbol,
                request.start,
                request.end,
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        trading_days = tuple(day for day, _ in session_windows)
        if not trading_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        mappings = self.catalog.main_map(
            request.symbol,
            trading_days[0],
            trading_days[-1],
        )
        mapping_by_day = {row.trade_date: row for row in mappings}
        missing_days = tuple(day for day in trading_days if day not in mapping_by_day)
        if missing_days:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        selected_mappings = tuple(mapping_by_day[day] for day in trading_days)
        if request.frequency is BarFrequency.W1:
            completed_mappings = tuple(
                mapping_by_day[day]
                for day, windows in session_windows
                if max(window.end for window in windows) <= request.end
            )
            selected = self._weekly_mappings(request, completed_mappings)
        else:
            selected = selected_mappings
        segments = _segments(selected)
        bars: list[CanonicalBar] = []
        contract_by_day = {row.trade_date: row.contract for row in selected}
        # 按出现过的合约去重读取，避免同一合约分区重复 IO
        for contract in dict.fromkeys(row.contract for row in selected):
            key = DatasetKey(
                DatasetKind.CONTRACT,
                request.symbol,
                contract,
                request.frequency,
            )
            try:
                # 拼接场景不要求单月分区覆盖整个查询窗口，只要求映射日有 bar
                contract_bars, _ = self._read_physical(
                    key,
                    request,
                    require_window_coverage=False,
                )
            except MarketDataError as exc:
                if exc.code == "DATASET_OR_PARTITION_MISSING":
                    raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING") from exc
                raise
            # 仅保留「该交易日映射到本合约」的 bar，实现 actual_dominant 语义
            bars.extend(
                bar
                for bar in contract_bars
                if contract_by_day.get(bar.trading_day) == contract
            )
        bars.sort(key=lambda item: item.bar_end)
        if not bars:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        # 每个被选中的映射日都必须有对应 bar，防止静默缺口
        if {item.trade_date for item in selected} - {bar.trading_day for bar in bars}:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        if request.frequency is not BarFrequency.W1:
            self._validate_actual_endpoints(
                request.symbol,
                request.frequency,
                contract_by_day,
                bars,
                request.start,
                request.end,
            )
        return self._result(request, tuple(bars), segments)

    def _validate_actual_endpoints(
        self,
        symbol: str,
        frequency: BarFrequency,
        contract_by_day: dict[date, str],
        bars: Iterable[CanonicalBar],
        start: datetime,
        end: datetime,
        *,
        missing_code: str = "MAPPED_CONTRACT_DATASET_MISSING",
        dataset_kind: DatasetKind = DatasetKind.CONTRACT,
    ) -> None:
        """Prove every endpoint in the selected rank-1 physical windows."""
        source = DatabaseCoverageSource(
            self.catalog.session,
            PROJECT_ROOT / "data/universe/product_window_starts.csv",
        )
        expected: list[tuple[datetime, date]] = []
        for contract in dict.fromkeys(contract_by_day.values()):
            days = tuple(
                day for day, owner in contract_by_day.items() if owner == contract
            )
            key = DatasetKey(dataset_kind, symbol, contract, frequency)
            try:
                expected.extend(
                    (bar_end, day)
                    for bar_end, day in source.expected_bar_end_pairs_for_trading_days(
                        key, days
                    )
                    if start < bar_end <= end
                )
            except InfrastructureError as exc:
                raise MarketDataError(exc.code) from exc
        actual = tuple(sorted((bar.bar_end, bar.trading_day) for bar in bars))
        if actual != tuple(sorted(expected)):
            if len(set(actual)) != len(actual):
                raise MarketDataError(missing_code, reason="REPLAY_ORDER_INVALID")
            if set(actual) - set(expected):
                raise MarketDataError(missing_code, reason="REPLAY_ENDPOINTS_EXTRA")
            raise MarketDataError(missing_code)

    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]:
        """返回每个品种最近一条主力映射（按 trade_date 降序取首条）。"""
        retired = load_retired_products()
        taxonomy = load_product_taxonomy()
        mappings = self.catalog.session.scalars(
            select(MainContractMap).order_by(
                MainContractMap.symbol,
                MainContractMap.trade_date.desc(),
            )
        )
        latest: dict[str, MainContractMap] = {}
        for row in mappings:
            if is_retired(row.symbol, retired=retired) or row.symbol not in taxonomy:
                continue
            latest.setdefault(row.symbol, row)
        instruments = {
            row.symbol: row for row in self.catalog.session.scalars(select(Instrument))
        }
        return tuple(
            DominantContractSummary(
                symbol=symbol,
                product_name=taxonomy[symbol].name,
                sector=taxonomy[symbol].sector,
                exchange=(
                    instruments[symbol].exchange_code if symbol in instruments else ""
                ),
                actual_contract=row.contract_code,
                dominant_mapping_date=row.trade_date,
            )
            for symbol, row in sorted(latest.items())
        )

    def latest_dominant_segment(self, symbol: str) -> DominantContractSegmentSummary:
        """返回最新连续 rank-1 合约区段；日历或映射缺口时整体失败。"""
        mappings = self.catalog.main_map_before(symbol, None)
        if not mappings:
            raise MarketDataError("DOMINANT_CONTEXT_MISSING")

        latest = mappings[-1]
        current_start_index = len(mappings) - 1
        while (
            current_start_index > 0
            and mappings[current_start_index - 1].contract == latest.contract
        ):
            current_start_index -= 1

        previous_mapping = (
            mappings[current_start_index - 1] if current_start_index > 0 else None
        )
        validation_start = (
            previous_mapping.trade_date
            if previous_mapping is not None
            else mappings[0].trade_date
        )
        try:
            trading_days = self.catalog.trading_days(
                latest.symbol,
                validation_start,
                latest.trade_date,
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if not trading_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")

        mapping_by_day = {
            item.trade_date: item
            for item in mappings
            if validation_start <= item.trade_date <= latest.trade_date
        }
        if any(day not in mapping_by_day for day in trading_days):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

        segment_days = tuple(
            day
            for day in trading_days
            if previous_mapping is None or day > previous_mapping.trade_date
        )
        if not segment_days or any(
            mapping_by_day[day].contract != latest.contract for day in segment_days
        ):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

        return DominantContractSegmentSummary(
            symbol=latest.symbol,
            contract=latest.contract,
            start_trading_day=segment_days[0],
            end_trading_day=latest.trade_date,
        )

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary:
        """返回包含指定交易日的连续 rank-1 区段并验证日历/映射连续性。"""
        normalized_symbol = symbol.strip().lower()
        try:
            assert_not_retired(normalized_symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        segments = self._authoritative_rank1_segments(
            normalized_symbol,
            trading_day,
            trading_day,
            empty_code="DOMINANT_CONTEXT_MISSING",
        )
        if len(segments) != 1:
            raise MarketDataError("MAIN_CONTRACT_MAP_CONFLICT")
        segment = segments[0]
        return DominantContractSegmentSummary(
            symbol=normalized_symbol,
            contract=segment.contract,
            start_trading_day=segment.start_trading_day,
            end_trading_day=segment.end_trading_day,
        )

    def actual_dominant_segments(
        self,
        symbol: str,
        since: date,
        through: date,
    ) -> tuple[ResolvedContractSegment, ...]:
        """Return full rank-1 segments intersecting a trading-day window."""
        normalized_symbol = symbol.strip().lower()
        try:
            assert_not_retired(normalized_symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        if type(since) is not date or type(through) is not date or since > through:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        return self._authoritative_rank1_segments(
            normalized_symbol,
            since,
            through,
            empty_code="MAIN_CONTRACT_MAP_MISSING",
        )

    def _authoritative_rank1_segments(
        self,
        symbol: str,
        since: date,
        through: date,
        *,
        empty_code: str,
    ) -> tuple[ResolvedContractSegment, ...]:
        """Return full rank-1 segments intersecting an exact calendar window."""
        mappings = self.catalog.main_map_before(symbol, None)
        if not mappings:
            raise MarketDataError(empty_code)

        requested_calendar = self._exact_calendar(symbol, since, through)
        requested_trading_days = tuple(
            day for day, is_trading_day in requested_calendar if is_trading_day
        )
        if not requested_trading_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")

        requested_day_set = set(requested_trading_days)
        target_indexes = tuple(
            index
            for index, mapping in enumerate(mappings)
            if mapping.trade_date in requested_day_set
        )
        target_days = tuple(mappings[index].trade_date for index in target_indexes)
        if len(set(target_days)) != len(target_days):
            raise MarketDataError("MAIN_CONTRACT_MAP_CONFLICT")
        if set(target_days) != requested_day_set:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        if any(
            since <= mapping.trade_date <= through
            and mapping.trade_date not in requested_day_set
            for mapping in mappings
        ):
            raise MarketDataError("MAIN_CONTRACT_MAP_CONFLICT")

        start_index = target_indexes[0]
        while (
            start_index > 0
            and mappings[start_index - 1].contract == mappings[start_index].contract
        ):
            start_index -= 1
        end_index = target_indexes[-1]
        while (
            end_index + 1 < len(mappings)
            and mappings[end_index + 1].contract == mappings[end_index].contract
        ):
            end_index += 1

        validation_start = (
            mappings[start_index - 1].trade_date
            if start_index > 0
            else mappings[start_index].trade_date
        )
        validation_end = (
            mappings[end_index + 1].trade_date
            if end_index + 1 < len(mappings)
            else mappings[end_index].trade_date
        )
        validation_calendar = self._exact_calendar(
            symbol,
            validation_start,
            validation_end,
        )
        validation_trading_days = tuple(
            day for day, is_trading_day in validation_calendar if is_trading_day
        )
        contextual_mappings = tuple(
            mapping
            for mapping in mappings
            if validation_start <= mapping.trade_date <= validation_end
        )
        mapping_by_day = {
            mapping.trade_date: mapping for mapping in contextual_mappings
        }
        if len(mapping_by_day) != len(contextual_mappings) or any(
            mapping.symbol != symbol for mapping in contextual_mappings
        ):
            raise MarketDataError("MAIN_CONTRACT_MAP_CONFLICT")
        if any(day not in mapping_by_day for day in validation_trading_days):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        if any(day not in validation_trading_days for day in mapping_by_day):
            raise MarketDataError("MAIN_CONTRACT_MAP_CONFLICT")

        segment_mappings = mappings[start_index : end_index + 1]
        segment_days = tuple(
            day
            for day in validation_trading_days
            if segment_mappings[0].trade_date <= day <= segment_mappings[-1].trade_date
        )
        if tuple(mapping.trade_date for mapping in segment_mappings) != segment_days:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        return _segments(segment_mappings)

    def _exact_calendar(
        self,
        symbol: str,
        since: date,
        through: date,
    ) -> tuple[tuple[date, bool], ...]:
        try:
            calendar = self.catalog.calendar_days(symbol, since, through)
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        expected_days = tuple(
            since + timedelta(days=offset)
            for offset in range((through - since).days + 1)
        )
        if tuple(day for day, _ in calendar) != expected_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        return calendar

    def contract_bars_for_trading_day(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency,
        trading_day: date,
    ) -> tuple[CanonicalBar, ...]:
        """只从真实合约 Dataset 读取指定正式交易日的 confirmed bars。"""
        try:
            assert_not_retired(symbol)
        except ProductRetiredError as exc:
            raise MarketDataError("PRODUCT_RETIRED") from exc
        try:
            calendar = self.catalog.calendar_days(symbol, trading_day, trading_day)
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if tuple(day for day, _ in calendar) != (trading_day,):
            raise MarketDataError("TRADING_CALENDAR_MISSING")
        if not calendar[0][1]:
            return ()

        try:
            exchange = self.catalog.exchange_for_symbol(symbol)
            windows = session_windows_for_trading_day(
                self.catalog.session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_day,
            )
        except (CatalogError, SessionClockError) as exc:
            raise MarketDataError(exc.code) from exc
        if not windows:
            raise MarketDataError("TRADING_SESSION_MISSING")
        key = DatasetKey(
            DatasetKind.CONTRACT,
            symbol,
            contract,
            frequency,
        )
        try:
            partitions = self.catalog.partitions(
                key,
                min(window.start for window in windows),
                max(window.end for window in windows),
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if not partitions:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")

        bars = sorted(
            (
                bar
                for partition in partitions
                for bar in self._partition_bars(partition)
                if bar.trading_day == trading_day
            ),
            key=lambda item: item.bar_end,
        )
        if not bars:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        if any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:])
        ):
            raise MarketDataError("BAR_IDENTITY_CONFLICT")
        return tuple(bars)

    def _weekly_mappings(
        self,
        request: SeriesQuery,
        mappings: tuple[MainMapFact, ...],
    ) -> tuple[MainMapFact, ...]:
        """周线 actual_dominant：仅保留窗口内「完整 ISO 交易周」的最后交易日映射。

        不完整周（节假日导致周内最后一个交易日不是周五对应日）整周跳过；
        若窗口内无任何完整周，抛出 ``COMPLETE_WEEK_MISSING``。
        """
        # ``mappings`` already represents the authoritative Session-overlapping
        # trading days resolved by ``_actual_dominant``.  Re-expanding the raw
        # local-date window can pull in the preceding Friday when ``start`` is
        # that Friday's night-session boundary, even though that session belongs
        # to Monday and the Friday owner is outside the query.
        request_days = tuple(row.trade_date for row in mappings)
        grouped: dict[tuple[int, int], list[date]] = {}
        for day in request_days:
            iso = day.isocalendar()
            grouped.setdefault((iso.year, iso.week), []).append(day)
        mapping_by_day = {row.trade_date: row for row in mappings}
        selected: list[MainMapFact] = []
        for days in grouped.values():
            candidate_day = days[-1]
            monday = candidate_day - timedelta(days=candidate_day.isoweekday() - 1)
            full_week = self.catalog.trading_days(
                request.symbol,
                monday,
                monday + timedelta(days=6),
            )
            # 该周必须在交易日历上连续填满至 candidate_day，否则不算完整周
            if not full_week or full_week[-1] != candidate_day:
                continue
            owner = mapping_by_day.get(candidate_day)
            if owner is None:
                raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
            selected.append(owner)
        if not selected:
            raise MarketDataError("COMPLETE_WEEK_MISSING")
        return tuple(selected)

    def _read_physical(
        self,
        key: DatasetKey,
        request: SeriesQuery,
        *,
        require_window_coverage: bool = True,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[CatalogPartition, ...]]:
        """从 Catalog 解析月分区并读取 Parquet，过滤到 ``(start, end]`` 窗口。

        ``require_window_coverage=True`` 时要求：
        - 首尾分区间月份无空洞；
        - 分区 coverage 包络整个查询窗口。
        并校验每分区 ``row_count`` 与文件行数一致、bar_end 严格递增。
        """
        partitions = self.catalog.partitions(key, request.start, request.end)
        if not partitions:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        if any(partition.source_quality for partition in partitions):
            raise MarketDataError("PRICE_UNAVAILABLE")
        partition_months = {
            (partition.year, partition.month) for partition in partitions
        }
        if require_window_coverage:
            # 命中分区所跨月份必须连续，防止中间月 Catalog 缺失被忽略
            if partition_months != _months_between(
                min(partition_months),
                max(partition_months),
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
            if (
                min((partition.source_coverage_start or partition.coverage_start) for partition in partitions)
                > request.start
                or max((partition.source_coverage_end or partition.coverage_end) for partition in partitions) < request.end
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        bars: list[CanonicalBar] = []
        for partition in partitions:
            try:
                values = self.store.read_catalog_partition(partition)
            except StorageError as exc:
                raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
            bars.extend(
                bar for bar in values if request.start < bar.bar_end <= request.end
            )
        bars.sort(key=lambda item: item.bar_end)
        if not bars:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        if any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:])
        ):
            raise MarketDataError("BAR_IDENTITY_CONFLICT")
        return tuple(bars), partitions

    def _result(
        self,
        request: SeriesQuery,
        bars: tuple[CanonicalBar, ...],
        segments: tuple[ResolvedContractSegment, ...],
    ) -> MarketSeriesResult:
        """组装统一结果结构，写入请求身份指纹与实际 coverage。"""
        identity = {
            "series_kind": request.series_kind.value,
            "symbol": request.symbol,
            "contract": request.contract,
            "frequency": request.frequency.value,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        return MarketSeriesResult(
            request_identity=identity,
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            resolved_contract_segments=segments,
        )

    def _page_result(
        self,
        request: SeriesPageQuery,
        selected_descending: list[CanonicalBar],
        segments: tuple[ResolvedContractSegment, ...],
        *,
        cursor_mode: SeriesPageCursorMode = SeriesPageCursorMode.EXCLUSIVE,
        has_more_before: bool | None = None,
    ) -> MarketSeriesPageResult:
        """将 newest-first 候选转换为稳定的 ascending 页面响应。"""
        has_more = (
            len(selected_descending) > request.limit
            if has_more_before is None else has_more_before
        )
        page = tuple(reversed(selected_descending[: request.limit]))
        identity = {
            "series_kind": request.series_kind.value,
            "symbol": request.symbol,
            "contract": request.contract,
            "frequency": request.frequency.value,
            "before": request.before.isoformat() if request.before else None,
            "limit": request.limit,
        }
        return MarketSeriesPageResult(
            request_identity=identity,
            bars=page,
            canonical_coverage=(page[0].bar_end, page[-1].bar_end) if page else None,
            has_more_before=has_more,
            next_before=page[0].bar_end if has_more else None,
            resolved_contract_segments=segments,
            cursor_mode=cursor_mode,
        )


def _segments(mappings: tuple[MainMapFact, ...]) -> tuple[ResolvedContractSegment, ...]:
    """将按日排序的主力映射合并为合约不变的最长连续段。"""
    if not mappings:
        return ()
    result: list[ResolvedContractSegment] = []
    contract = mappings[0].contract
    start = mappings[0].trade_date
    end = start
    for row in mappings[1:]:
        if row.contract != contract:
            result.append(ResolvedContractSegment(contract, start, end))
            contract = row.contract
            start = row.trade_date
        end = row.trade_date
    result.append(ResolvedContractSegment(contract, start, end))
    return tuple(result)


def _partition_month_groups(
    partitions: tuple[CatalogPartition, ...],
) -> tuple[tuple[tuple[int, int], tuple[CatalogPartition, ...]], ...]:
    """保留 Catalog 的 reverse 月序，并把同月各合约分区作为一个时间层处理。"""
    groups: dict[tuple[int, int], list[CatalogPartition]] = {}
    for partition in partitions:
        groups.setdefault((partition.year, partition.month), []).append(partition)
    return tuple((month, tuple(values)) for month, values in groups.items())


def _local_date(value: datetime) -> date:
    """将带时区时刻转为上海时区交易日（与 RQData/国内期货日历对齐）。"""
    return value.astimezone(SHANGHAI).date()


def _months_between(
    start: tuple[int, int],
    end: tuple[int, int],
) -> set[tuple[int, int]]:
    """生成 ``(year, month)`` 闭区间内的全部月份集合，用于分区连续性检查。"""
    cursor = start
    end_month = end
    result: set[tuple[int, int]] = set()
    while cursor <= end_month:
        result.add(cursor)
        year, month = cursor
        cursor = (year + 1, 1) if month == 12 else (year, month + 1)
    return result
