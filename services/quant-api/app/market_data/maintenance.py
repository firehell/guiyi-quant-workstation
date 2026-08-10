"""历史 canonical 数据的维护编排层（update / refresh / audit）。

本模块是「写路径」的应用服务，把 Catalog、月分区 Store、Coverage 期望、元数据同步与
RQData 拉取组装成可审计的维护流程。消费者（MarketDataService、Web）只读已发布分区；
任何缺口补齐、分区重写或 derived 聚合都必须经过这里的门禁。

职责边界
--------
HistoricalDataManager
    唯一维护入口：规划目标月分区、区分 direct（RQData 直拉）与 derived（由 1m 聚合）、
    调用 store.publish 完成 staging 六项硬校验与 part.parquet 原子替换，再 register_partition
    并 strict_verify 读回。apply=False 时只返回 planned 窗口，不写库与文件。

CoverageSource（Protocol，实现见 infrastructure.DatabaseCoverageSource）
    从交易所日历、会话模板与品种窗口推导「应有 bar_end」序列；不读 Parquet、不拉行情。
    maintenance 用它判断缺口、会话窗口与 metadata 是否齐备；缺口不得在此层静默填充。

BarSource / MetadataPort（Protocol，RQData 适配在 infrastructure）
    仅在 apply 路径向 RQData 请求 bars 或 metadata snapshot；配额耗尽等边界错误在此归一化，
    由 manager 决定 partial 停止或按 family 隔离失败。

维护 lease
    apply 的 update/refresh 必须先 acquire_maintenance_lock，避免并发写分区与 Catalog 行。
    拿不到锁时 fail-closed 返回 blocked，不降级为无锁写入。

fail-closed
    元数据/会话事实不齐、主力映射缺口、发布校验失败、全局存储错误或 strict 读回不一致
    均中止或隔离；不得用旧分区、跨频回退或静默截断窗口替代。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.market_data.aggregation import AggregationError, aggregate_from_1m
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import (
    DERIVED_FREQUENCIES,
    DIRECT_FREQUENCIES,
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
    SeriesKind,
    SeriesQuery,
)
from app.market_data.product_retirement import assert_products_not_retired
from app.market_data.service import MarketDataService, MarketDataError
from app.market_data.storage import (
    CanonicalMonthlyStore,
    PublishRequest,
    StorageError,
)


class CoverageSource(Protocol):
    """期望 bar 边界与交易日会话的只读来源；实现通常绑定 DB 日历/会话/品种窗口。"""

    def product_start(self, symbol: str) -> date: ...
    def latest_complete_day(self, products: tuple[str, ...]) -> date: ...
    def latest_metadata_day(self, products: tuple[str, ...]) -> date: ...
    def metadata_complete(self, products: tuple[str, ...], through: date) -> bool: ...
    def require_historical_session_facts(
        self, products: tuple[str, ...], through: date
    ) -> None: ...
    def expected_bar_ends(
        self,
        key: DatasetKey,
        year: int,
        month: int,
        start: date,
        end: date,
    ) -> tuple[datetime, ...]: ...
    def expected_bar_ends_for_trading_days(
        self,
        key: DatasetKey,
        trading_days: tuple[date, ...],
    ) -> tuple[datetime, ...]: ...
    def sessions(
        self,
        key: DatasetKey,
        year: int,
        month: int,
        through: date | None = None,
    ): ...


class MetadataPort(Protocol):
    """元数据同步端口：在 coverage 判定不齐时从 provider 拉 snapshot 并落库。"""

    def synchronize(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> date: ...

    def synchronize_current_day(
        self,
        products: tuple[str, ...],
        trading_day: date,
    ) -> date: ...


class BarSource(Protocol):
    """行情拉取端口：按 DatasetKey 与缺失 bar_end 列表返回一批 canonical bars。"""

    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch: ...


@dataclass(frozen=True, slots=True)
class BarBatch:
    """单次 provider 拉取归一化后的 bar 批次。"""

    bars: tuple[CanonicalBar, ...]


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """批量增量更新：多品种、可选 since，through 缺省为最近完整交易日。"""

    products: tuple[str, ...]
    since: date | None
    through: date | None
    apply: bool = False


@dataclass(frozen=True, slots=True)
class RefreshRequest:
    """单品种强制重写窗口：无视现有缺口语义，按 force 规划整月 expected。"""

    symbol: str
    since: date
    through: date
    apply: bool = False


@dataclass(frozen=True, slots=True)
class AuditRequest:
    """只读审计请求：检查主力映射与分区完整性，不触发 provider 与写入。"""

    products: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """审计发现项：编码 + 数据集四元组 + 问题所在年月。"""

    code: str
    category: str
    dataset: tuple[str, str, str, str]
    year: int | None
    month: int | None


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    """维护动作统一结果：供 CLI/API 序列化与运维观测。"""

    action: str
    status: str
    through: date | None
    planned: int
    applied: int
    blocked: int
    failed: int
    provider_requests: int
    stop_reason: str | None = None
    findings: tuple[AuditFinding, ...] = ()
    failures: tuple[Mapping[str, object], ...] = ()
    target_windows: tuple[Mapping[str, object], ...] = ()

    def as_payload(self) -> dict[str, object]:
        """转为 schema_version=1 的 JSON 友好字典。"""
        return {
            "schema_version": 1,
            "action": self.action,
            "status": self.status,
            "through": self.through.isoformat() if self.through else None,
            "planned": self.planned,
            "applied": self.applied,
            "blocked": self.blocked,
            "failed": self.failed,
            "provider_requests": self.provider_requests,
            "stop_reason": self.stop_reason,
            "targets": [dict(item) for item in self.target_windows],
            "finding_count": len(self.findings),
            "findings": [
                {
                    "code": item.code,
                    "category": item.category,
                    "dataset": item.dataset,
                    "year": item.year,
                    "month": item.month,
                }
                for item in self.findings
            ],
            "failures": [dict(item) for item in self.failures],
        }


def _maintenance_locked(action: str, through: date) -> MaintenanceResult:
    """另一维护任务已持有 lease 时的标准 blocked 响应，避免无锁写入。"""
    return MaintenanceResult(
        action=action,
        status="blocked",
        through=through,
        planned=0,
        applied=0,
        blocked=1,
        failed=0,
        provider_requests=0,
        stop_reason="maintenance_locked",
    )


@dataclass(frozen=True, slots=True)
class _Target:
    """单个待处理月分区：期望序列、缺口子集与已有 bar（用于合并发布）。"""

    key: DatasetKey
    year: int
    month: int
    expected: tuple[datetime, ...]
    missing: tuple[datetime, ...]
    existing: tuple[CanonicalBar, ...]
    gap_clear_start: datetime | None = None
    gap_clear_end: datetime | None = None


# 规划顺序：先日/周再 1m，使 derived 聚合能尽快在同事族 1m 补齐后触发。
_FREQUENCY_ORDER = (
    BarFrequency.D1,
    BarFrequency.W1,
    BarFrequency.M1,
    BarFrequency.M5,
    BarFrequency.M15,
    BarFrequency.M30,
    BarFrequency.H1,
)

_AUDIT_METADATA_CATEGORIES = {
    "TRADING_SESSION_MISSING": ("metadata_session", "session"),
    "PREVIOUS_TRADING_DAY_MISSING": ("metadata_session", "session"),
    "TRADING_CALENDAR_MISSING": ("metadata_calendar", "calendar"),
    "COMPLETE_TRADING_DAY_MISSING": ("metadata_calendar", "calendar"),
    "PRODUCT_WINDOW_START_MISSING": ("metadata_window", "window"),
    "INSTRUMENT_EXCHANGE_MISSING": ("metadata_window", "exchange"),
}


def _audit_metadata_finding(exc: Exception, symbol: str) -> AuditFinding | None:
    """将已知只读 metadata 缺口转为 finding；未知异常保持 fail-closed。"""
    code = getattr(exc, "code", None)
    if not isinstance(code, str):
        return None
    classification = _AUDIT_METADATA_CATEGORIES.get(code)
    if classification is None:
        return None
    category, series = classification
    return AuditFinding(code, category, ("metadata", symbol, series, "1d"), None, None)


class HistoricalDataManager:
    """历史 canonical 维护编排器：update / refresh / audit 的唯一应用服务入口。"""

    def __init__(
        self,
        *,
        catalog: MarketCatalog,
        store: CanonicalMonthlyStore,
        coverage: CoverageSource,
        metadata: MetadataPort,
        provider: BarSource,
    ) -> None:
        self.catalog = catalog
        self.store = store
        self.coverage = coverage
        self.metadata = metadata
        self.provider = provider
        # 同进程内已同步过的 (products, through) 不再重复拉 metadata，减少 RQData 调用。
        self._metadata_watermarks: set[tuple[tuple[str, ...], date]] = set()

    def update(self, request: UpdateRequest) -> MaintenanceResult:
        """增量更新：缺省 through 为各品种最近完整交易日；apply 时持锁并先补齐元数据再写分区。"""
        assert_products_not_retired(request.products)
        if request.apply:
            metadata_through = request.through or self.coverage.latest_metadata_day(
                request.products
            )
            # apply 路径必须持 maintenance lease，防止与 refresh/另一 update 并发写分区。
            lease = self.catalog.acquire_maintenance_lock()
            if lease is None:
                return _maintenance_locked("update", metadata_through)
            try:
                watermark = (request.products, metadata_through)
                # 日历/会话/主力映射不齐时先 synchronize；失败则不会进入拉 bar。
                if (
                    watermark not in self._metadata_watermarks
                    and not self.coverage.metadata_complete(request.products, metadata_through)
                ):
                    self.metadata.synchronize(
                        request.products,
                        metadata_through,
                        {symbol: self.coverage.product_start(symbol) for symbol in request.products},
                    )
                    self._metadata_watermarks.add(watermark)
                through = request.through or self.coverage.latest_complete_day(request.products)
                if request.since is not None and request.since > through:
                    raise ValueError("UPDATE_WINDOW_INVALID")
                # 要求每个历史交易日均有 provider 会话事实，禁止用当前 trading_hours 回填旧日。
                self.coverage.require_historical_session_facts(request.products, through)
                # streaming：先 direct 再 derived，1m 补齐后同事族当月 derived 立即聚合。
                return self._execute_streaming(
                    "update",
                    request.products,
                    request.since,
                    through,
                )
            finally:
                lease.release()
        through = request.through or self.coverage.latest_complete_day(request.products)
        if request.since is not None and request.since > through:
            raise ValueError("UPDATE_WINDOW_INVALID")
        targets = self._plan(request.products, request.since, through)
        return self._execute("update", targets, through, apply=False)

    def refresh(self, request: RefreshRequest) -> MaintenanceResult:
        """强制重写单品种窗口：要求主力映射连续；apply 时持锁并全量 expected 重拉/重聚合。"""
        if request.since > request.through:
            raise ValueError("REFRESH_WINDOW_INVALID")
        products = (request.symbol.strip().lower(),)
        assert_products_not_retired(products)
        if request.apply:
            lease = self.catalog.acquire_maintenance_lock()
            if lease is None:
                return _maintenance_locked("refresh", request.through)
            try:
                if not self.coverage.metadata_complete(products, request.through):
                    self.metadata.synchronize(
                        products,
                        request.through,
                        {request.symbol: self.coverage.product_start(request.symbol)},
                    )
                self.coverage.require_historical_session_facts(products, request.through)
                # refresh 覆盖 contract 序列，主力映射缺口会导致 expected 与物理路径不一致。
                if self.catalog.missing_main_map_days(
                    request.symbol,
                    request.since,
                    request.through,
                ):
                    raise ValueError("MAIN_CONTRACT_MAP_MISSING")
                targets = tuple(
                    self._iter_targets(
                        products,
                        request.since,
                        request.through,
                        force=True,
                    )
                )
                return self._execute("refresh", targets, request.through, apply=True)
            finally:
                lease.release()
        targets = tuple(
            self._iter_targets(
                products,
                request.since,
                request.through,
                force=True,
            )
        )
        return self._execute("refresh", targets, request.through, apply=request.apply)

    def audit(self, request: AuditRequest) -> MaintenanceResult:
        """只读审计：不拉 RQData、不写分区；对照 catalog 与 coverage 期望发现缺口/损坏。"""
        assert_products_not_retired(request.products)
        findings: list[AuditFinding] = []
        throughs: list[date] = []
        for symbol in request.products:
            try:
                through = self.coverage.latest_complete_day((symbol,))
                start = self.coverage.product_start(symbol)
                missing_map = self.catalog.missing_main_map_days(symbol, start, through)
                if missing_map:
                    first = missing_map[0]
                    findings.append(
                        AuditFinding(
                            "MAIN_CONTRACT_MAP_MISSING",
                            "main_contract_map",
                            ("metadata", symbol, "rank1", "1d"),
                            first.year,
                            first.month,
                        )
                    )
                for key, year, month, expected in self._desired_months((symbol,), through):
                    if not expected:
                        continue
                    existing, physical_reason = self._existing_partition(key, year, month)
                    if physical_reason is not None:
                        findings.append(
                            AuditFinding(
                                physical_reason,
                                "physical",
                                key.as_tuple(),
                                year,
                                month,
                            )
                        )
                        continue
                    if tuple(bar.bar_end for bar in existing) != expected:
                        findings.append(
                            AuditFinding(
                                "EXPECTED_PARTITION_MISSING",
                                "partition",
                                key.as_tuple(),
                                year,
                                month,
                            )
                        )
                throughs.append(through)
            except Exception as exc:  # noqa: BLE001 - recognized metadata gaps isolate one product
                finding = _audit_metadata_finding(exc, symbol)
                if finding is None:
                    raise
                findings.append(finding)
        return MaintenanceResult(
            action="audit",
            status="passed" if not findings else "failed",
            through=min(throughs) if throughs else None,
            planned=0,
            applied=0,
            blocked=0,
            failed=len(findings),
            provider_requests=0,
            findings=tuple(findings),
        )

    def _plan(
        self,
        products: tuple[str, ...],
        since: date | None,
        through: date,
    ) -> tuple[_Target, ...]:
        """dry-run 规划：收集全部待处理 _Target，不区分 direct/derived 顺序。"""
        return tuple(self._iter_targets(products, since, through))

    def _iter_targets(
        self,
        products: tuple[str, ...],
        since: date | None,
        through: date,
        *,
        frequencies: frozenset[BarFrequency] | None = None,
        force: bool = False,
    ):
        """遍历应处理的月分区；force 时 missing=整段 expected（refresh 重写语义）。"""
        for key, year, month, expected in self._desired_months(
            products,
            through,
            frequencies=frequencies,
        ):
            if not expected:
                continue
            existing, physical_reason = self._existing_partition(key, year, month)
            if physical_reason is not None:
                # 分区元数据损坏：按整月 expected 重拉，避免在残缺文件上增量合并。
                yield _Target(key, year, month, expected, expected, ())
                continue
            present = {bar.bar_end for bar in existing}
            missing = tuple(
                item
                for item in expected
                if item not in present and (since is None or item.date() >= since)
            )
            if force:
                if expected and (since is None or expected[-1].date() >= since):
                    yield _Target(key, year, month, expected, expected, ())
            elif not present <= set(expected) or len(present) != len(existing):
                # 存在非期望 bar 或重复 bar_end：整月重写而非只补 missing。
                yield _Target(key, year, month, expected, expected, ())
            elif missing:
                yield _Target(key, year, month, expected, missing, existing)

    def _desired_months(
        self,
        products: tuple[str, ...],
        through: date,
        *,
        frequencies: frozenset[BarFrequency] | None = None,
    ):
        """展开 continuous MAIN 与各 contract 月分区及其 expected_bar_ends（coverage 驱动）。"""
        selected_frequencies = tuple(
            value
            for value in _FREQUENCY_ORDER
            if frequencies is None or value in frequencies
        )
        for symbol in tuple(dict.fromkeys(item.strip().lower() for item in products)):
            product_start = self.coverage.product_start(symbol)
            for frequency in selected_frequencies:
                key = DatasetKey(DatasetKind.CONTINUOUS, symbol, "MAIN", frequency)
                start = (
                    self.coverage.dataset_start(key)
                    if hasattr(self.coverage, "dataset_start")
                    else product_start
                )
                for year, month in _months(start, through):
                    yield (
                        key,
                        year,
                        month,
                        tuple(
                            item.astimezone(UTC)
                            for item in self.coverage.expected_bar_ends(
                                key, year, month, start, through
                            )
                        ),
                    )
            # contract 序列按主力映射日分组：只在映射到的交易日生成该合约的 expected。
            mapping = self.catalog.main_map(symbol, product_start, through)
            days_by_contract_month: dict[tuple[str, int, int], list[date]] = {}
            for fact in mapping:
                days_by_contract_month.setdefault(
                    (fact.contract, fact.trade_date.year, fact.trade_date.month), []
                ).append(fact.trade_date)
            for (contract, year, month), mapped_days in days_by_contract_month.items():
                for frequency in selected_frequencies:
                    key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, frequency)
                    dataset_start = (
                        self.coverage.dataset_start(key)
                        if hasattr(self.coverage, "dataset_start")
                        else product_start
                    )
                    expected = self.coverage.expected_bar_ends_for_trading_days(
                        key,
                        tuple(day for day in mapped_days if day >= dataset_start),
                    )
                    if not expected:
                        continue
                    yield (
                        key,
                        year,
                        month,
                        tuple(item.astimezone(UTC) for item in expected),
                    )

    def _execute(
        self,
        action: str,
        targets: tuple[_Target, ...],
        through: date | None,
        *,
        apply: bool,
    ) -> MaintenanceResult:
        """执行或仅规划：apply 时先 direct 批次再 derived（非 streaming 路径）。"""
        if not targets:
            return MaintenanceResult(action, "noop", through, 0, 0, 0, 0, 0)
        if not apply:
            return MaintenanceResult(
                action,
                "planned",
                through,
                len(targets),
                0,
                0,
                0,
                0,
                target_windows=tuple(_target_payload(item) for item in targets),
            )
        direct = tuple(item for item in targets if item.key.frequency in DIRECT_FREQUENCIES)
        derived = tuple(item for item in targets if item.key.frequency in DERIVED_FREQUENCIES)
        return self._execute_apply(
            action,
            direct,
            derived,
            through,
        )

    def _execute_streaming(
        self,
        action: str,
        products: tuple[str, ...],
        since: date | None,
        through: date,
    ) -> MaintenanceResult:
        """update apply 专用：direct 与 derived 分两路迭代器，支持 1m 后即时聚合 derived。"""
        return self._execute_apply(
            action,
            self._iter_targets(
                products,
                since,
                through,
                frequencies=DIRECT_FREQUENCIES,
            ),
            self._iter_targets(
                products,
                since,
                through,
                frequencies=DERIVED_FREQUENCIES,
            ),
            through,
        )

    def _execute_apply(
        self,
        action: str,
        direct,
        derived,
        through: date | None,
    ) -> MaintenanceResult:
        """apply 核心循环：先尝试已有 1m 的 derived，再拉 direct，最后扫剩余 derived。"""
        remaining_derived = list(derived)
        planned = 0
        applied = 0
        blocked = 0
        provider_requests = 0
        failures: list[Mapping[str, object]] = []
        # 某 (kind, symbol, contract) 族 direct 失败后，同族 derived 标记 blocked 而非误聚合。
        failed_families: set[tuple[str, str, str]] = set()
        # 已有完整 1m 的 derived 可先发布（例如 refresh 只动了 direct 之外的频度）。
        for target in tuple(remaining_derived):
            try:
                self._publish_derived(target)
            except (AggregationError, StorageError) as exc:
                # 源 1m 尚未就绪时跳过，留待 direct 补齐同月 1m 后再聚合。
                if getattr(exc, "code", "") in {
                    "SOURCE_1M_INCOMPLETE",
                    "SOURCE_1M_NOT_ORDERED",
                    "TARGET_WINDOW_INCOMPLETE",
                }:
                    continue
                raise
            else:
                remaining_derived.remove(target)
                planned += 1
                applied += 1
        for target in direct:
            planned += 1
            try:
                provider_requests += 1
                batch = self.provider.fetch(target.key, target.missing)
                self._publish_direct(target, (batch,))
                applied += 1
                # derived 聚合触发点：同族同月 1m 发布成功后立即聚合同月 5m/15m/30m/60m。
                if target.key.frequency is BarFrequency.M1:
                    ready = [
                        item
                        for item in remaining_derived
                        if _family(item.key) == _family(target.key)
                        and item.year == target.year
                        and item.month == target.month
                    ]
                    for item in ready:
                        remaining_derived.remove(item)
                        planned += 1
                        self._publish_derived(item)
                        applied += 1
            except Exception as exc:  # noqa: BLE001 - isolate one product/dataset
                # 配额耗尽：partial 停止并保留已 applied，避免继续烧钱且无意义重试。
                if getattr(exc, "code", None) == "PROVIDER_QUOTA_EXHAUSTED":
                    return MaintenanceResult(
                        action,
                        "partial",
                        through,
                        planned,
                        applied,
                        blocked,
                        len(failures),
                        provider_requests,
                        "provider_quota_exhausted",
                        failures=tuple(failures),
                    )
                if _is_global_failure(exc):
                    raise
                failed_families.add(_family(target.key))
                failures.append(_failure(target, exc))
                self.catalog.session.rollback()
            if planned == 1 or planned % 100 == 0:
                print(
                    f"maintenance {action} direct planned={planned} applied={applied} "
                    f"failed={len(failures)} provider_requests={provider_requests}",
                    flush=True,
                )
        for target in remaining_derived:
            planned += 1
            if _family(target.key) in failed_families:
                blocked += 1
                continue
            try:
                self._publish_derived(target)
                applied += 1
            except Exception as exc:  # noqa: BLE001 - isolate one product/dataset
                if _is_global_failure(exc):
                    raise
                failures.append(_failure(target, exc))
                self.catalog.session.rollback()
            if planned % 100 == 0:
                print(
                    f"maintenance {action} derived planned={planned} applied={applied} "
                    f"failed={len(failures)} blocked={blocked}",
                    flush=True,
                )
        if planned == 0:
            status = "noop"
        else:
            status = "failed" if failures or blocked else "passed"
        return MaintenanceResult(
            action,
            status,
            through,
            planned,
            applied,
            blocked,
            len(failures),
            provider_requests,
            failures=tuple(failures),
        )

    def _publish_direct(self, target: _Target, batches: tuple[BarBatch, ...]) -> None:
        """合并 existing 与 provider 批次，经 store.publish 六项校验后注册分区。"""
        merged = {bar.bar_end: bar for bar in target.existing}
        for batch in batches:
            for bar in batch.bars:
                merged[bar.bar_end] = bar
        bars = tuple(merged[item] for item in target.expected if item in merged)
        if tuple(bar.bar_end for bar in bars) != target.expected:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        # publish 内部：schema/顺序/月界/会话边界校验 → tmp.parquet → os.replace 原子替换。
        partition = self.store.publish(
            PublishRequest(
                target.key,
                target.year,
                target.month,
                bars,
                target.expected,
            )
        )
        self._commit_partition(partition, target)

    def _publish_derived(self, target: _Target) -> None:
        """从当月 1m 源分区聚合 derived 频度；会话窗口须覆盖 target.expected。"""
        source_key = DatasetKey(
            target.key.kind,
            target.key.symbol,
            target.key.series_or_contract,
            BarFrequency.M1,
        )
        source = self._read_existing(source_key, target.year, target.month)
        if not source:
            raise StorageError("SOURCE_1M_INCOMPLETE")
        sessions = tuple(
            session
            for session in self.coverage.sessions(
                target.key,
                target.year,
                target.month,
                through=target.expected[-1].date(),
            )
            if any(session.start < bar_end <= session.end for bar_end in target.expected)
        )
        if not sessions:
            raise StorageError("TARGET_SESSION_WINDOW_MISSING")
        bars = aggregate_from_1m(
            source,
            target_frequency=target.key.frequency,
            sessions=sessions,
        )
        if tuple(bar.bar_end for bar in bars) != target.expected:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        partition = self.store.publish(
            PublishRequest(
                target.key,
                target.year,
                target.month,
                bars,
                target.expected,
            )
        )
        self._commit_partition(partition, target)

    def _commit_partition(self, partition, target: _Target) -> None:
        """注册 catalog 分区行并 strict 读回验证；任一步失败 rollback，不留下半提交状态。"""
        try:
            self.catalog.register_partition(partition)
            self._strict_verify(target)
            self.catalog.session.commit()
        except Exception:
            self.catalog.session.rollback()
            raise

    def _strict_verify(self, target: _Target) -> None:
        """发布后经 MarketDataService 读回，确保消费者路径与 expected 完全一致（fail-closed）。"""
        if target.key.kind is DatasetKind.CONTINUOUS:
            series_kind = SeriesKind.CONTINUOUS
            contract = None
        else:
            series_kind = SeriesKind.CONTRACT
            contract = target.key.series_or_contract
        try:
            result = MarketDataService(self.catalog, self.store).query(
                SeriesQuery(
                    series_kind=series_kind,
                    symbol=target.key.symbol,
                    contract=contract,
                    frequency=target.key.frequency,
                    start=target.expected[0] - timedelta(microseconds=1),
                    end=target.expected[-1],
                )
            )
        except MarketDataError as exc:
            raise StorageError("STRICT_READ_VERIFICATION_FAILED") from exc
        if tuple(bar.bar_end for bar in result.bars) != target.expected:
            raise StorageError("STRICT_READ_VERIFICATION_FAILED")

    def _read_existing(self, key: DatasetKey, year: int, month: int) -> tuple[CanonicalBar, ...]:
        """读取已有月分区；无 catalog 行或物理不可读时返回空元组（非 corrupt 语义）。"""
        rows = tuple(
            item
            for item in self.catalog.all_partitions(key)
            if item.year == year and item.month == month
        )
        if not rows:
            return ()
        try:
            return self.store.read_month(key, year, month)
        except StorageError:
            return ()

    def _existing_partition(
        self,
        key: DatasetKey,
        year: int,
        month: int,
    ) -> tuple[tuple[CanonicalBar, ...], str | None]:
        """检查 catalog 与 part.parquet 一致性；返回物理问题码以支持 audit 分类。"""
        rows = tuple(
            item
            for item in self.catalog.all_partitions(key)
            if item.year == year and item.month == month
        )
        if not rows:
            return (), None
        expected_path = self.store.root.joinpath(
            *key.relative_root.parts,
            f"year={year:04d}",
            f"month={month:02d}",
            "part.parquet",
        )
        row = rows[0]
        if len(rows) != 1 or row.file_path != expected_path or not row.file_path.is_file():
            return (), "PARTITION_CATALOG_MISMATCH"
        try:
            values = self.store.read_month(key, year, month)
        except StorageError as exc:
            return (), getattr(exc, "code", "PARTITION_UNREADABLE")
        if not values:
            return (), "PARTITION_EMPTY"
        if row.row_count != len(values):
            return (), "PARTITION_ROW_COUNT_MISMATCH"
        # catalog 记录的 coverage 区间须与物理首尾 bar 对齐，否则消费者会误判可读范围。
        if (
            row.coverage_start != values[0].bar_end - _frequency_delta(key.frequency)
            or row.coverage_end != values[-1].bar_end
        ):
            return (), "PARTITION_COVERAGE_MISMATCH"
        return values, None


def _months(start: date, end: date):
    """闭区间 [start, end] 内按自然月递增的 (year, month) 序列。"""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def _family(key: DatasetKey) -> tuple[str, str, str]:
    """数据集族标识：continuous/contract + symbol + series_or_contract，用于失败隔离。"""
    return key.kind.value, key.symbol, key.series_or_contract


def _failure(target: _Target, exc: Exception) -> Mapping[str, object]:
    """将单分区失败归一化为可序列化记录，供 MaintenanceResult.failures。"""
    return {
        "dataset": target.key.as_tuple(),
        "year": target.year,
        "month": target.month,
        "reason_code": getattr(exc, "code", type(exc).__name__),
    }


def _target_payload(target: _Target) -> Mapping[str, object]:
    """dry-run 时描述单个目标窗口（缺失 bar 起止与数量）。"""
    return {
        "dataset": target.key.as_tuple(),
        "year": target.year,
        "month": target.month,
        "window_start": target.missing[0].isoformat(),
        "window_end": target.missing[-1].isoformat(),
        "missing_bar_count": len(target.missing),
    }


def _is_global_failure(exc: Exception) -> bool:
    """须立即中止整次维护的全局错误（DB 或原子发布/路径逃逸），不可按族隔离。"""
    if isinstance(exc, SQLAlchemyError):
        return True
    return getattr(exc, "code", None) in {
        "ATOMIC_PUBLISH_FAILED",
        "CANONICAL_ROOT_ESCAPE",
        "PARTITION_URI_ESCAPE",
        "PARTITION_OUTSIDE_CANONICAL_ROOT",
    }


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    """单根 bar 的时间跨度，用于 coverage_start 与 bar_end 对齐校验。"""
    return {
        BarFrequency.M1: timedelta(minutes=1),
        BarFrequency.M5: timedelta(minutes=5),
        BarFrequency.M15: timedelta(minutes=15),
        BarFrequency.M30: timedelta(minutes=30),
        BarFrequency.H1: timedelta(hours=1),
        BarFrequency.D1: timedelta(days=1),
        BarFrequency.W1: timedelta(days=7),
    }[frequency]
