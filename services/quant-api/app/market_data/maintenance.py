from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.market_data.aggregation import aggregate_from_1m, session_digest
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
from app.market_data.service import MarketDataService, MarketDataError
from app.market_data.storage import (
    CanonicalMonthlyStore,
    PublishRequest,
    SourceMetadata,
    StagedPublication,
    StorageError,
)


class CoverageSource(Protocol):
    def product_start(self, symbol: str) -> date: ...
    def latest_complete_day(self, products: tuple[str, ...]) -> date: ...
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
    def sessions(self, key: DatasetKey, year: int, month: int): ...


class MetadataPort(Protocol):
    def synchronize(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> date: ...


class BarSource(Protocol):
    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch: ...


class LegacySource(Protocol):
    def fetch(
        self, key: DatasetKey, expected: tuple[datetime, ...]
    ) -> BarBatch | None: ...


@dataclass(frozen=True, slots=True)
class BarBatch:
    bars: tuple[CanonicalBar, ...]
    source_digest: str
    source_kind: str = "rqdata"


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    products: tuple[str, ...]
    since: date | None
    through: date | None
    apply: bool = False


@dataclass(frozen=True, slots=True)
class BootstrapRequest:
    products: tuple[str, ...]
    through: date | None
    apply: bool = False


@dataclass(frozen=True, slots=True)
class ExactRepairItem:
    dataset: DatasetKey
    year: int
    month: int
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("REPAIR_WINDOW_INVALID")
        if not 1 <= self.month <= 12:
            raise ValueError("REPAIR_MONTH_INVALID")


@dataclass(frozen=True, slots=True)
class RepairRequest:
    items: tuple[ExactRepairItem, ...]
    apply: bool = False


@dataclass(frozen=True, slots=True)
class AuditRequest:
    products: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    dataset: tuple[str, str, str, str]
    year: int
    month: int


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    action: str
    status: str
    through: date | None
    planned: int
    applied: int
    blocked: int
    failed: int
    provider_requests: int
    findings: tuple[AuditFinding, ...] = ()
    failures: tuple[Mapping[str, object], ...] = ()
    target_windows: tuple[Mapping[str, object], ...] = ()

    def as_payload(self) -> dict[str, object]:
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
            "targets": [dict(item) for item in self.target_windows],
            "finding_count": len(self.findings),
            "findings": [
                {
                    "code": item.code,
                    "dataset": item.dataset,
                    "year": item.year,
                    "month": item.month,
                }
                for item in self.findings
            ],
            "failures": [dict(item) for item in self.failures],
        }


@dataclass(frozen=True, slots=True)
class _Target:
    key: DatasetKey
    year: int
    month: int
    expected: tuple[datetime, ...]
    missing: tuple[datetime, ...]
    existing: tuple[CanonicalBar, ...]
    gap_clear_start: datetime | None = None
    gap_clear_end: datetime | None = None


_FREQUENCY_ORDER = (
    BarFrequency.M1,
    BarFrequency.D1,
    BarFrequency.W1,
    BarFrequency.M5,
    BarFrequency.M15,
    BarFrequency.M30,
    BarFrequency.H1,
)


