"""市场数据查询服务（数据核心 V2 唯一历史读入口）。

``MarketDataService`` 是消费者（Market API、CLI 等）访问 canonical 数据的**唯一门面**：
- 物理序列（``continuous`` / ``contract``）：经八表 Catalog 定位月分区，再读 Parquet；
- 逻辑序列 ``actual_dominant``：按 ``MainContractMap`` 逐日映射到具体合约数据集后拼接，
  周线另按「完整交易周」规则选取映射日。

本模块强制执行分区连续性、行数一致、bar 严格递增等 fail-closed 校验；
映射或物理数据缺失时不回退、不插值，直接 ``MarketDataError``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.market_data.catalog import (
    CatalogError,
    CatalogPartition,
    MainMapFact,
    MarketCatalog,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
    SeriesQuery,
)
from app.market_data.product_retirement import (
    ProductRetiredError,
    assert_not_retired,
    is_retired,
    load_retired_products,
)
from app.market_data.storage import CanonicalMonthlyStore, StorageError
from app.models import Instrument, MainContractMap, MarketDataset, MarketPartition


SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketDataError(RuntimeError):
    """服务层业务失败：以稳定 ``code`` 字符串标识，不含存储内部细节。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DatasetCoverageSummary:
    """单个物理数据集在 Catalog 中的聚合覆盖摘要（供运维/审计列表）。"""

    kind: str
    symbol: str
    series_or_contract: str
    frequency: str
    start: datetime
    end: datetime
    row_count: int
    partition_count: int


