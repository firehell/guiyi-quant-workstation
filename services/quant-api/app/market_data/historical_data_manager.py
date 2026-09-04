"""历史 canonical 数据的维护编排层（update / refresh / audit）。

本模块是「写路径」的应用服务，把 Catalog、月分区 Store、Coverage 期望、元数据同步与
RQData 拉取组装成可审计的维护流程。消费者（MarketDataService、Web）只读已发布分区；
任何缺口补齐、分区重写或 derived 聚合都必须经过这里的门禁。

职责边界
--------
HistoricalDataManager
    唯一维护入口：规划目标月分区、区分经 BarSource 获取的 base/weekly 目标与日内 1m 派生目标、
    调用 store.publish 完成 staging 六项硬校验与 part.parquet 原子替换，再 register_partition
    并 strict_verify 读回。apply=False 时只返回 planned 窗口，不写库与文件。

CoverageSource（Protocol，实现见 coverage_source.DatabaseCoverageSource）
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

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.market_data.aggregation import AggregationError, aggregate_from_1m
from app.market_data.catalog import ContractFact, MarketCatalog
from app.market_data.domain import (
    INTRADAY_DERIVED_FREQUENCIES,
    PROVIDER_FETCH_FREQUENCIES,
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
    SeriesKind,
    SeriesQuery,
)
from app.market_data.product_retirement import assert_products_not_retired
from app.market_data.session_clock import SHANGHAI
from app.market_data.market_data_service import MarketDataError, MarketDataService
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
    def contract_trading_days(
        self,
        fact: ContractFact,
        start: date,
        end: date,
    ) -> tuple[date, ...]: ...
    def contract_expected_bar_ends(
        self,
        key: DatasetKey,
        fact: ContractFact,
        year: int,
        month: int,
        through: date,
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
    """行情拉取端口：同批请求共享 provider 日行情快照。"""

    def fetch_many(
        self,
        requests: tuple[BarFetchRequest, ...],
    ) -> tuple[BarBatch, ...]: ...


@dataclass(frozen=True, slots=True)
class BarBatch:
    """单次 provider 拉取归一化后的 bar 批次。"""

    bars: tuple[CanonicalBar, ...]


@dataclass(frozen=True, slots=True)
class BarFetchRequest:
    """一次 provider 逻辑请求；同一 fetch_many 调用内可复用底层日行情。"""

    key: DatasetKey
    expected: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """批量增量更新：多品种、可选 since，through 缺省为最近完整交易日。"""

    products: tuple[str, ...]
    since: date | None
    through: date | None
    apply: bool = False
    sync_current_day_metadata: bool = False


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
    through: date | None = None


@dataclass(frozen=True, slots=True)
class ContractWarmupRequest:
    symbol: str
    contract: str
    through: date
    expected_plan_sha256: str | None = None
    apply: bool = False


@dataclass(frozen=True, slots=True)
class ContractWarmupPlan:
    symbol: str
    contract: str
    provider: str
    listed_date: date
    expired_date: date
    through: date
    target_windows: tuple[Mapping[str, object], ...]
    direct_target_count: int
    derived_target_count: int
    expected_bar_count: int
    provider_request_count: int
    plan_sha256: str


@dataclass(frozen=True, slots=True)
class ContractWarmupResult:
    status: str
    readonly: bool
    plan: ContractWarmupPlan
    applied: int
    blocked: int
    failed: int
    provider_requests: int
    failures: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """审计发现项：编码 + 数据集四元组 + 问题所在年月。"""

    code: str
    category: str
    dataset: tuple[str, str, str, str]
    year: int | None
    month: int | None


@dataclass(frozen=True, slots=True)
class AuditProgressEvent:
    """审计单品种进度的结构化 observer 值，不含 CLI 输出语义。"""

    state: str
    completed: int
    total: int
    symbol: str
    finding_count: int | None


AuditObserver = Callable[[AuditProgressEvent], None]


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


@dataclass(frozen=True, slots=True)
class _ContractPartitionClassification:
    """Mapped required 与 lifecycle-valid persisted 的单一分区分类结果。"""

    expected: tuple[datetime, ...]
    refresh_expected: tuple[datetime, ...]
    missing_mapped: tuple[datetime, ...]
    outside_lifecycle: bool


# 规划顺序：先日/周再 1m，使日内派生能在同族 1m 补齐后尽快触发。
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

    def update(
        self,
        request: UpdateRequest,
        *,
        before_apply: Callable[[], None] | None = None,
    ) -> MaintenanceResult:
        """增量更新：缺省 through 为各品种最近完整交易日；apply 时持锁并先补齐元数据再写分区。"""
        assert_products_not_retired(request.products)
        if (
            request.since is not None
            and request.through is not None
            and request.since > request.through
        ):
            raise ValueError("UPDATE_WINDOW_INVALID")
        if request.apply:
            metadata_through = request.through or self.coverage.latest_metadata_day(
                request.products
            )
            # apply 路径必须持 maintenance lease，防止与 refresh/另一 update 并发写分区。
            lease = self.catalog.acquire_maintenance_lock()
            if lease is None:
                return _maintenance_locked("update", metadata_through)
            try:
                if before_apply is not None:
                    before_apply()
                if request.sync_current_day_metadata:
                    self.metadata.synchronize_current_day(
                        request.products,
                        metadata_through,
                    )
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

    def refresh(
        self,
        request: RefreshRequest,
        *,
        before_apply: Callable[[], None] | None = None,
    ) -> MaintenanceResult:
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
                if before_apply is not None:
                    before_apply()
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

    def contract_warmup(
        self,
        request: ContractWarmupRequest,
        *,
        before_apply: Callable[[], None] | None = None,
    ) -> ContractWarmupResult:
        """规划或执行单一真实合约上市有效期内的七周期 warm-up。"""
        plan, _targets = self._contract_warmup_plan(request)
        if not request.apply:
            return ContractWarmupResult(
                status="planned",
                readonly=True,
                plan=plan,
                applied=0,
                blocked=0,
                failed=0,
                provider_requests=0,
            )
        expected_hash = request.expected_plan_sha256
        if expected_hash is None:
            raise ValueError("CONTRACT_WARMUP_PLAN_HASH_REQUIRED")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in expected_hash
        ):
            raise ValueError("CONTRACT_WARMUP_PLAN_HASH_INVALID")
        lease = self.catalog.acquire_maintenance_lock()
        if lease is None:
            return ContractWarmupResult(
                status="blocked",
                readonly=False,
                plan=plan,
                applied=0,
                blocked=1,
                failed=0,
                provider_requests=0,
                failures=({"reason_code": "maintenance_locked"},),
            )
        try:
            locked_plan, locked_targets = self._contract_warmup_plan(request)
            if locked_plan.plan_sha256 != expected_hash:
                raise ValueError("CONTRACT_WARMUP_PLAN_CHANGED")
            if before_apply is not None:
                before_apply()
            maintenance = self._execute_apply(
                "contract_warmup",
                tuple(
                    target
                    for target in locked_targets
                    if target.key.frequency in PROVIDER_FETCH_FREQUENCIES
                ),
                tuple(
                    target
                    for target in locked_targets
                    if target.key.frequency in INTRADAY_DERIVED_FREQUENCIES
                ),
                request.through,
                weekly_daily_companions=False,
            )
            return ContractWarmupResult(
                status=maintenance.status,
                readonly=False,
                plan=locked_plan,
                applied=maintenance.applied,
                blocked=maintenance.blocked,
                failed=maintenance.failed,
                provider_requests=maintenance.provider_requests,
                failures=maintenance.failures,
            )
        finally:
            lease.release()

    def _contract_warmup_plan(
        self,
        request: ContractWarmupRequest,
    ) -> tuple[ContractWarmupPlan, tuple[_Target, ...]]:
        """只读构建 exact physical-contract 目标及稳定 plan identity。"""
        symbol = request.symbol.strip().lower()
        contract = request.contract.strip().upper()
        assert_products_not_retired((symbol,))
        fact = self.catalog.contract_fact(symbol, contract)
        latest_complete = self.coverage.latest_complete_day((symbol,))
        if request.through > latest_complete:
            raise ValueError("CONTRACT_WARMUP_THROUGH_INCOMPLETE")
        effective_through = min(
            request.through,
            fact.expired_date - timedelta(days=1),
        )
        if fact.listed_date > effective_through:
            raise ValueError("CONTRACT_ACTIVE_WINDOW_MISSING")

        targets: list[_Target] = []
        for frequency in _FREQUENCY_ORDER:
            key = DatasetKey(
                DatasetKind.CONTRACT,
                symbol,
                contract,
                frequency,
            )
            for year, month in _months(fact.listed_date, effective_through):
                expected = tuple(
                    item.astimezone(UTC)
                    for item in self.coverage.contract_expected_bar_ends(
                        key,
                        fact,
                        year,
                        month,
                        effective_through,
                    )
                )
                if not expected:
                    continue
                existing, physical_reason = self._existing_partition(key, year, month)
                if physical_reason is not None:
                    targets.append(_Target(key, year, month, expected, expected, ()))
                    continue
                classification = self._classify_contract_partition(
                    key,
                    year,
                    month,
                    expected,
                    existing,
                    effective_through,
                )
                if classification.outside_lifecycle:
                    targets.append(
                        _Target(
                            key,
                            year,
                            month,
                            classification.expected,
                            classification.expected,
                            (),
                        )
                    )
                elif classification.missing_mapped:
                    targets.append(
                        _Target(
                            key,
                            year,
                            month,
                            classification.expected,
                            classification.missing_mapped,
                            existing,
                        )
                    )

        targets = self._with_contract_weekly_daily_context(
            targets,
            fact,
            effective_through,
        )
        target_windows = tuple(_contract_warmup_target_payload(item) for item in targets)
        plan_identity: Mapping[str, object] = {
            "schema_version": 1,
            "command": "data.contract-warmup",
            "symbol": symbol,
            "contract": contract,
            "provider": fact.provider,
            "listed_date": fact.listed_date.isoformat(),
            "expired_date": fact.expired_date.isoformat(),
            "requested_window": {
                "start": fact.listed_date.isoformat(),
                "through": request.through.isoformat(),
            },
            "effective_window": {
                "start": fact.listed_date.isoformat(),
                "through": effective_through.isoformat(),
            },
            "targets": tuple(
                _contract_warmup_hash_target_payload(target) for target in targets
            ),
        }
        plan_sha256 = hashlib.sha256(
            json.dumps(
                plan_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        direct_target_count = sum(
            target.key.frequency in PROVIDER_FETCH_FREQUENCIES for target in targets
        )
        return (
            ContractWarmupPlan(
                symbol=symbol,
                contract=contract,
                provider=fact.provider,
                listed_date=fact.listed_date,
                expired_date=fact.expired_date,
                through=request.through,
                target_windows=target_windows,
                direct_target_count=direct_target_count,
                derived_target_count=len(targets) - direct_target_count,
                expected_bar_count=sum(len(target.expected) for target in targets),
                provider_request_count=direct_target_count,
                plan_sha256=plan_sha256,
            ),
            tuple(targets),
        )

    def audit(
        self,
        request: AuditRequest,
        *,
        observer: AuditObserver | None = None,
    ) -> MaintenanceResult:
        """只读审计：不拉 RQData、不写分区；对照 catalog 与 coverage 期望发现缺口/损坏。"""
        products = tuple(symbol.strip().lower() for symbol in request.products)
        assert_products_not_retired(products)
        findings: list[AuditFinding] = []
        throughs: list[date] = []
        total = len(products)
        for completed, symbol in enumerate(products):
            if observer is not None:
                observer(
                    AuditProgressEvent(
                        state="started",
                        completed=completed,
                        total=total,
                        symbol=symbol,
                        finding_count=None,
                    )
                )
            finding_start = len(findings)
            try:
                through = request.through or self.coverage.latest_complete_day((symbol,))
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
                for key, year, month, expected, _mapped_days in self._desired_months(
                    (symbol,), through
                ):
                    if not expected and key.kind is not DatasetKind.CONTRACT:
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
                    if key.kind is DatasetKind.CONTRACT:
                        classification = self._classify_contract_partition(
                            key,
                            year,
                            month,
                            expected,
                            existing,
                            through,
                        )
                        if classification.outside_lifecycle:
                            findings.append(
                                AuditFinding(
                                    "CONTRACT_PARTITION_OUTSIDE_LIFECYCLE",
                                    "partition",
                                    key.as_tuple(),
                                    year,
                                    month,
                                )
                            )
                        if classification.missing_mapped:
                            findings.append(
                                AuditFinding(
                                    "EXPECTED_PARTITION_MISSING",
                                    "partition",
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
            if observer is not None:
                observer(
                    AuditProgressEvent(
                        state="completed",
                        completed=completed + 1,
                        total=total,
                        symbol=symbol,
                        finding_count=len(findings) - finding_start,
                    )
                )
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
        """dry-run 规划：显式展示缺失周线会带动的完整同周日线刷新。"""
        planned: list[_Target] = []
        for target in self._iter_targets(products, since, through):
            if target.key.frequency is BarFrequency.W1:
                planned.extend(self._weekly_daily_companions(target, through))
            planned.append(target)
        return tuple(planned)

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
        latest_complete_by_symbol: dict[str, date] = {}
        for key, year, month, expected, mapped_days in self._desired_months(
            products,
            through,
            frequencies=frequencies,
        ):
            if not expected and key.kind is not DatasetKind.CONTRACT:
                continue
            existing, physical_reason = self._existing_partition(key, year, month)
            if physical_reason is not None:
                if not expected:
                    continue
                # 分区元数据损坏：按整月 expected 重拉，避免在残缺文件上增量合并。
                yield _Target(key, year, month, expected, expected, ())
                continue
            existing_by_end = {bar.bar_end: bar for bar in existing}
            present = set(existing_by_end)
            if key.kind is DatasetKind.CONTRACT:
                classification = self._classify_contract_partition(
                    key,
                    year,
                    month,
                    expected,
                    existing,
                    through,
                )
                eligible_mapped = classification.missing_mapped
                if since is not None:
                    required_since = {
                        item.astimezone(UTC)
                        for item in self.coverage.expected_bar_ends_for_trading_days(
                            key,
                            tuple(day for day in mapped_days if day >= since),
                        )
                    }
                    eligible_mapped = tuple(
                        item
                        for item in classification.missing_mapped
                        if item in required_since
                    )
                missing = eligible_mapped
                if force:
                    if classification.refresh_expected and (
                        since is None
                        or (year, month) >= (since.year, since.month)
                    ):
                        refresh_set = set(classification.refresh_expected)
                        publish_set = set(classification.expected)
                        retained = tuple(
                            bar
                            for bar in existing
                            if bar.bar_end.astimezone(UTC) in publish_set
                            and bar.bar_end.astimezone(UTC) not in refresh_set
                        )
                        yield _Target(
                            key,
                            year,
                            month,
                            classification.expected,
                            classification.refresh_expected,
                            retained,
                        )
                elif classification.outside_lifecycle:
                    yield _Target(
                        key,
                        year,
                        month,
                        classification.expected,
                        classification.expected,
                        (),
                    )
                elif missing:
                    yield _Target(
                        key,
                        year,
                        month,
                        classification.expected,
                        missing,
                        existing,
                    )
                continue
            latest_complete = latest_complete_by_symbol.get(key.symbol)
            if latest_complete is None:
                latest_complete = self.coverage.latest_complete_day((key.symbol,))
                latest_complete_by_symbol[key.symbol] = latest_complete
            missing = tuple(
                item
                for item in expected
                if item not in present and (since is None or item.date() >= since)
            )
            if force:
                if expected and (since is None or expected[-1].date() >= since):
                    yield _Target(key, year, month, expected, expected, ())
            elif len(present) != len(existing) or any(
                item <= expected[-1]
                or existing_by_end[item].trading_day > latest_complete
                for item in present - set(expected)
            ):
                # 窗口内非期望 bar 或重复 bar_end：整月重写而非只补 missing。
                yield _Target(key, year, month, expected, expected, ())
            elif missing:
                # fixed-through 只能补窗口内的缺口，不能把该月已发布的后续
                # Canonical bar 当作异常并在重写时丢弃。
                publish_expected = tuple(sorted(set(expected).union(present)))
                yield _Target(key, year, month, publish_expected, missing, existing)

    def _classify_contract_partition(
        self,
        key: DatasetKey,
        year: int,
        month: int,
        required_mapped: tuple[datetime, ...],
        existing: tuple[CanonicalBar, ...],
        through: date,
    ) -> _ContractPartitionClassification:
        """应用 mapped ⊆ persisted ⊆ lifecycle-valid 的唯一 contract 判定。"""
        fact = self.catalog.contract_fact(key.symbol, key.series_or_contract)
        lifecycle_valid = (
            {
                item.astimezone(UTC)
                for item in self.coverage.contract_expected_bar_ends(
                    key,
                    fact,
                    year,
                    month,
                    max(bar.trading_day for bar in existing),
                )
            }
            if existing
            else set()
        )
        required = {item.astimezone(UTC) for item in required_mapped}
        persisted = tuple(bar.bar_end.astimezone(UTC) for bar in existing)
        persisted_set = set(persisted)
        valid_persisted = persisted_set.intersection(lifecycle_valid)
        refresh_persisted = {
            bar.bar_end.astimezone(UTC)
            for bar in existing
            if bar.trading_day <= through
            and bar.bar_end.astimezone(UTC) in lifecycle_valid
        }
        return _ContractPartitionClassification(
            expected=tuple(sorted(required.union(valid_persisted))),
            refresh_expected=tuple(sorted(required.union(refresh_persisted))),
            missing_mapped=tuple(sorted(required - persisted_set)),
            outside_lifecycle=(
                len(persisted) != len(persisted_set)
                or not persisted_set.issubset(lifecycle_valid)
            ),
        )

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
                        (),
                    )
            # contract 序列的 required 仍仅来自主力映射日；已存在的 Catalog
            # 分区也必须参与 lifecycle 分类，以覆盖没有 rank1 日的纯 warm-up 月。
            mapping = self.catalog.main_map(symbol, product_start, through)
            days_by_contract_month: dict[tuple[str, int, int], list[date]] = {}
            for fact in mapping:
                days_by_contract_month.setdefault(
                    (fact.contract, fact.trade_date.year, fact.trade_date.month), []
                ).append(fact.trade_date)
            desired_contract_partitions: dict[
                tuple[str, int, int, BarFrequency], tuple[date, ...]
            ] = {
                (contract, year, month, frequency): tuple(mapped_days)
                for (contract, year, month), mapped_days in days_by_contract_month.items()
                for frequency in selected_frequencies
            }
            through_month = (through.year, through.month)
            for frequency in selected_frequencies:
                for partition in self.catalog.contract_partitions_before(
                    symbol,
                    frequency,
                    None,
                ):
                    if (partition.year, partition.month) <= through_month:
                        identity = (
                            partition.dataset.series_or_contract,
                            partition.year,
                            partition.month,
                            frequency,
                        )
                        desired_contract_partitions.setdefault(identity, ())
            frequency_index = {
                frequency: index
                for index, frequency in enumerate(selected_frequencies)
            }
            for (
                contract,
                year,
                month,
                frequency,
            ), mapped_days in sorted(
                desired_contract_partitions.items(),
                key=lambda item: (
                    item[0][1],
                    item[0][2],
                    item[0][0],
                    frequency_index[item[0][3]],
                ),
            ):
                key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, frequency)
                dataset_start = (
                    self.coverage.dataset_start(key)
                    if hasattr(self.coverage, "dataset_start")
                    else product_start
                )
                active_mapped_days = tuple(
                    day for day in mapped_days if day >= dataset_start
                )
                expected = self.coverage.expected_bar_ends_for_trading_days(
                    key,
                    active_mapped_days,
                )
                yield (
                    key,
                    year,
                    month,
                    tuple(item.astimezone(UTC) for item in expected),
                    active_mapped_days,
                )

    def _execute(
        self,
        action: str,
        targets: tuple[_Target, ...],
        through: date | None,
        *,
        apply: bool,
    ) -> MaintenanceResult:
        """执行或仅规划：apply 时先 fetch 批次再聚合日内频度（非 streaming 路径）。"""
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
        fetched = tuple(
            item for item in targets if item.key.frequency in PROVIDER_FETCH_FREQUENCIES
        )
        intraday_derived = tuple(
            item
            for item in targets
            if item.key.frequency in INTRADAY_DERIVED_FREQUENCIES
        )
        return self._execute_apply(
            action,
            fetched,
            intraday_derived,
            through,
            weekly_daily_companions=True,
        )

    def _execute_streaming(
        self,
        action: str,
        products: tuple[str, ...],
        since: date | None,
        through: date,
    ) -> MaintenanceResult:
        """update apply 专用：fetch 与日内派生分两路，支持 1m 后即时聚合。"""
        return self._execute_apply(
            action,
            self._iter_targets(
                products,
                since,
                through,
                frequencies=PROVIDER_FETCH_FREQUENCIES,
            ),
            self._iter_targets(
                products,
                since,
                through,
                frequencies=INTRADAY_DERIVED_FREQUENCIES,
            ),
            through,
            weekly_daily_companions=True,
        )

    def _execute_apply(
        self,
        action: str,
        fetched,
        intraday_derived,
        through: date | None,
        *,
        weekly_daily_companions: bool,
    ) -> MaintenanceResult:
        """apply 核心循环：先聚合已有 1m，再 fetch，最后扫剩余日内派生目标。"""
        remaining_derived = list(intraday_derived)
        planned = 0
        applied = 0
        blocked = 0
        provider_requests = 0
        failures: list[Mapping[str, object]] = []
        # 某 (kind, symbol, contract) 族 fetch 失败后，同族日内派生标记 blocked 而非误聚合。
        failed_families: set[tuple[str, str, str]] = set()
        # 已有完整 1m 的日内派生可先发布（例如 refresh 只涉及日内派生频度）。
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
        fetched_targets = tuple(fetched)
        fetch_groups: Iterable[tuple[_Target, ...]]
        if weekly_daily_companions:
            fetch_groups = (
                (
                    (*self._weekly_daily_companions(target, through), target)
                    if target.key.frequency is BarFrequency.W1
                    and through is not None
                    else (target,)
                )
                for target in fetched_targets
            )
        else:
            fetch_groups = _contract_warmup_fetch_groups(fetched_targets)
        for fetch_targets in fetch_groups:
            target = fetch_targets[-1]
            if (
                target.key.frequency is BarFrequency.W1
                and _family(target.key) in failed_families
            ):
                planned += 1
                blocked += 1
                continue
            failure_target = target
            try:
                planned += len(fetch_targets)
                provider_requests += len(fetch_targets)
                batches = self.provider.fetch_many(tuple(
                    BarFetchRequest(fetch_target.key, fetch_target.missing)
                    for fetch_target in fetch_targets
                ))
                if len(batches) != len(fetch_targets):
                    raise StorageError("PROVIDER_BATCH_COUNT_MISMATCH")
                paired = tuple(zip(fetch_targets, batches, strict=True))
                for fetch_target, batch in paired:
                    failure_target = fetch_target
                    self._merged_fetched_bars(
                        fetch_target,
                        (batch,),
                    )
                for fetch_target, batch in paired:
                    failure_target = fetch_target
                    self._publish_fetched(fetch_target, (batch,))
                    applied += 1
                # 日内派生触发点：同族同月 1m 发布成功后立即聚合 5m/15m/30m/60m。
                if target.key.frequency is BarFrequency.M1:
                    ready = [
                        item
                        for item in remaining_derived
                        if _family(item.key) == _family(target.key)
                        and item.year == target.year
                        and item.month == target.month
                    ]
                    for item in ready:
                        failure_target = item
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
                failed_families.add(_family(failure_target.key))
                failures.append(_failure(failure_target, exc))
                self.catalog.session.rollback()
            if planned == 1 or planned % 100 == 0:
                print(
                    f"maintenance {action} fetched planned={planned} applied={applied} "
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
        elif failures or blocked:
            status = (
                "partial"
                if action == "contract_warmup" and applied
                else "failed"
            )
        else:
            status = "passed"
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

    def _with_contract_weekly_daily_context(
        self,
        targets: list[_Target],
        fact: ContractFact,
        through: date,
    ) -> list[_Target]:
        """将缺失周线需要的 exact-lifecycle 日线刷新并入 warm-up 计划。"""
        refresh_by_partition: dict[
            tuple[DatasetKey, int, int], set[datetime]
        ] = {}
        for weekly in tuple(targets):
            if weekly.key.frequency is not BarFrequency.W1:
                continue
            daily_key = DatasetKey(
                DatasetKind.CONTRACT,
                weekly.key.symbol,
                weekly.key.series_or_contract,
                BarFrequency.D1,
            )
            for weekly_end in weekly.missing:
                trading_day = weekly_end.astimezone(SHANGHAI).date()
                monday = trading_day - timedelta(days=trading_day.isoweekday() - 1)
                sunday = min(monday + timedelta(days=6), through)
                trading_days = self.coverage.contract_trading_days(
                    fact,
                    monday,
                    sunday,
                )
                for item in self.coverage.expected_bar_ends_for_trading_days(
                    daily_key,
                    trading_days,
                ):
                    bar_end = item.astimezone(UTC)
                    local_day = bar_end.astimezone(SHANGHAI).date()
                    refresh_by_partition.setdefault(
                        (daily_key, local_day.year, local_day.month), set()
                    ).add(bar_end)

        by_partition = {
            (target.key, target.year, target.month): target for target in targets
        }
        for (key, year, month), refresh in refresh_by_partition.items():
            target = by_partition.get((key, year, month))
            if target is None:
                existing, physical_reason = self._existing_partition(key, year, month)
                if physical_reason is not None:
                    expected = tuple(sorted(refresh))
                    target = _Target(key, year, month, expected, expected, ())
                else:
                    present = {bar.bar_end.astimezone(UTC) for bar in existing}
                    target = _Target(
                        key,
                        year,
                        month,
                        tuple(sorted(present.union(refresh))),
                        tuple(sorted(refresh)),
                        existing,
                    )
            else:
                target = _Target(
                    key,
                    year,
                    month,
                    tuple(sorted(set(target.expected).union(refresh))),
                    tuple(sorted(set(target.missing).union(refresh))),
                    target.existing,
                )
            by_partition[(key, year, month)] = target
        frequency_order = {
            frequency: index for index, frequency in enumerate(_FREQUENCY_ORDER)
        }
        return sorted(
            by_partition.values(),
            key=lambda target: (
                frequency_order[target.key.frequency],
                target.year,
                target.month,
            ),
        )

    def _weekly_daily_companions(
        self,
        weekly: _Target,
        through: date,
    ) -> tuple[_Target, ...]:
        """周线发布前强制刷新同一 ISO 周内已落盘的日线事实。"""
        daily_key = DatasetKey(
            weekly.key.kind,
            weekly.key.symbol,
            weekly.key.series_or_contract,
            BarFrequency.D1,
        )
        refresh_by_month: dict[tuple[int, int], set[datetime]] = {}
        for weekly_end in weekly.missing:
            trading_day = weekly_end.astimezone(SHANGHAI).date()
            monday = trading_day - timedelta(days=trading_day.isoweekday() - 1)
            sunday = min(monday + timedelta(days=6), through)
            if daily_key.kind is DatasetKind.CONTRACT:
                mapped_days = tuple(
                    fact.trade_date
                    for fact in self.catalog.main_map(
                        daily_key.symbol,
                        monday,
                        sunday,
                    )
                    if fact.contract == daily_key.series_or_contract
                )
                expected = self.coverage.expected_bar_ends_for_trading_days(
                    daily_key,
                    mapped_days,
                )
                for item in expected:
                    local_day = item.astimezone(SHANGHAI).date()
                    refresh_by_month.setdefault(
                        (local_day.year, local_day.month), set()
                    ).add(item.astimezone(UTC))
                continue
            for year, month in _months(monday, sunday):
                expected = self.coverage.expected_bar_ends(
                    daily_key,
                    year,
                    month,
                    monday,
                    sunday,
                )
                refresh_by_month.setdefault((year, month), set()).update(
                    item.astimezone(UTC) for item in expected
                )
        companions: list[_Target] = []
        for (year, month), refresh in sorted(refresh_by_month.items()):
            if not refresh:
                continue
            existing, physical_reason = self._existing_partition(daily_key, year, month)
            if physical_reason is not None:
                raise StorageError(physical_reason)
            present = {bar.bar_end for bar in existing}
            expected = tuple(sorted(present.union(refresh)))
            companions.append(
                _Target(
                    daily_key,
                    year,
                    month,
                    expected,
                    tuple(sorted(refresh)),
                    existing,
                )
            )
        return tuple(companions)

    def _publish_fetched(self, target: _Target, batches: tuple[BarBatch, ...]) -> None:
        """合并 existing 与 provider 批次，经 store.publish 六项校验后注册分区。"""
        bars = self._merged_fetched_bars(target, batches)
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

    def _merged_fetched_bars(
        self,
        target: _Target,
        batches: tuple[BarBatch, ...],
    ) -> tuple[CanonicalBar, ...]:
        """在任何分区写入前验证 provider 批次可构成完整目标窗口。"""
        merged = {bar.bar_end: bar for bar in target.existing}
        for batch in batches:
            for bar in batch.bars:
                merged[bar.bar_end] = bar
        bars = tuple(merged[item] for item in target.expected if item in merged)
        if tuple(bar.bar_end for bar in bars) != target.expected:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        return bars

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
        source = tuple(
            bar
            for bar in source
            if any(session.start < bar.bar_end <= session.end for session in sessions)
        )
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
        """只读取通过共享 Catalog 完整性校验的唯一月分区。"""
        rows = tuple(
            item
            for item in self.catalog.all_partitions(key)
            if item.year == year and item.month == month
        )
        if len(rows) != 1:
            return ()
        try:
            return self.store.read_catalog_partition(rows[0])
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
        row = rows[0]
        if len(rows) != 1:
            return (), "PARTITION_CATALOG_MISMATCH"
        try:
            values = self.store.read_catalog_partition(row)
        except StorageError as exc:
            return (), getattr(exc, "code", "PARTITION_UNREADABLE")
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


def _contract_warmup_target_payload(target: _Target) -> Mapping[str, object]:
    """稳定描述 warm-up 月目标的完整 expected 与实际 missing 边界。"""
    return {
        "dataset": target.key.as_tuple(),
        "year": target.year,
        "month": target.month,
        "expected_start": target.expected[0].isoformat(),
        "expected_end": target.expected[-1].isoformat(),
        "expected_bar_count": len(target.expected),
        "missing_start": target.missing[0].isoformat(),
        "missing_end": target.missing[-1].isoformat(),
        "missing_bar_count": len(target.missing),
    }


def _contract_warmup_hash_target_payload(target: _Target) -> Mapping[str, object]:
    """Plan identity additionally locks every sorted expected/missing timestamp."""
    return {
        **_contract_warmup_target_payload(target),
        "expected_bar_ends": tuple(
            item.isoformat() for item in sorted(target.expected)
        ),
        "missing_bar_ends": tuple(
            item.isoformat() for item in sorted(target.missing)
        ),
    }


def _contract_warmup_fetch_groups(
    targets: tuple[_Target, ...],
) -> tuple[tuple[_Target, ...], ...]:
    """Batch only D1/W1 targets connected by an affected ISO week."""
    parent = list(range(len(targets)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    daily = tuple(
        index
        for index, target in enumerate(targets)
        if target.key.frequency is BarFrequency.D1
    )
    weekly = tuple(
        index
        for index, target in enumerate(targets)
        if target.key.frequency is BarFrequency.W1
    )
    weeks = {
        index: {
            value.astimezone(SHANGHAI).date().isocalendar()[:2]
            for value in targets[index].missing
        }
        for index in (*daily, *weekly)
    }
    for daily_index in daily:
        for weekly_index in weekly:
            if (
                _family(targets[daily_index].key)
                == _family(targets[weekly_index].key)
                and weeks[daily_index].intersection(weeks[weekly_index])
            ):
                union(daily_index, weekly_index)

    grouped: dict[int, list[tuple[int, _Target]]] = {}
    for index, target in enumerate(targets):
        grouped.setdefault(find(index), []).append((index, target))
    return tuple(
        tuple(target for _index, target in sorted(group))
        for group in sorted(grouped.values(), key=lambda group: min(group)[0])
    )


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