class HistoricalDataManager:
    """Single application service for update/bootstrap/repair/audit."""

    def __init__(
        self,
        *,
        catalog: MarketCatalog,
        store: CanonicalMonthlyStore,
        coverage: CoverageSource,
        metadata: MetadataPort,
        provider: BarSource,
        legacy: LegacySource | None = None,
    ) -> None:
        self.catalog = catalog
        self.store = store
        self.coverage = coverage
        self.metadata = metadata
        self.provider = provider
        self.legacy = legacy
        self._metadata_watermarks: set[tuple[tuple[str, ...], date]] = set()

    def update(self, request: UpdateRequest) -> MaintenanceResult:
        through = request.through or self.coverage.latest_complete_day(request.products)
        if request.since is not None and request.since > through:
            raise ValueError("UPDATE_WINDOW_INVALID")
        watermark = (request.products, through)
        if request.apply and (
            watermark not in self._metadata_watermarks
            and not self.coverage.metadata_complete(request.products, through)
        ):
            through = self.metadata.synchronize(
                request.products,
                through,
                {symbol: self.coverage.product_start(symbol) for symbol in request.products},
            )
            self._metadata_watermarks.add((request.products, through))
        if request.apply:
            self.coverage.require_historical_session_facts(request.products, through)
            return self._execute_streaming(
                "update",
                request.products,
                request.since,
                through,
                use_legacy=False,
            )
        targets = self._plan(request.products, request.since, through)
        return self._execute("update", targets, through, apply=False, use_legacy=False)

    def bootstrap(self, request: BootstrapRequest) -> MaintenanceResult:
        through = request.through or self.coverage.latest_complete_day(request.products)
        watermark = (request.products, through)
        if request.apply and (
            watermark not in self._metadata_watermarks
            and not self.coverage.metadata_complete(request.products, through)
        ):
            through = self.metadata.synchronize(
                request.products,
                through,
                {symbol: self.coverage.product_start(symbol) for symbol in request.products},
            )
            self._metadata_watermarks.add((request.products, through))
        if request.apply:
            self.coverage.require_historical_session_facts(request.products, through)
            return self._execute_streaming(
                "bootstrap",
                request.products,
                None,
                through,
                use_legacy=True,
            )
        targets = self._plan(request.products, None, through)
        return self._execute("bootstrap", targets, through, apply=False, use_legacy=True)

    def repair(self, request: RepairRequest) -> MaintenanceResult:
        targets: list[_Target] = []
        for item in request.items:
            expected = self.coverage.expected_bar_ends(
                item.dataset,
                item.year,
                item.month,
                item.start.date(),
                item.end.date(),
            )
            existing = self._read_existing(item.dataset, item.year, item.month)
            month_expected = tuple(sorted(
                {bar.bar_end for bar in existing} | set(expected)
            ))
            targets.append(
                _Target(
                    item.dataset,
                    item.year,
                    item.month,
                    month_expected,
                    expected,
                    existing,
                    item.start,
                    item.end,
                )
            )
        result = self._execute(
            "repair",
            tuple(targets),
            max((item.end.date() for item in request.items), default=None),
            apply=request.apply,
            use_legacy=False,
        )
        if request.apply and result.failed == 0 and result.blocked == 0:
            for item in request.items:
                self.catalog.clear_gaps(item.dataset, item.start, item.end)
            self.catalog.session.commit()
        return result

    def audit(self, request: AuditRequest) -> MaintenanceResult:
        through = self.coverage.latest_complete_day(request.products)
        findings: list[AuditFinding] = []
        for symbol in request.products:
            start = self.coverage.product_start(symbol)
            missing_map = self.catalog.missing_main_map_days(symbol, start, through)
            if missing_map:
                first = missing_map[0]
                findings.append(
                    AuditFinding(
                        "MAIN_CONTRACT_MAP_MISSING",
                        ("metadata", symbol, "rank1", "1d"),
                        first.year,
                        first.month,
                    )
                )
            missing_specs = self.catalog.missing_contract_spec_days(symbol, start, through)
            if missing_specs:
                first = missing_specs[0]
                findings.append(
                    AuditFinding(
                        "CONTRACT_SPEC_MISSING",
                        ("metadata", symbol, "contract_specs", "1d"),
                        first.year,
                        first.month,
                    )
                )
        for key, year, month, expected in self._desired_months(request.products, through):
            if not expected:
                continue
            if self.catalog.has_gap(
                key,
                expected[0],
                expected[-1],
            ):
                findings.append(AuditFinding("DATA_GAP_PRESENT", key.as_tuple(), year, month))
            existing = self._read_existing(key, year, month)
            if tuple(bar.bar_end for bar in existing) != expected:
                findings.append(
                    AuditFinding("EXPECTED_PARTITION_MISSING", key.as_tuple(), year, month)
                )
        return MaintenanceResult(
            action="audit",
            status="passed" if not findings else "failed",
            through=through,
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
        return tuple(self._iter_targets(products, since, through))

    def _iter_targets(
        self,
        products: tuple[str, ...],
        since: date | None,
        through: date,
        *,
        frequencies: frozenset[BarFrequency] | None = None,
    ):
        for key, year, month, expected in self._desired_months(
            products,
            through,
            frequencies=frequencies,
        ):
            if not expected:
                continue
            existing = self._read_existing(key, year, month)
            present = {bar.bar_end for bar in existing}
            missing = tuple(
                item
                for item in expected
                if item not in present and (since is None or item.date() >= since)
            )
            if missing:
                yield _Target(key, year, month, expected, missing, existing)

    def _desired_months(
        self,
        products: tuple[str, ...],
        through: date,
        *,
        frequencies: frozenset[BarFrequency] | None = None,
    ):
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
        use_legacy: bool,
    ) -> MaintenanceResult:
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
            use_legacy=use_legacy,
        )

    def _execute_streaming(
        self,
        action: str,
        products: tuple[str, ...],
        since: date | None,
        through: date,
        *,
        use_legacy: bool,
    ) -> MaintenanceResult:
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
            use_legacy=use_legacy,
        )

    def _execute_apply(
        self,
        action: str,
        direct,
        derived,
        through: date | None,
        *,
        use_legacy: bool,
    ) -> MaintenanceResult:
        planned = 0
        applied = 0
        blocked = 0
        provider_requests = 0
        failures: list[Mapping[str, object]] = []
        failed_families: set[tuple[str, str, str]] = set()
        for target in direct:
            planned += 1
            try:
                batches: list[BarBatch] = []
                remaining = target.missing
                if use_legacy and self.legacy is not None:
                    legacy_batch = self.legacy.fetch(target.key, remaining)
                    if legacy_batch is not None:
                        batches.append(legacy_batch)
                        legacy_ends = {bar.bar_end for bar in legacy_batch.bars}
                        remaining = tuple(item for item in remaining if item not in legacy_ends)
                if remaining:
                    batch = self.provider.fetch(target.key, remaining)
                    provider_requests += 1
                    batches.append(batch)
                self._publish_direct(target, tuple(batches))
                applied += 1
            except Exception as exc:  # noqa: BLE001 - isolate one product/dataset
                if _is_global_failure(exc):
                    raise
                failed_families.add(_family(target.key))
                failures.append(_failure(target, exc))
                self.catalog.session.rollback()
                self._record_gap(target, exc)
            if planned == 1 or planned % 100 == 0:
                print(
                    f"maintenance {action} direct planned={planned} applied={applied} "
                    f"failed={len(failures)} provider_requests={provider_requests}",
                    flush=True,
                )
        for target in derived:
            planned += 1
            if _family(target.key) in failed_families:
                blocked += 1
                self._record_gap(target, StorageError("SOURCE_1M_BLOCKED"))
                continue
            try:
                self._publish_derived(target)
                applied += 1
            except Exception as exc:  # noqa: BLE001 - isolate one product/dataset
                if _is_global_failure(exc):
                    raise
                failures.append(_failure(target, exc))
                self.catalog.session.rollback()
                self._record_gap(target, exc)
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

    def _record_gap(self, target: _Target, exc: Exception) -> None:
        if not target.missing:
            return
        width = _frequency_delta(target.key.frequency)
        self.catalog.add_gap(
            target.key,
            target.missing[0] - width,
            target.missing[-1],
            str(getattr(exc, "code", type(exc).__name__))[:64],
        )
        self.catalog.session.commit()

    def _publish_direct(self, target: _Target, batches: tuple[BarBatch, ...]) -> None:
        merged = {bar.bar_end: bar for bar in target.existing}
        source_kinds: set[str] = set()
        digests: list[str] = []
        for batch in batches:
            source_kinds.add(batch.source_kind)
            digests.append(batch.source_digest)
            for bar in batch.bars:
                merged[bar.bar_end] = bar
        bars = tuple(merged[item] for item in target.expected if item in merged)
        if tuple(bar.bar_end for bar in bars) != target.expected:
            raise StorageError("TARGET_WINDOW_INCOMPLETE")
        if source_kinds == {"legacy_staging"}:
            source_kind = "legacy_staging"
        elif source_kinds <= {"rqdata"}:
            source_kind = "rqdata"
        else:
            source_kind = "bootstrap_mixed"
        digest = _combined_digest(digests or ["0" * 64])
        staged = self.store.stage(
            PublishRequest(
                target.key,
                target.year,
                target.month,
                bars,
                target.expected,
                SourceMetadata(source_kind=source_kind, source_digest=digest),
            )
        )
        self._commit_staged(staged, target)

    def _publish_derived(self, target: _Target) -> None:
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
            for session in self.coverage.sessions(target.key, target.year, target.month)
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
        source_partitions = self.catalog.all_partitions(source_key)
        digests = tuple(
            item.manifest_digest
            for item in source_partitions
            if item.year == target.year and item.month == target.month
        )
        staged = self.store.stage(
            PublishRequest(
                target.key,
                target.year,
                target.month,
                bars,
                target.expected,
                SourceMetadata(
                    source_kind="derived_1m",
                    source_digest=_combined_digest(digests),
                    source_1m_digests=digests,
                    session_digest=session_digest(sessions),
                ),
            )
        )
        self._commit_staged(staged, target)

    def _commit_staged(self, staged: StagedPublication, target: _Target) -> None:
        try:
            self.catalog.register_partition(staged.partition)
            self.catalog.clear_gaps(
                target.key,
                target.gap_clear_start
                or target.expected[0] - _frequency_delta(target.key.frequency),
                target.gap_clear_end or target.expected[-1],
            )
            self._strict_verify(target)
            self.catalog.session.commit()
        except Exception:
            self.catalog.session.rollback()
            self.store.rollback(staged)
            raise
        self.store.finalize(staged)

    def _strict_verify(self, target: _Target) -> None:
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
                    start=target.expected[0] - _frequency_delta(target.key.frequency),
                    end=target.expected[-1],
                )
            )
        except MarketDataError as exc:
            raise StorageError("STRICT_READ_VERIFICATION_FAILED") from exc
        if tuple(bar.bar_end for bar in result.bars) != target.expected:
            raise StorageError("STRICT_READ_VERIFICATION_FAILED")

    def _read_existing(self, key: DatasetKey, year: int, month: int) -> tuple[CanonicalBar, ...]:
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


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def _family(key: DatasetKey) -> tuple[str, str, str]:
    return key.kind.value, key.symbol, key.series_or_contract


