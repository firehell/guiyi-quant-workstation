"""Sectioned, read-only Newow product orchestration."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
import json
import sys

from guiyi_quant.newow.composite_explanation import calculate_composite_explanation
from guiyi_quant.newow.context_alignment import ContextSnapshot
from guiyi_quant.newow.page_comparator import (
    ComparatorOwnerSegment,
    PageComparatorResult,
    VerifiedPageComparatorEvidence,
    compare_page_windows,
)
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_auxiliary import calculate_auxiliary_component
from guiyi_quant.newow.product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
    StrategyReplay,
)
from guiyi_quant.newow.product_identity import (
    FUTURES_ADAPTATION_VERSION,
    REFERENCE_MODEL_VERSION,
    utc_timestamp,
)
from guiyi_quant.newow.reference_statistics import (
    PerformanceWindow,
    ReferenceSummary,
    summarize_reference,
)
from guiyi_quant.newow.reference_trades import (
    ReferenceProjection,
    ReferenceTradeProjector,
)
from guiyi_quant.newow.target_absorb_display import calculate_target_absorb

from .product_query import NewowProductQuery, ProductReadWindow
from .product_reader import (
    NewowProductReadCancelled,
    NewowProductReader,
    ProductReadSet,
    ResolvedPerformanceWindow,
)
from .inflight import InFlightCoordinator
from .resource_gate import HeavyResourceGate
from .snapshot_cache import SnapshotCache
from .source_facts import (
    SourceFact,
    build_composite_inputs,
    target_absorb_available_sources,
    target_absorb_gap_sources,
)


SCHEMA_VERSION = "newow_product_detail_v1"


class ProductSection(StrEnum):
    CHART = "chart"
    AUXILIARY = "auxiliary"
    REFERENCE = "reference"
    EXPLANATION = "explanation"
    COMPARATOR = "comparator"


class AuxiliaryComponent(StrEnum):
    MAIN_FORCE_CONTROL = "main_force_control"
    UP_DOWN_ENERGY = "up_down_energy"
    ZHAOYAO_MIRROR = "zhaoyao_mirror"
    CUP_HANDLE = "cup_handle"


@dataclass(frozen=True, slots=True)
class ProductServiceQuery:
    product: str
    strategy: ProductStrategy
    frequency: ProductFrequency
    section: ProductSection = ProductSection.CHART
    since: date | None = None
    through: date | None = None
    performance_since: date | None = None
    performance_through: date | None = None
    as_of: datetime | None = None
    series_kind: str = "actual_dominant"
    chart_limit: int = 500
    chart_before: str | None = None
    component: AuxiliaryComponent | None = None
    history_limit: int = 50
    history_before: str | None = None
    snapshot_token: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy", ProductStrategy(self.strategy))
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(self, "section", ProductSection(self.section))
        if self.component is not None:
            object.__setattr__(self, "component", AuxiliaryComponent(self.component))
        if self.series_kind != "actual_dominant":
            raise ValueError("NEWOW_INVALID_SERIES")
        if (self.since is None) != (self.through is None):
            raise ValueError("NEWOW_INVALID_RANGE")
        if (
            self.since is not None
            and self.through is not None
            and self.since > self.through
        ):
            raise ValueError("NEWOW_INVALID_RANGE")
        if (self.performance_since is None) != (self.performance_through is None):
            raise ValueError("NEWOW_INVALID_PERFORMANCE_WINDOW")
        if (
            self.performance_since is not None
            and self.performance_through is not None
            and self.performance_since > self.performance_through
        ):
            raise ValueError("NEWOW_INVALID_PERFORMANCE_WINDOW")
        if type(self.chart_limit) is not int or not 1 <= self.chart_limit <= 2000:
            raise ValueError("NEWOW_INVALID_CHART_LIMIT")
        if type(self.history_limit) is not int or not 1 <= self.history_limit <= 200:
            raise ValueError("NEWOW_INVALID_HISTORY_LIMIT")
        if self.as_of is not None:
            object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        if self.section is ProductSection.AUXILIARY:
            if self.component is None:
                raise ValueError("NEWOW_AUXILIARY_COMPONENT_REQUIRED")
        elif self.component is not None:
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
        if self.section is not ProductSection.CHART and self.chart_before is not None:
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
        if self.section is not ProductSection.CHART and self.chart_limit != 500:
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
        if self.section is not ProductSection.REFERENCE and (
            self.performance_since is not None
            or self.history_before is not None
            or self.history_limit != 50
        ):
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
        if (
            self.section
            in {
                ProductSection.REFERENCE,
                ProductSection.EXPLANATION,
                ProductSection.COMPARATOR,
            }
            and self.since is not None
        ):
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")


@dataclass(frozen=True, slots=True)
class ChartSectionValue:
    bars: tuple[ProductBar, ...]
    replay: StrategyReplay
    next_before: str | None
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReferenceSectionValue:
    projection: ReferenceProjection
    summary: ReferenceSummary
    items: tuple[object, ...]
    next_before: str | None
    requested_window: ProductReadWindow
    actual_available_through: date
    reference_cutoff: datetime
    reference_input_sha256: str


@dataclass(frozen=True, slots=True)
class ExplanationSectionValue:
    context: ContextSnapshot
    composite: object
    target_absorb: object
    sources: tuple[SourceFact, ...]


@dataclass(frozen=True, slots=True)
class SectionDelivery:
    delivery: str
    status: FeatureStatus | None
    value: object | None


@dataclass(frozen=True, slots=True)
class ProductResultMeta:
    schema_version: str
    identity: ProductIdentity
    as_of: datetime
    read_at: datetime
    input_content_sha256: str
    data_revision_identity: None
    snapshot_token: str | None
    reference_model_version: str = REFERENCE_MODEL_VERSION
    futures_adaptation_version: str = FUTURES_ADAPTATION_VERSION


@dataclass(frozen=True, slots=True)
class NewowProductResult:
    meta: ProductResultMeta
    section: ProductSection
    chart: SectionDelivery
    auxiliary: SectionDelivery
    reference: SectionDelivery
    explanation: SectionDelivery
    comparator: SectionDelivery


class NewowProductServiceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


ReaderFactory = Callable[
    [tuple[ProductFrequency, ...], Callable[[], bool] | None], NewowProductReader
]


def _ready(
    evidence: EvidenceStatus = EvidenceStatus.ACTIVE_CODE_VERIFIED,
) -> FeatureStatus:
    return FeatureStatus(FeatureRuntimeStatus.READY, evidence)


def _not_requested() -> SectionDelivery:
    return SectionDelivery("not_requested", None, None)


def _fingerprint(read: ProductReadSet, identity: ProductIdentity) -> str:
    bars = []
    for frequency in sorted(read.bars_by_frequency, key=str):
        for item in read.bars_by_frequency[frequency]:
            bar = item.bar
            bars.append(
                (
                    frequency.value,
                    bar.physical_contract,
                    bar.segment_id,
                    bar.trading_day.isoformat(),
                    bar.bar_end.isoformat(),
                    str(bar.open),
                    str(bar.high),
                    str(bar.low),
                    str(bar.close),
                    bar.volume,
                    bar.open_interest,
                    bar.source_identity,
                    bar.observation_eligible,
                )
            )
    owners = tuple(
        (
            owner.contract,
            owner.start_trading_day.isoformat(),
            owner.end_trading_day.isoformat(),
        )
        for owner in read.owners
    )
    boundaries = tuple(
        (
            item.old_contract,
            item.new_contract,
            item.old_segment_id,
            item.new_segment_id,
            item.effective_trading_day.isoformat(),
            item.effective_at.isoformat(),
            item.source_identity,
        )
        for item in read.boundaries
    )
    payload = json.dumps(
        {
            "identity": (
                identity.product,
                identity.strategy.value,
                identity.frequency.value,
                identity.formula_versions,
                identity.profile_id,
            ),
            "as_of": read.as_of.isoformat(),
            "bars": bars,
            "owners": owners,
            "boundaries": boundaries,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode()).hexdigest()


def _cursor(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(
    value: str, expected_kind: str, fingerprint: str, page_identity: str
) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise NewowProductServiceError("NEWOW_CURSOR_INVALID")
    try:
        raw = urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise NewowProductServiceError("NEWOW_CURSOR_INVALID") from error
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("kind") != expected_kind
        or payload.get("fingerprint") != fingerprint
        or payload.get("page_identity") != page_identity
        or not isinstance(payload.get("before"), str)
    ):
        raise NewowProductServiceError("NEWOW_CURSOR_GENERATION_CONFLICT")
    return payload["before"]


def _snapshot_namespace(identity: ProductIdentity, as_of: datetime) -> str:
    payload = {
        "identity": (
            identity.product,
            identity.strategy.value,
            identity.frequency.value,
            identity.profile_id,
            identity.formula_versions,
        ),
        "as_of": as_of.isoformat(),
    }
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _dependency_proof(read: ProductReadSet) -> dict[str, str]:
    proof: dict[str, str] = {}
    for frequency in sorted(read.bars_by_frequency, key=str):
        for item in read.bars_by_frequency[frequency]:
            bar = item.bar
            key = "|".join(
                (
                    frequency.value,
                    bar.physical_contract,
                    bar.segment_id,
                    bar.bar_end.isoformat(),
                )
            )
            value = "|".join(
                (
                    bar.trading_day.isoformat(),
                    str(bar.open),
                    str(bar.high),
                    str(bar.low),
                    str(bar.close),
                    str(bar.volume),
                    str(bar.open_interest),
                    bar.source_identity,
                    str(bar.observation_eligible),
                )
            )
            proof[key] = sha256(value.encode()).hexdigest()
    return proof


def _retained_size(value: object, seen: set[int] | None = None) -> int:
    seen = seen or set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        return size + sum(
            _retained_size(getattr(value, field.name), seen) for field in fields(value)
        )
    if isinstance(value, Mapping):
        return size + sum(
            _retained_size(key, seen) + _retained_size(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return size + sum(_retained_size(item, seen) for item in value)
    return size


class NewowProductService:
    def __init__(
        self,
        reader_factory: ReaderFactory,
        *,
        cache: SnapshotCache | None = None,
        heavy_gate: HeavyResourceGate | None = None,
        inflight: InFlightCoordinator | None = None,
        now: Callable[[], datetime] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._reader_factory = reader_factory
        self._cache = cache or SnapshotCache()
        self._gate = heavy_gate or HeavyResourceGate()
        self._inflight = inflight or InFlightCoordinator()
        self._now = now or (lambda: datetime.now(UTC))
        self._cancelled = cancelled

    def query(self, request: ProductServiceQuery) -> NewowProductResult:
        if not isinstance(request, ProductServiceQuery):
            raise NewowProductServiceError("NEWOW_INVALID_QUERY")
        as_of = utc_timestamp(request.as_of or self._now())
        if as_of > utc_timestamp(self._now()):
            raise NewowProductServiceError("NEWOW_INVALID_AS_OF")
        key = (request, as_of)
        return self._inflight.execute(
            key,
            lambda shared_cancelled: self._query(request, as_of, shared_cancelled),
            self._cancelled,
        )

    def _query(
        self,
        request: ProductServiceQuery,
        as_of: datetime,
        cancelled: Callable[[], bool],
    ) -> NewowProductResult:
        self._check_cancelled(cancelled)
        context = (
            tuple(ProductFrequency)
            if request.section is ProductSection.EXPLANATION
            else ()
        )
        reader = self._reader_factory(context, cancelled)
        resolved: ResolvedPerformanceWindow | None = None
        if request.section is ProductSection.REFERENCE:
            resolved = reader.resolve_performance_window(
                request.product,
                request.frequency,
                request.performance_since,
                request.performance_through,
                as_of,
            )
            window = ProductReadWindow(
                resolved.requested_since, resolved.actual_through
            )
            read_as_of = resolved.cutoff
        elif request.since is not None and request.through is not None:
            window = ProductReadWindow(request.since, request.through)
            read_as_of = as_of
        else:
            window = reader.resolve_chart_window(
                request.product, request.frequency, request.chart_limit, as_of
            )
            read_as_of = as_of
        low_query = NewowProductQuery(
            request.product,
            request.strategy,
            request.frequency,
            window.since,
            window.through,
            window.since,
            window.through,
            read_as_of,
            history_limit=request.history_limit,
            history_before=request.history_before,
        )
        read = reader.load(low_query, read_as_of)
        self._check_cancelled(cancelled)
        if resolved is not None and request.frequency is ProductFrequency.WEEKLY:
            completed = tuple(
                item.bar
                for item in read.replay_bars
                if item.bar.observation_eligible
                and item.bar.bar_end <= resolved.cutoff
                and item.bar.trading_day <= resolved.requested_through
            )
            if not completed:
                raise NewowProductServiceError("NEWOW_COMPLETE_PERIOD_MISSING")
            last_week = completed[-1]
            weekly_complete = last_week.trading_day == resolved.actual_through
            resolved = replace(
                resolved,
                actual_through=last_week.trading_day,
                cutoff=last_week.bar_end,
                complete=weekly_complete,
                reason_code=(
                    None if weekly_complete else "NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL"
                ),
            )
        identity = build_product_identity(
            request.product, request.strategy, request.frequency
        )
        fact_key = _fingerprint(read, identity)
        common_key = _snapshot_namespace(identity, as_of)
        proof = _dependency_proof(read)
        page_identity = self._page_identity(request, window, resolved, as_of)
        section_key = self._section_key(
            request, window, resolved, fact_key, page_identity
        )
        if request.snapshot_token is not None:
            if not self._cache.token_is_compatible(
                request.snapshot_token, common_key, proof
            ):
                raise NewowProductServiceError("NEWOW_SNAPSHOT_GENERATION_CONFLICT")
        cached = self._cache.get(common_key, section_key)
        if isinstance(cached, NewowProductResult):
            return replace(
                cached, meta=replace(cached.meta, read_at=utc_timestamp(self._now()))
            )
        result = self._calculate(
            request,
            read,
            identity,
            fact_key,
            page_identity,
            resolved,
            cancelled,
            as_of,
        )
        token = None
        if self._cacheable(result):
            token = self._cache.put(
                common_key,
                section_key,
                result,
                _retained_size(result),
                token=request.snapshot_token,
                proof=proof,
            )
        if token is not None:
            result = NewowProductResult(
                ProductResultMeta(
                    result.meta.schema_version,
                    result.meta.identity,
                    result.meta.as_of,
                    result.meta.read_at,
                    result.meta.input_content_sha256,
                    None,
                    token,
                ),
                result.section,
                result.chart,
                result.auxiliary,
                result.reference,
                result.explanation,
                result.comparator,
            )
            self._cache.put(
                common_key,
                section_key,
                result,
                _retained_size(result),
                token=token,
                proof=proof,
            )
        return result

    @staticmethod
    def _check_cancelled(cancelled: Callable[[], bool]) -> None:
        if cancelled():
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")

    def _section_key(
        self,
        request: ProductServiceQuery,
        window: ProductReadWindow,
        resolved: ResolvedPerformanceWindow | None,
        fact_key: str,
        page_identity: str,
    ) -> tuple[object, ...]:
        return (
            fact_key,
            page_identity,
            request.section.value,
            request.component.value if request.component else None,
            window.since.isoformat(),
            window.through.isoformat(),
            resolved.requested_through.isoformat() if resolved else None,
            request.chart_limit,
            request.chart_before,
            request.history_limit,
            request.history_before,
        )

    def _page_identity(
        self,
        request: ProductServiceQuery,
        window: ProductReadWindow,
        resolved: ResolvedPerformanceWindow | None,
        as_of: datetime,
    ) -> str:
        payload = (
            request.product,
            request.strategy.value,
            request.frequency.value,
            request.section.value,
            request.component.value if request.component else None,
            window.since.isoformat(),
            window.through.isoformat(),
            resolved.requested_since.isoformat() if resolved else None,
            resolved.requested_through.isoformat() if resolved else None,
            as_of.isoformat(),
            request.chart_limit,
            request.history_limit,
        )
        return sha256(repr(payload).encode()).hexdigest()

    @staticmethod
    def _cacheable(result: NewowProductResult) -> bool:
        delivery = getattr(result, result.section.value)
        return (
            delivery.delivery == "delivered"
            and delivery.status is not None
            and delivery.status.status is FeatureRuntimeStatus.READY
        )

    def _calculate(
        self,
        request: ProductServiceQuery,
        read: ProductReadSet,
        identity: ProductIdentity,
        fact_key: str,
        page_identity: str,
        resolved: ResolvedPerformanceWindow | None,
        cancelled: Callable[[], bool],
        request_as_of: datetime,
    ) -> NewowProductResult:
        self._check_cancelled(cancelled)
        deliveries = {section: _not_requested() for section in ProductSection}
        if request.section is ProductSection.CHART:
            deliveries[request.section] = self._chart(
                request, read, identity, fact_key, page_identity
            )
        elif request.section is ProductSection.AUXILIARY:
            assert request.component is not None
            layer = calculate_auxiliary_component(
                identity, read.replay_bars, request.component.value, as_of=read.as_of
            )
            self._check_cancelled(cancelled)
            deliveries[request.section] = SectionDelivery(
                "delivered", layer.availability, layer
            )
        elif request.section is ProductSection.REFERENCE:
            assert resolved is not None
            with self._gate.acquire(cancelled):
                deliveries[request.section] = self._reference(
                    request, read, identity, fact_key, page_identity, resolved
                )
        elif request.section is ProductSection.EXPLANATION:
            deliveries[request.section] = self._explanation(read, identity)
        else:
            with self._gate.acquire(cancelled):
                deliveries[request.section] = self._comparator(read, identity)
        self._check_cancelled(cancelled)
        meta = ProductResultMeta(
            SCHEMA_VERSION,
            identity,
            request_as_of,
            utc_timestamp(self._now()),
            fact_key,
            None,
            None,
        )
        return NewowProductResult(
            meta,
            request.section,
            deliveries[ProductSection.CHART],
            deliveries[ProductSection.AUXILIARY],
            deliveries[ProductSection.REFERENCE],
            deliveries[ProductSection.EXPLANATION],
            deliveries[ProductSection.COMPARATOR],
        )

    def _chart(
        self,
        request: ProductServiceQuery,
        read: ProductReadSet,
        identity: ProductIdentity,
        fact_key: str,
        page_identity: str,
    ) -> SectionDelivery:
        replay = replay_strategy(identity, read.replay_bars)
        frames = tuple(
            frame
            for frame in replay.frames
            if frame.bar.bar.observation_eligible
            and read.display_window.since
            <= frame.bar.bar.trading_day
            <= read.display_window.through
        )
        if request.chart_before is not None:
            before = datetime.fromisoformat(
                _decode_cursor(
                    request.chart_before, "chart", fact_key, page_identity
                ).replace("Z", "+00:00")
            )
            frames = tuple(frame for frame in frames if frame.bar.bar.bar_end < before)
        selected = frames[-request.chart_limit :]
        has_more = len(frames) > len(selected)
        next_before = (
            _cursor(
                {
                    "v": 1,
                    "kind": "chart",
                    "fingerprint": fact_key,
                    "page_identity": page_identity,
                    "before": selected[0].bar.bar.bar_end.isoformat(),
                }
            )
            if has_more and selected
            else None
        )
        selected_ids = {frame.bar.bar.bar_end for frame in selected}
        visible = StrategyReplay(
            identity,
            selected,
            tuple(
                action for action in replay.actions if action.bar_end in selected_ids
            ),
            tuple(hint for hint in replay.hints if hint.bar_end in selected_ids),
            replay.diagnostics,
        )
        status = (
            selected[-1].availability
            if selected
            else FeatureStatus(
                FeatureRuntimeStatus.WARMING,
                EvidenceStatus.ACTIVE_CODE_VERIFIED,
                "NEWOW_CHART_WARMING",
            )
        )
        return SectionDelivery(
            "delivered",
            status,
            ChartSectionValue(
                tuple(frame.bar for frame in selected),
                visible,
                next_before,
                replay.diagnostics,
            ),
        )

    def _reference(
        self,
        request: ProductServiceQuery,
        read: ProductReadSet,
        identity: ProductIdentity,
        fact_key: str,
        page_identity: str,
        resolved: ResolvedPerformanceWindow,
    ) -> SectionDelivery:
        replay = replay_strategy(identity, read.replay_bars)
        projection = ReferenceTradeProjector().project(
            replay, read.boundaries, resolved.cutoff
        )
        summary = summarize_reference(
            projection,
            PerformanceWindow(
                resolved.requested_since, resolved.requested_through, resolved.cutoff
            ),
        )
        all_items = tuple(
            sorted(
                (
                    *summary.closed_trades,
                    *summary.open_trades,
                    *summary.interrupted_trades,
                    *summary.initial_trades,
                ),
                key=lambda trade: (trade.entry_bar_end, trade.reference_trade_id),
                reverse=True,
            )
        )
        if request.history_before is not None:
            marker = _decode_cursor(
                request.history_before, "reference", fact_key, page_identity
            )
            positions = tuple(
                index
                for index, item in enumerate(all_items)
                if item.reference_trade_id == marker
            )
            if len(positions) != 1:
                raise NewowProductServiceError("NEWOW_CURSOR_GENERATION_CONFLICT")
            all_items = all_items[positions[0] + 1 :]
        items = all_items[: request.history_limit]
        next_before = (
            _cursor(
                {
                    "v": 1,
                    "kind": "reference",
                    "fingerprint": fact_key,
                    "page_identity": page_identity,
                    "before": items[-1].reference_trade_id,
                }
            )
            if len(all_items) > len(items) and items
            else None
        )
        value = ReferenceSectionValue(
            projection,
            summary,
            items,
            next_before,
            ProductReadWindow(resolved.requested_since, resolved.requested_through),
            resolved.actual_through,
            resolved.cutoff,
            fact_key,
        )
        status = (
            _ready()
            if resolved.complete
            else FeatureStatus(
                FeatureRuntimeStatus.WARMING,
                EvidenceStatus.ACTIVE_CODE_VERIFIED,
                resolved.reason_code or "NEWOW_REFERENCE_WINDOW_PARTIAL",
            )
        )
        return SectionDelivery("delivered", status, value)

    def _explanation(
        self, read: ProductReadSet, identity: ProductIdentity
    ) -> SectionDelivery:
        trend = {
            frequency: replay_strategy(
                build_product_identity(
                    identity.product, ProductStrategy.TREND, frequency
                ),
                bars,
            )
            for frequency, bars in read.bars_by_frequency.items()
        }
        oscillation = {
            frequency: replay_strategy(
                build_product_identity(
                    identity.product, ProductStrategy.OSCILLATION, frequency
                ),
                bars,
            )
            for frequency, bars in read.bars_by_frequency.items()
        }
        inputs = build_composite_inputs(trend, oscillation, read.as_of)
        composite = calculate_composite_explanation(inputs.context, inputs.evidence)
        target = calculate_target_absorb(inputs.context, None)
        sources = (
            *inputs.sources,
            *target_absorb_available_sources(inputs.context, identity.frequency),
            *target_absorb_gap_sources(read.as_of),
        )
        if target.status is FeatureRuntimeStatus.EVIDENCE_REQUIRED:
            status = FeatureStatus(
                FeatureRuntimeStatus.EVIDENCE_REQUIRED,
                EvidenceStatus.EVIDENCE_REQUIRED,
                target.reason_code or "NEWOW_EXPLANATION_EVIDENCE_REQUIRED",
            )
        else:
            status = FeatureStatus(
                composite.status, composite.evidence_status, composite.reason_code
            )
        return SectionDelivery(
            "delivered",
            status,
            ExplanationSectionValue(inputs.context, composite, target, sources),
        )

    def _comparator(
        self, read: ProductReadSet, identity: ProductIdentity
    ) -> SectionDelivery:
        if identity.strategy is not ProductStrategy.OSCILLATION:
            status = FeatureStatus(
                FeatureRuntimeStatus.NOT_APPLICABLE,
                EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
                "NEWOW_PAGE_COMPARATOR_NOT_APPLICABLE",
            )
            return SectionDelivery("delivered", status, None)
        eligible_bars = tuple(
            item
            for item in read.replay_bars
            if item.bar.observation_eligible and item.bar.bar_end <= read.as_of
        )
        owners = tuple(
            ComparatorOwnerSegment(
                identity.product,
                owner.contract,
                next(
                    bar.bar.segment_id
                    for bar in eligible_bars
                    if bar.bar.physical_contract == owner.contract
                    and owner.start_trading_day
                    <= bar.bar.trading_day
                    <= owner.end_trading_day
                ),
                owner.start_trading_day,
                owner.end_trading_day,
            )
            for owner in read.owners
            if any(
                bar.bar.physical_contract == owner.contract
                and owner.start_trading_day
                <= bar.bar.trading_day
                <= owner.end_trading_day
                for bar in eligible_bars
            )
        )
        result: PageComparatorResult = compare_page_windows(
            identity,
            eligible_bars,
            VerifiedPageComparatorEvidence(),
            authoritative_segments=owners,
            as_of=read.as_of,
        )
        status = FeatureStatus(
            result.status, result.evidence_status, result.reason_code
        )
        return SectionDelivery("delivered", status, result)