@dataclass(frozen=True, slots=True)
class DominantContractSummary:
    """各品种最新主力映射一行摘要（映射日 + 实际合约代码）。"""

    symbol: str
    product_name: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


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
        return self._result(
            request,
            bars,
            (),
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
        return self._page_result(
            request,
            self._physical_page_bars(request.physical_key, request),
            (),
        )

    def _physical_page_bars(
        self,
        key: DatasetKey,
        request: SeriesPageQuery,
    ) -> list[CanonicalBar]:
        partitions = self.catalog.partitions_before(key, request.before)
        if not partitions:
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        selected: list[CanonicalBar] = []
        previous_end: datetime | None = None
        newer_partition: CatalogPartition | None = None
        for partition in partitions:
            if (
                newer_partition is None
                and request.before is not None
                and partition.coverage_end < request.before
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
            if (
                newer_partition is not None
                and len(
                    _months_between(
                        (partition.year, partition.month),
                        (newer_partition.year, newer_partition.month),
                    )
                ) > 2
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
            if newer_partition is not None:
                self._validate_partition_coverage_gap(
                    key.symbol,
                    partition,
                    newer_partition,
                )
            values = self._partition_bars(partition)
            for bar in reversed(values):
                if request.before is not None and bar.bar_end >= request.before:
                    continue
                if previous_end is not None and bar.bar_end >= previous_end:
                    raise MarketDataError("BAR_IDENTITY_CONFLICT")
                selected.append(bar)
                previous_end = bar.bar_end
                if len(selected) == request.limit + 1:
                    return selected
            newer_partition = partition
        if not selected:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        return selected

    def _validate_partition_coverage_gap(
        self,
        symbol: str,
        older: CatalogPartition,
        newer: CatalogPartition,
    ) -> None:
        """用完整 TradingCalendar 事实判断相邻 coverage 之间是否漏过交易日。"""
        start_day = _local_date(older.coverage_end)
        end_day = _local_date(newer.coverage_start)
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
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        if any(is_trading_day for _, is_trading_day in calendar_days):
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")

    def _actual_dominant_page(
        self,
        request: SeriesPageQuery,
    ) -> MarketSeriesPageResult:
        mappings = self.catalog.main_map_before(request.symbol, request.before)
        mapping_by_day = {item.trade_date: item for item in mappings}
        partitions = self.catalog.contract_partitions_before(
            request.symbol,
            request.frequency,
            request.before,
        )
        if not partitions:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        selected: list[CanonicalBar] = []
        available_contract_days: set[tuple[str, date]] = set()
        for _, month_partitions in _partition_month_groups(partitions):
            candidates: list[CanonicalBar] = []
            for partition in month_partitions:
                for bar in self._partition_bars(partition):
                    if request.before is not None and bar.bar_end >= request.before:
                        continue
                    available_contract_days.add(
                        (partition.dataset.series_or_contract, bar.trading_day)
                    )
                    owner = (
                        self._page_weekly_owner(
                            request.symbol,
                            bar.trading_day,
                            mapping_by_day,
                            strict_mapping=False,
                        )
                        if request.frequency is BarFrequency.W1
                        else mapping_by_day.get(bar.trading_day)
                    )
                    if (
                        owner is not None
                        and owner.contract == partition.dataset.series_or_contract
                    ):
                        candidates.append(bar)
            for bar in sorted(candidates, key=lambda item: item.bar_end, reverse=True):
                if any(item.bar_end == bar.bar_end for item in selected):
                    raise MarketDataError("BAR_IDENTITY_CONFLICT")
                selected.append(bar)
                if len(selected) == request.limit + 1:
                    return self._actual_page_result(
                        request,
                        selected,
                        mapping_by_day,
                        available_contract_days,
                    )
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
                    )
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        return self._actual_page_result(
            request,
            selected,
            mapping_by_day,
            available_contract_days,
        )

    def _actual_page_result(
        self,
        request: SeriesPageQuery,
        selected: list[CanonicalBar],
        mapping_by_day: dict[date, MainMapFact],
        available_contract_days: set[tuple[str, date]],
    ) -> MarketSeriesPageResult:
        page = selected[: request.limit]
        self._validate_actual_page_boundary(
            request,
            page,
            mapping_by_day,
            available_contract_days,
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
        segments = _segments(
            tuple(mapping_by_day[bar.trading_day] for bar in reversed(page))
        )
        return self._page_result(request, selected, segments)

    def _validate_actual_page_boundary(
        self,
        request: SeriesPageQuery,
        page: list[CanonicalBar],
        mapping_by_day: dict[date, MainMapFact],
        available_contract_days: set[tuple[str, date]],
    ) -> None:
        """在决定分页边界前验证映射日没有被静默跳过。"""
        page_start = min(bar.trading_day for bar in page)
        cursor_day = (
            request.before.astimezone(SHANGHAI).date()
            if request.before is not None
            else None
        )
        relevant_days = {
            item.trade_date for item in mapping_by_day.values() if item.trade_date >= page_start
        } | {
            trading_day
            for _, trading_day in available_contract_days
            if trading_day >= page_start
        }
        if not relevant_days:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        end_day = max(relevant_days)
        try:
            expected_days = self.catalog.trading_days(request.symbol, page_start, end_day)
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
        if not expected_days:
            raise MarketDataError("TRADING_CALENDAR_MISSING")
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

    def _page_weekly_owner(
        self,
        symbol: str,
        trading_day: date,
        mapping_by_day: dict[date, MainMapFact],
        *,
        strict_mapping: bool = True,
    ) -> MainMapFact | None:
        """仅将完整 ISO 交易周最后交易日的正式 owner 用于周线拼接。"""
        monday = trading_day - timedelta(days=trading_day.isoweekday() - 1)
        try:
            week_days = self.catalog.trading_days(symbol, monday, monday + timedelta(days=6))
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
        try:
            values = self.store.read_month(
                partition.dataset,
                partition.year,
                partition.month,
            )
        except StorageError as exc:
            raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
        if len(values) != partition.row_count:
            raise MarketDataError("PARTITION_INTEGRITY_INVALID")
        if any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(values, values[1:])
        ):
            raise MarketDataError("BAR_IDENTITY_CONFLICT")
        return values

    def _actual_dominant(self, request: SeriesQuery) -> MarketSeriesResult:
        """按交易日主力映射拼接多合约物理数据，得到逻辑连续序列。

        关键约束：
        - 窗口内每个交易日须有 ``MainContractMap`` 行（与交易日历对齐）；
        - 周线仅使用「完整交易周」最后交易日的映射；
        - 映射指向的合约分区缺失或交易日缺 bar 时整体失败，不部分返回。
        """
        try:
            trading_days = self.catalog.trading_days_overlapping_window(
                request.symbol,
                request.start,
                request.end,
            )
        except CatalogError as exc:
            raise MarketDataError(exc.code) from exc
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
            selected = self._weekly_mappings(request, selected_mappings)
        else:
            selected = selected_mappings
        segments = _segments(selected)
        bars: list[CanonicalBar] = []
        mapping_by_day = {row.trade_date: row.contract for row in selected}
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
                if mapping_by_day.get(bar.trading_day) == contract
            )
        bars.sort(key=lambda item: item.bar_end)
        if not bars:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        # 每个被选中的映射日都必须有对应 bar，防止静默缺口
        if {item.trade_date for item in selected} - {bar.trading_day for bar in bars}:
            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")
        return self._result(request, tuple(bars), segments)

    def list_dataset_coverage(
        self,
        symbol: str | None = None,
    ) -> tuple[DatasetCoverageSummary, ...]:
        """列出 Catalog 中已注册数据集的覆盖范围与行数汇总；无分区的数据集跳过。"""
        retired = load_retired_products()
        query = select(MarketDataset)
        if symbol:
            normalized = symbol.strip().lower()
            try:
                assert_not_retired(normalized, retired=retired)
            except ProductRetiredError as exc:
                raise MarketDataError("PRODUCT_RETIRED") from exc
            query = query.where(MarketDataset.symbol == normalized)
        items: list[DatasetCoverageSummary] = []
        for dataset in self.catalog.session.scalars(
            query.order_by(MarketDataset.symbol, MarketDataset.frequency)
        ):
            partitions = tuple(
                self.catalog.session.scalars(
                    select(MarketPartition)
                    .where(MarketPartition.dataset_id == dataset.id)
                    .order_by(MarketPartition.year, MarketPartition.month)
                )
            )
            if dataset.symbol in retired:
                continue
            if not partitions:
                continue
            items.append(
                DatasetCoverageSummary(
                    kind=dataset.kind,
                    symbol=dataset.symbol,
                    series_or_contract=dataset.series_or_contract,
                    frequency=dataset.frequency,
                    start=partitions[0].coverage_start,
                    end=partitions[-1].coverage_end,
                    row_count=sum(item.row_count for item in partitions),
                    partition_count=len(partitions),
                )
            )
        return tuple(items)

    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]:
        """返回每个品种最近一条主力映射（按 trade_date 降序取首条）。"""
        retired = load_retired_products()
        mappings = self.catalog.session.scalars(
            select(MainContractMap).order_by(
                MainContractMap.symbol,
                MainContractMap.trade_date.desc(),
            )
        )
        latest: dict[str, MainContractMap] = {}
        for row in mappings:
            if is_retired(row.symbol, retired=retired):
                continue
            latest.setdefault(row.symbol, row)
        instruments = {
            row.symbol: row for row in self.catalog.session.scalars(select(Instrument))
        }
        return tuple(
            DominantContractSummary(
                symbol=symbol,
                product_name=(
                    instruments[symbol].name
                    if symbol in instruments
                    else symbol.upper()
                ),
                exchange=(
                    instruments[symbol].exchange_code if symbol in instruments else ""
                ),
                actual_contract=row.contract_code,
                dominant_mapping_date=row.trade_date,
            )
            for symbol, row in sorted(latest.items())
        )

    def _weekly_mappings(
        self,
        request: SeriesQuery,
        mappings: tuple[MainMapFact, ...],
    ) -> tuple[MainMapFact, ...]:
        """周线 actual_dominant：仅保留窗口内「完整 ISO 交易周」的最后交易日映射。

        不完整周（节假日导致周内最后一个交易日不是周五对应日）整周跳过；
        若窗口内无任何完整周，抛出 ``COMPLETE_WEEK_MISSING``。
        """
        request_days = self.catalog.trading_days(
            request.symbol,
            _local_date(request.start),
            _local_date(request.end),
        )
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
                min(partition.coverage_start for partition in partitions)
                > request.start
                or max(partition.coverage_end for partition in partitions) < request.end
            ):
                raise MarketDataError("DATASET_OR_PARTITION_MISSING")
        bars: list[CanonicalBar] = []
        for partition in partitions:
            try:
                values = self.store.read_month(key, partition.year, partition.month)
            except StorageError as exc:
                raise MarketDataError("PARTITION_INTEGRITY_INVALID") from exc
            # Catalog 登记行数与物理文件不一致视为分区损坏
            if len(values) != partition.row_count:
                raise MarketDataError("PARTITION_INTEGRITY_INVALID")
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
    ) -> MarketSeriesPageResult:
        """将 newest-first 候选转换为稳定的 ascending 页面响应。"""
        has_more = len(selected_descending) > request.limit
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
    return tuple(
        (month, tuple(values))
        for month, values in groups.items()
    )


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