def _failure(target: _Target, exc: Exception) -> Mapping[str, object]:
    return {
        "dataset": target.key.as_tuple(),
        "year": target.year,
        "month": target.month,
        "reason_code": getattr(exc, "code", type(exc).__name__),
    }


def _target_payload(target: _Target) -> Mapping[str, object]:
    return {
        "dataset": target.key.as_tuple(),
        "year": target.year,
        "month": target.month,
        "window_start": target.missing[0].isoformat(),
        "window_end": target.missing[-1].isoformat(),
        "missing_bar_count": len(target.missing),
    }


def _is_global_failure(exc: Exception) -> bool:
    if isinstance(exc, SQLAlchemyError):
        return True
    return getattr(exc, "code", None) in {
        "ATOMIC_PUBLISH_FAILED",
        "CANONICAL_ROOT_ESCAPE",
        "PARTITION_URI_ESCAPE",
        "PARTITION_OUTSIDE_CANONICAL_ROOT",
    }


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    return {
        BarFrequency.M1: timedelta(minutes=1),
        BarFrequency.M5: timedelta(minutes=5),
        BarFrequency.M15: timedelta(minutes=15),
        BarFrequency.M30: timedelta(minutes=30),
        BarFrequency.H1: timedelta(hours=1),
        BarFrequency.D1: timedelta(days=1),
        BarFrequency.W1: timedelta(days=7),
    }[frequency]


def _combined_digest(values) -> str:
    encoded = json.dumps(sorted(values), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
