"""Sectioned, read-only Newow product orchestration."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from itertools import groupby
import json
from secrets import token_urlsafe
from threading import Lock
from typing import TypeVar

from guiyi_quant.newow.composite_explanation import calculate_composite_explanation
from guiyi_quant.newow.context_alignment import ContextSnapshot
from guiyi_quant.newow.page_comparator import (
    ComparatorOwnerSegment,
    PageComparatorResult,
    VerifiedPageComparatorEvidence,
    compare_page_windows,
)
from guiyi_quant.newow.product_adapters import (
    build_product_identity, label_calculation_segments, replay_strategy,
)
from guiyi_quant.newow.product_auxiliary import calculate_auxiliary_component

from .product_macd import MACD_CACHE_IDENTITY, calculate_macd_display
from guiyi_quant.newow.product_contracts import (
    DataInterruption,
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
    StrategyReplay,
    lifecycle_input_sha256,
)
from guiyi_quant.newow.chart_price_reference import ChartPriceReference, project_chart_price_reference
from guiyi_quant.newow.product_identity import (
    FUTURES_ADAPTATION_VERSION,
    InputQualityPolicy,
    REFERENCE_MODEL_VERSION,
    futures_adaptation_version,
    input_policy_version,
    input_quality_policy,
    utc_timestamp,
)
from guiyi_quant.newow.trend_channel_display import (
    TrendChannelLayer,
    build_trend_channel_layer,
)
from guiyi_quant.newow.reference_statistics import (
    PerformanceWindow,
    ReferenceSummary,
    summarize_reference,
)
from guiyi_quant.newow.reference_trades import (
    ReferenceProjection,
    ReferenceTrade,
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
    SOURCE_FACT_ADAPTER_VERSION,
    SourceFact,
    build_composite_inputs,
    target_absorb_available_sources,
    target_absorb_gap_sources,
)


SCHEMA_VERSION = "newow_product_detail_v3"
_K = TypeVar("_K")
_V = TypeVar("_V")


class ProductSection(StrEnum):
    CHART = "chart"
    AUXILIARY = "auxiliary"
    REFERENCE = "reference"
    EXPLANATION = "explanation"
    COMPARATOR = "comparator"


class AuxiliaryComponent(StrEnum):
    MACD = "macd"
    MAIN_FORCE_CONTROL = "main_force_control"
    UP_DOWN_ENERGY = "up_down_energy"
    TREND_REVERSAL = "trend_reversal"
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
    chart_older_window: str | None = None
    component: AuxiliaryComponent | None = None
    history_limit: int = 50
    history_before: str | None = None
    snapshot_token: str | None = None
    include_fusion: bool = False
    decision_v2: bool = False

    def __post_init__(self) -> None:
        if self.decision_v2 and (self.section != "explanation" or self.frequency not in ("1d", "1w")):
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
        if self.include_fusion and (self.section != "reference" or self.strategy not in ("trend", "oscillation") or self.history_before is not None):
            raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
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
        if self.chart_older_window is not None and (
            self.section is not ProductSection.CHART
            or self.chart_before is not None or self.since is not None
            or self.snapshot_token is None
        ):
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
    actual_window: ProductReadWindow
    page_identity: str
    trend_channel: TrendChannelLayer | None
    price_reference: ChartPriceReference | None
    next_older_window: str | None = None
    price_unavailable_days: tuple[tuple[date, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _ChartNavigation:
    window: ProductReadWindow
    limit: int
    fingerprint: str
    oldest_bar_end: datetime | None


@dataclass(frozen=True, slots=True)
class ReferenceSectionValue:
    projection: ReferenceProjection
    summary: ReferenceSummary
    items: tuple[ReferenceTrade, ...]
    next_before: str | None
    requested_window: ProductReadWindow
    actual_available_through: date
    reference_cutoff: datetime
    reference_input_sha256: str
    entry_sequences: tuple[tuple[str, int], ...]
    history_coverage: str = "FULL"
    unavailable_days: tuple[date, ...] = ()
    coverage_intervals: tuple[ReferenceCoverageInterval, ...] = ()
    fusion_comparison: dict[str, object] | None = None
    theoretical: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PersistedReferenceSectionValue:
    """Already serialized read-only projection; no strategy replay object."""

    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReferenceCoverageInterval:
    since: date
    through: date
    status: str
    physical_contract: str
    segment_id: str
    calculation_segment_id: str | None


@dataclass(frozen=True, slots=True)
class ExplanationSectionValue:
    context: ContextSnapshot
    composite: object
    target_absorb: object
    sources: tuple[SourceFact, ...]
    decision_v2: dict[str, object] | None = None


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


def _has_unresolved_tail_gap(read: ProductReadSet) -> bool:
    """A stale pre-gap frame cannot represent the current completed D1 state."""
    latest_bar = max((item.bar.bar_end for item in read.replay_bars), default=None)
    return any(
        gap.effective_at <= read.as_of
        and (latest_bar is None or gap.effective_at > latest_bar)
        for gap in read.data_interruptions
    )


def _owned_display_interruptions(read: ProductReadSet) -> tuple[DataInterruption, ...]:
    """Use the owning segment once for display; replay keeps every prefix gap."""
    if not read.owners:
        return read.data_interruptions
    owner_segments: tuple[str, ...] | None = None
    if len(read.boundaries) == len(read.owners) - 1 and read.boundaries:
        owner_segments = (
            read.boundaries[0].old_segment_id,
            *(boundary.new_segment_id for boundary in read.boundaries),
        )
    selected: list[DataInterruption] = []
    seen: set[tuple[str, date]] = set()
    for gap in read.data_interruptions:
        matching = tuple(
            index for index, owner in enumerate(read.owners)
            if owner.contract == gap.physical_contract
            and owner.start_trading_day <= gap.trading_day <= owner.end_trading_day
        )
        if not matching:
            continue
        if len(matching) != 1:
            raise NewowProductServiceError("NEWOW_COVERAGE_IDENTITY_CONFLICT")
        if owner_segments is not None and gap.segment_id != owner_segments[matching[0]]:
            continue
        key = (gap.physical_contract, gap.trading_day)
        if key in seen:
            raise NewowProductServiceError("NEWOW_COVERAGE_IDENTITY_CONFLICT")
        seen.add(key)
        selected.append(gap)
    return tuple(selected)


def _reference_coverage_intervals(
    read: ProductReadSet,
    replay: StrategyReplay,
    since: date,
    through: date,
) -> tuple[ReferenceCoverageInterval, ...]:
    """Describe observed valid and excluded D1 stretches without inferring prices."""
    mapped_gaps = tuple(
        gap for gap in _owned_display_interruptions(read)
        if since <= gap.trading_day <= through
    )
    events = [
        (
            frame.bar.bar.trading_day,
            "VALID" if frame.availability.status is FeatureRuntimeStatus.READY else "WARMING",
            frame.bar.bar.physical_contract,
            frame.bar.bar.segment_id,
            frame.bar.calculation_segment_id,
        )
        for frame in replay.frames
        if frame.bar.bar.observation_eligible
        and since <= frame.bar.bar.trading_day <= through
    ]
    events.extend(
        (
            gap.trading_day, "PRICE_UNAVAILABLE", gap.physical_contract,
            gap.segment_id, None,
        )
        for gap in mapped_gaps
    )
    events.sort(key=lambda item: item[0])
    daily_events = []
    for day, grouped in groupby(events, key=lambda item: item[0]):
        same_day = tuple(grouped)
        if len(same_day) > 1:
            if read.frequency is not ProductFrequency.HOURLY or len({item[2:] for item in same_day}) != 1:
                raise NewowProductServiceError("NEWOW_COVERAGE_IDENTITY_CONFLICT")
            if any(item[1] == "PRICE_UNAVAILABLE" for item in same_day):
                raise NewowProductServiceError("NEWOW_COVERAGE_IDENTITY_CONFLICT")
        status = "WARMING" if any(item[1] == "WARMING" for item in same_day) else same_day[0][1]
        daily_events.append((day, status, *same_day[0][2:]))
    intervals: list[ReferenceCoverageInterval] = []
    previous_day: date | None = None
    for day, status, contract, segment_id, calculation_segment_id in daily_events:
        if previous_day is not None and day <= previous_day:
            raise NewowProductServiceError("NEWOW_COVERAGE_IDENTITY_CONFLICT")
        previous_day = day
        if intervals and (
            intervals[-1].status,
            intervals[-1].physical_contract,
            intervals[-1].segment_id,
            intervals[-1].calculation_segment_id,
        ) == (status, contract, segment_id, calculation_segment_id):
            intervals[-1] = replace(intervals[-1], through=day)
        else:
            intervals.append(ReferenceCoverageInterval(
                day, day, status, contract, segment_id, calculation_segment_id,
            ))
    return tuple(intervals)


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
                    item.source_bar_sha256,
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
    sources = tuple(
        (
            frequency.value,
            source.source_identity,
            None if source.bar_end is None else source.bar_end.isoformat(),
            source.input_policy_version,
            source.raw_bar_count,
            source.effective_bar_count,
            source.no_trade_bar_count,
            source.price_unavailable_count,
        )
        for frequency, source in sorted(
            read.sources.items(), key=lambda item: str(item[0])
        )
    )
    interruptions = tuple(
        (
            frequency.value, item.physical_contract, item.segment_id,
            item.trading_day.isoformat(), item.effective_at.isoformat(),
            item.source_identity,
        )
        for frequency, values in sorted(
            read.data_interruptions_by_frequency.items(), key=lambda item: str(item[0])
        )
        for item in values
    )
    identity_fields: tuple[object, ...] = (
        identity.product,
        identity.strategy.value,
        identity.frequency.value,
        identity.formula_versions,
        identity.profile_id,
    )
    if identity.input_quality_policy is not InputQualityPolicy.V1:
        identity_fields = (*identity_fields, identity.input_quality_policy.value)
    payload = json.dumps(
        {
            "identity": identity_fields,
            "as_of": read.as_of.isoformat(),
            "bars": bars,
            "owners": owners,
            "boundaries": boundaries,
            "sources": sources,
            "interruptions": interruptions,
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


def _reference_cursor_marker(item: ReferenceTrade, entry_sequence: int) -> str:
    return json.dumps(
        [item.entry_bar_end.isoformat(), entry_sequence, item.reference_trade_id],
        separators=(",", ":"),
    )


def _snapshot_namespace(identity: ProductIdentity, as_of: datetime) -> str:
    identity_fields: tuple[object, ...] = (
        identity.product,
        identity.strategy.value,
        identity.frequency.value,
        identity.profile_id,
        identity.formula_versions,
    )
    contract: tuple[object, ...] = (
        SCHEMA_VERSION,
        REFERENCE_MODEL_VERSION,
        futures_adaptation_version(
            identity.frequency, identity.input_quality_policy
        ),
    )
    if identity.input_quality_policy is not InputQualityPolicy.V1:
        identity_fields = (*identity_fields, identity.input_quality_policy.value)
        contract = (*contract, identity.input_quality_policy.value)
    payload = {
        "identity": identity_fields,
        "as_of": as_of.isoformat(),
        "contract": contract,
    }
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _dependency_proof(read: ProductReadSet) -> dict[str, str]:
    proof: dict[str, str] = {}
    physical_gaps: dict[str, str] = {}
    for frequency in sorted(read.bars_by_frequency, key=str):
        for item in read.bars_by_frequency[frequency]:
            bar = item.bar
            key = "|".join(
                (
                    "bar",
                    frequency.value,
                    bar.physical_contract,
                    bar.segment_id,
                    bar.bar_end.isoformat(),
                )
            )
            # The segment ID already binds the owner start. A physical warm-up
            # bar may also fall inside an earlier owner visible only to a wider
            # section; borrowing that owner's start makes equal bars conflict.
            # Shared owner transitions are compared as boundaries below.
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
                    item.source_bar_sha256 or "",
                )
            )
            proof[key] = sha256(value.encode()).hexdigest()
            if frequency in (ProductFrequency.DAILY, ProductFrequency.WEEKLY):
                day_key = "|".join((
                    "price-state", frequency.value, bar.physical_contract,
                    bar.trading_day.isoformat(),
                ))
                physical_value = "|".join((
                    bar.trading_day.isoformat(), str(bar.open), str(bar.high),
                    str(bar.low), str(bar.close), str(bar.volume),
                    str(bar.open_interest), bar.source_identity,
                    item.source_bar_sha256 or "",
                ))
                proof[day_key] = sha256(
                    f"bar|{physical_value}".encode()
                ).hexdigest()
                if bar.observation_eligible:
                    owner_key = "|".join((
                        "owner-price-state", frequency.value,
                        bar.physical_contract, bar.trading_day.isoformat(),
                    ))
                    proof[owner_key] = sha256(bar.segment_id.encode()).hexdigest()
    for frequency, interruptions in read.data_interruptions_by_frequency.items():
        for gap in interruptions:
            key = "|".join((
                "price-unavailable", frequency.value, gap.physical_contract,
                gap.trading_day.isoformat(),
            ))
            value = "|".join((gap.effective_at.isoformat(), gap.source_identity))
            physical_digest = sha256(value.encode()).hexdigest()
            if key in physical_gaps and physical_gaps[key] != physical_digest:
                raise NewowProductServiceError("NEWOW_DATA_IDENTITY_INVALID")
            physical_gaps[key] = physical_digest
            proof[key] = physical_digest
            segment_key = "|".join((
                "segment-price-unavailable", frequency.value,
                gap.physical_contract, gap.segment_id, gap.trading_day.isoformat(),
            ))
            if segment_key in proof:
                raise NewowProductServiceError("NEWOW_DATA_IDENTITY_INVALID")
            proof[segment_key] = physical_digest
            day_key = "|".join((
                "price-state", frequency.value, gap.physical_contract,
                gap.trading_day.isoformat(),
            ))
            gap_state = sha256(f"gap|{value}".encode()).hexdigest()
            if day_key in proof and proof[day_key] != gap_state:
                raise NewowProductServiceError("NEWOW_DATA_IDENTITY_INVALID")
            proof[day_key] = gap_state
    if read.owners:
        for gap in _owned_display_interruptions(read):
            owner_key = "|".join((
                "owner-price-state", gap.frequency.value,
                gap.physical_contract, gap.trading_day.isoformat(),
            ))
            proof[owner_key] = sha256(gap.segment_id.encode()).hexdigest()
    for boundary in read.boundaries:
        key = "|".join(
            (
                "boundary",
                boundary.effective_at.isoformat(),
                boundary.new_contract,
            )
        )
        value = "|".join(
            (
                boundary.old_contract,
                boundary.old_segment_id,
                boundary.new_segment_id,
                boundary.effective_trading_day.isoformat(),
                boundary.source_identity,
            )
        )
        proof[key] = sha256(value.encode()).hexdigest()
    for frequency, source in read.sources.items():
        proof["|".join(("source-version", frequency.value))] = sha256(
            "|".join((source.source_identity, source.input_policy_version)).encode()
        ).hexdigest()
        key = "|".join(
            (
                "source-window",
                frequency.value,
                read.display_window.since.isoformat(),
                read.display_window.through.isoformat(),
                read.as_of.isoformat(),
            )
        )
        value = "|".join(
            (
                "" if source.bar_end is None else source.bar_end.isoformat(),
                str(source.raw_bar_count),
                str(source.effective_bar_count),
                str(source.no_trade_bar_count),
                str(source.price_unavailable_count),
            )
        )
        proof[key] = sha256(value.encode()).hexdigest()
    proof["version|product"] = sha256(
        "|".join(
            (
                SCHEMA_VERSION,
                futures_adaptation_version(
                    read.frequency, read.input_quality_policy
                ),
                input_policy_version(
                    read.frequency, read.input_quality_policy
                ),
                REFERENCE_MODEL_VERSION,
                SOURCE_FACT_ADAPTER_VERSION,
                "main_contract_map:rank1:calendar_session_v1",
                "newow_product_dependency_proof_v7",
            )
        ).encode()
    ).hexdigest()
    return proof


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
        reuse_read_inputs: bool = False,
        quality_policy: InputQualityPolicy | str = InputQualityPolicy.V1,
        persisted_reference: Callable | None = None,
    ) -> None:
        self._reader_factory = reader_factory
        self._cache = cache or SnapshotCache()
        self._gate = heavy_gate or HeavyResourceGate()
        self._inflight = inflight or InFlightCoordinator()
        self._now = now or (lambda: datetime.now(UTC))
        self._cancelled = cancelled
        self._reuse_read_inputs = reuse_read_inputs
        self._quality_policy = InputQualityPolicy(quality_policy)
        self._persisted_reference = persisted_reference
        self._read_input_lock = Lock()
        self._chart_windows: dict[
            tuple[str, ProductFrequency, int, datetime], ProductReadWindow
        ] = {}
        self._performance_windows: dict[
            tuple[str, ProductFrequency, date | None, date | None, datetime],
            ResolvedPerformanceWindow,
        ] = {}
        self._reads: dict[tuple[object, ...], ProductReadSet] = {}

    def query(self, request: ProductServiceQuery) -> NewowProductResult:
        if not isinstance(request, ProductServiceQuery):
            raise NewowProductServiceError("NEWOW_INVALID_QUERY")
        as_of = utc_timestamp(request.as_of or self._now())
        if as_of > utc_timestamp(self._now()):
            raise NewowProductServiceError("NEWOW_INVALID_AS_OF")
        key = (self._quality_policy, request, as_of)
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
        if request.section in {ProductSection.REFERENCE, ProductSection.COMPARATOR}:
            with self._gate.acquire(cancelled):
                return self._query_admitted(request, as_of, cancelled)
        return self._query_admitted(request, as_of, cancelled)

    def _query_admitted(
        self,
        request: ProductServiceQuery,
        as_of: datetime,
        cancelled: Callable[[], bool],
    ) -> NewowProductResult:
        context = (
            (ProductFrequency.DAILY, ProductFrequency.WEEKLY) if request.decision_v2 else tuple(ProductFrequency)
            if request.section is ProductSection.EXPLANATION
            else ()
        )
        reader = self._reader_factory(context, cancelled)
        policy = input_quality_policy(request.frequency.value, self._quality_policy)
        identity = build_product_identity(
            request.product,
            request.strategy,
            request.frequency,
            input_quality_policy=policy,
        )
        common_key = _snapshot_namespace(identity, as_of)
        prior_navigation: _ChartNavigation | None = None
        anchor_proof: dict[str, str] = {}
        if request.chart_older_window is not None:
            candidate = self._cache.get_by_token(
                request.snapshot_token or "", common_key,
                ("older_window", request.chart_older_window),
                touch=False,
            )
            if not isinstance(candidate, _ChartNavigation) or candidate.limit != request.chart_limit:
                raise NewowProductServiceError("NEWOW_CHART_CURSOR_INVALID")
            prior_navigation = candidate
            # Re-read the preceding accepted bounded window through the same
            # authoritative reader. This bridges disjoint physical-owner inputs;
            # cached proof alone cannot establish that the anchor is still true.
            anchor = reader.load(NewowProductQuery(
                request.product, request.strategy, request.frequency,
                candidate.window.since, candidate.window.through,
                candidate.window.since, candidate.window.through, as_of,
            ), as_of)
            anchor_proof = _dependency_proof(anchor)
            if (_fingerprint(anchor, identity) != candidate.fingerprint
                or not self._cache.token_is_compatible(
                    request.snapshot_token or "", common_key, anchor_proof
                )):
                raise NewowProductServiceError("NEWOW_SNAPSHOT_GENERATION_CONFLICT")
        resolved: ResolvedPerformanceWindow | None = None
        if prior_navigation is not None:
            older = reader.resolve_older_chart_window(
                request.product, request.frequency, request.chart_limit, as_of,
                prior_navigation.window.since,
            )
            if older is None or older.through >= prior_navigation.window.since:
                raise NewowProductServiceError("NEWOW_CHART_CURSOR_INVALID")
            window = older
            read_as_of = as_of
        elif request.section is ProductSection.REFERENCE:
            performance_key = (
                request.product,
                request.frequency,
                request.performance_since,
                request.performance_through,
                as_of,
            )
            resolved = self._cached_read_input(
                self._performance_windows,
                performance_key,
                lambda: reader.resolve_performance_window(
                    request.product,
                    request.frequency,
                    request.performance_since,
                    request.performance_through,
                    as_of,
                ),
            )
            window = ProductReadWindow(
                resolved.requested_since, resolved.actual_through
            )
            read_as_of = resolved.cutoff
        elif request.since is not None and request.through is not None:
            window = ProductReadWindow(request.since, request.through)
            read_as_of = as_of
        else:
            chart_key = (
                request.product, request.frequency, request.chart_limit, as_of
            )
            window = self._cached_read_input(
                self._chart_windows,
                chart_key,
                lambda: reader.resolve_chart_window(
                    request.product, request.frequency, request.chart_limit, as_of
                ),
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
        read = self._cached_read_input(
            self._reads,
            self._market_read_key(low_query, read_as_of, policy),
            lambda: reader.load(low_query, read_as_of),
        )
        if read.input_quality_policy is not policy:
            raise NewowProductServiceError("NEWOW_DATA_IDENTITY_INVALID")
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
        fact_key = _fingerprint(read, identity)
        proof = _dependency_proof(read)
        if any(proof[key] != anchor_proof[key] for key in proof.keys() & anchor_proof.keys()):
            raise NewowProductServiceError("NEWOW_SNAPSHOT_GENERATION_CONFLICT")
        proof.update(anchor_proof)
        page_identity = self._page_identity(request, window, resolved, as_of)
        navigable = request.section is ProductSection.CHART and (
            request.since is None or (
                request.chart_before is not None and request.snapshot_token is not None
                and isinstance(self._cache.get_by_token(
                    request.snapshot_token, common_key, ("chart_window", page_identity),
                    touch=False,
                ), _ChartNavigation)
            )
        )
        section_key = self._section_key(
            request, window, resolved, fact_key, page_identity
        ) + (navigable,)
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
            reader,
        )
        chart = result.chart.value
        if prior_navigation is not None and isinstance(chart, ChartSectionValue):
            if (chart.bars and prior_navigation.oldest_bar_end is not None
                and chart.bars[-1].bar.bar_end >= prior_navigation.oldest_bar_end):
                raise NewowProductServiceError("NEWOW_CHART_CURSOR_INVALID")
        # Complete every authoritative read before retaining any result. A
        # failed navigation read must not leave a cached truncated success.
        has_older_window = (
            navigable and isinstance(chart, ChartSectionValue)
            and chart.next_before is None and self._cacheable(result)
            and reader.resolve_older_chart_window(
                request.product, request.frequency, request.chart_limit, as_of, window.since
            ) is not None
        )
        self._check_cancelled(cancelled)
        if not self._cacheable(result):
            return result
        related: dict[tuple[object, ...], object] = {}
        complete = result
        if navigable and isinstance(chart, ChartSectionValue):
            navigation = _ChartNavigation(
                window, request.chart_limit, fact_key,
                chart.bars[0].bar.bar_end if chart.bars else None,
            )
            related[("chart_window", page_identity)] = navigation
            if has_older_window:
                cursor = token_urlsafe(24)
                related[("older_window", cursor)] = navigation
                complete = replace(result, chart=replace(
                    result.chart, value=replace(chart, next_older_window=cursor)
                ))

        def bind_snapshot(token: str) -> NewowProductResult:
            return replace(complete, meta=replace(complete.meta, snapshot_token=token))

        # Result, token, proof and navigation are one measured cache candidate.
        # Rejection retains no partial success and leaves the old entry intact.
        token = self._cache.put(
            common_key, section_key, complete, token=request.snapshot_token,
            proof=proof, related_values=related, value_factory=bind_snapshot,
        )
        return bind_snapshot(token) if token is not None else result

    def _cached_read_input(
        self,
        cache: dict[_K, _V],
        key: _K,
        load: Callable[[], _V],
    ) -> _V:
        if not self._reuse_read_inputs:
            return load()
        with self._read_input_lock:
            cached = cache.get(key)
            if cached is not None:
                return cached
            value = load()
            cache[key] = value
            return value

    @staticmethod
    def _market_read_key(
        query: NewowProductQuery,
        read_as_of: datetime,
        quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    ) -> tuple[object, ...]:
        # Reader output contains market facts and owner evidence only. Strategy
        # identity is applied later by _calculate, so all three strategies may
        # safely share one immutable ProductReadSet for the same bounded input.
        return (
            query.product,
            query.frequency,
            query.since,
            query.through,
            query.performance_since,
            query.performance_through,
            read_as_of,
            query.series_kind,
            query.history_limit,
            query.history_before,
            quality_policy,
        )

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
            MACD_CACHE_IDENTITY if request.component is AuxiliaryComponent.MACD else None,
            request.component.value if request.component else None,
            window.since.isoformat(),
            window.through.isoformat(),
            resolved.requested_through.isoformat() if resolved else None,
            request.chart_limit,
            request.chart_before,
            request.chart_older_window,
            request.history_limit,
            request.history_before,
            request.include_fusion,
            request.decision_v2,
        )

    def _page_identity(
        self,
        request: ProductServiceQuery,
        window: ProductReadWindow,
        resolved: ResolvedPerformanceWindow | None,
        as_of: datetime,
    ) -> str:
        payload: tuple[object, ...] = (
            SCHEMA_VERSION,
            REFERENCE_MODEL_VERSION,
            futures_adaptation_version(request.frequency, self._quality_policy),
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
        if self._quality_policy is not InputQualityPolicy.V1:
            payload = (*payload, self._quality_policy.value)
        return sha256(repr(payload).encode()).hexdigest()

    @staticmethod
    def _cacheable(result: NewowProductResult) -> bool:
        delivery = getattr(result, result.section.value)
        return (
            delivery.delivery == "delivered"
            and delivery.status is not None
            and delivery.value is not None
            and delivery.status.status
            in {FeatureRuntimeStatus.READY, FeatureRuntimeStatus.WARMING}
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
        reader: NewowProductReader,
    ) -> NewowProductResult:
        self._check_cancelled(cancelled)
        deliveries = {section: _not_requested() for section in ProductSection}
        if request.section is ProductSection.CHART:
            deliveries[request.section] = self._chart(
                request, read, identity, fact_key, page_identity
            )
        elif request.section is ProductSection.AUXILIARY:
            assert request.component is not None
            layer = (
                calculate_macd_display(identity, read)
                if request.component is AuxiliaryComponent.MACD
                else calculate_auxiliary_component(
                    identity,
                    label_calculation_segments(identity, read.replay_bars, read.data_interruptions),
                    request.component.value,
                    as_of=read.as_of,
                )
            )
            self._check_cancelled(cancelled)
            deliveries[request.section] = SectionDelivery(
                "delivered", layer.availability, layer
            )
        elif request.section is ProductSection.REFERENCE:
            assert resolved is not None
            deliveries[request.section] = (
                self._reference(request, read, identity, fact_key, page_identity, resolved)
                if self._persisted_reference is None or request.include_fusion else
                self._persisted_reference(
                    request, read, identity, reader, fact_key, page_identity, resolved,
                )
            )
        elif request.section is ProductSection.EXPLANATION:
            deliveries[request.section] = self._explanation(read, identity, decision_v2=request.decision_v2)
        else:
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
            futures_adaptation_version=futures_adaptation_version(
                request.frequency, identity.input_quality_policy
            ),
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
        replay = replay_strategy(
            identity,
            read.replay_bars,
            lifecycle_evidence=read.lifecycle_evidence,
            data_interruptions=read.data_interruptions,
        )
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
        visible = StrategyReplay(
            identity,
            selected,
            tuple(action for frame in selected for action in frame.actions),
            tuple(hint for frame in selected for hint in frame.hints),
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
        if _has_unresolved_tail_gap(read):
            status = FeatureStatus(
                FeatureRuntimeStatus.WARMING,
                EvidenceStatus.ACTIVE_CODE_VERIFIED,
                "NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING",
            )
        channel = build_trend_channel_layer(read.replay_bars, tuple(frame.bar for frame in selected))
        price_reference = project_chart_price_reference(
            channel, selected[-1].bar, as_of=read.replay_bars[-1].bar.bar_end,
            input_sha256=lifecycle_input_sha256(read.replay_bars),
        ) if selected else None
        return SectionDelivery(
            "delivered",
            status,
            ChartSectionValue(
                tuple(frame.bar for frame in selected),
                visible,
                next_before,
                replay.diagnostics,
                read.display_window,
                page_identity,
                channel if identity.strategy is ProductStrategy.TREND else None,
                price_reference,
                price_unavailable_days=tuple(
                    (gap.trading_day, gap.physical_contract, gap.segment_id)
                    for gap in _owned_display_interruptions(read)
                    if read.display_window.since <= gap.trading_day <= read.display_window.through
                ),
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
        replay = replay_strategy(
            identity,
            read.replay_bars,
            lifecycle_evidence=read.lifecycle_evidence,
            data_interruptions=read.data_interruptions,
        )
        projection = ReferenceTradeProjector().project(
            replay, read.boundaries, resolved.cutoff,
            data_interruptions=read.data_interruptions,
        )
        summary = summarize_reference(
            projection,
            PerformanceWindow(
                resolved.requested_since, resolved.requested_through, resolved.cutoff
            ),
        )
        entry_sequences = {
            action.signal_id: action.sequence for action in replay.actions
        }
        all_items = tuple(
            sorted(
                (
                    *summary.closed_trades,
                    *summary.open_trades,
                    *summary.interrupted_trades,
                    *summary.initial_trades,
                ),
                key=lambda trade: (
                    trade.entry_bar_end,
                    entry_sequences[trade.entry_signal_id],
                    trade.reference_trade_id,
                ),
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
                if _reference_cursor_marker(
                    item, entry_sequences[item.entry_signal_id]
                )
                == marker
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
                    "before": _reference_cursor_marker(
                        items[-1], entry_sequences[items[-1].entry_signal_id]
                    ),
                }
            )
            if len(all_items) > len(items) and items
            else None
        )
        coverage_intervals = _reference_coverage_intervals(
            read, replay, resolved.requested_since, resolved.actual_through,
        )
        unavailable_days = tuple(sorted({
            gap.trading_day
            for gap in read.data_interruptions
            if any(
                interval.status == "PRICE_UNAVAILABLE"
                and interval.since <= gap.trading_day <= interval.through
                and interval.physical_contract == gap.physical_contract
                for interval in coverage_intervals
            )
        }))
        fusion = None
        if request.include_fusion:
            from guiyi_quant.newow.fusion_reference import fusion_reference_comparison
            replays = {}
            for strategy in (ProductStrategy.TREND, ProductStrategy.OSCILLATION):
                source_identity = build_product_identity(
                    identity.product, strategy, identity.frequency,
                    input_quality_policy=identity.input_quality_policy,
                )
                replays[strategy] = replay if strategy is identity.strategy else replay_strategy(
                    source_identity, read.replay_bars,
                    lifecycle_evidence=read.lifecycle_evidence,
                    data_interruptions=read.data_interruptions,
                )
            fusion = fusion_reference_comparison(
                replays[ProductStrategy.TREND], replays[ProductStrategy.OSCILLATION],
                read.boundaries, read.data_interruptions,
                PerformanceWindow(resolved.requested_since, resolved.requested_through, resolved.cutoff),
            )
            fusion["reference_input_sha256"] = fact_key
        from guiyi_quant.newow.theoretical_reference import theoretical_reference
        theoretical = theoretical_reference(summary.closed_trades, tuple(frame.bar for frame in replay.frames))
        value = ReferenceSectionValue(
            projection,
            summary,
            items,
            next_before,
            ProductReadWindow(resolved.requested_since, resolved.requested_through),
            resolved.actual_through,
            resolved.cutoff,
            fact_key,
            tuple(sorted(entry_sequences.items())),
            "PARTIAL" if any(
                interval.status != "VALID" for interval in coverage_intervals
            ) else "FULL",
            unavailable_days,
            coverage_intervals,
            fusion,
            theoretical,
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
        if _has_unresolved_tail_gap(read) or (
            read.data_interruptions and replay.frames
            and replay.frames[-1].availability.status is not FeatureRuntimeStatus.READY
        ):
            status = FeatureStatus(
                FeatureRuntimeStatus.WARMING,
                EvidenceStatus.ACTIVE_CODE_VERIFIED,
                "NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING",
            )
        return SectionDelivery("delivered", status, value)

    def _explanation(
        self, read: ProductReadSet, identity: ProductIdentity, *, decision_v2: bool = False
    ) -> SectionDelivery:
        trend = {
            frequency: replay_strategy(
                build_product_identity(
                    identity.product,
                    ProductStrategy.TREND,
                    frequency,
                    input_quality_policy=read.input_quality_policies_by_frequency.get(frequency, (
                        identity.input_quality_policy
                        if frequency is ProductFrequency.WEEKLY
                        else InputQualityPolicy.V1
                    )),
                ),
                bars,
                lifecycle_evidence=read.lifecycle_evidence_by_frequency.get(
                    frequency, ()
                ),
                data_interruptions=read.data_interruptions_by_frequency.get(frequency, ()),
            )
            for frequency, bars in read.bars_by_frequency.items()
        }
        oscillation = {
            frequency: replay_strategy(
                build_product_identity(
                    identity.product,
                    ProductStrategy.OSCILLATION,
                    frequency,
                    input_quality_policy=read.input_quality_policies_by_frequency.get(frequency, (
                        identity.input_quality_policy
                        if frequency is ProductFrequency.WEEKLY
                        else InputQualityPolicy.V1
                    )),
                ),
                bars,
                lifecycle_evidence=read.lifecycle_evidence_by_frequency.get(
                    frequency, ()
                ),
                data_interruptions=read.data_interruptions_by_frequency.get(frequency, ()),
            )
            for frequency, bars in read.bars_by_frequency.items()
        }
        addon = None
        if decision_v2:
            from .decision_v2 import build_decision_v2
            main_frequency = identity.frequency
            main_bars = read.bars_by_frequency.get(main_frequency, ())
            main = replay_strategy(
                build_product_identity(identity.product, ProductStrategy.MAIN_RISE, main_frequency,
                    input_quality_policy=read.input_quality_policies_by_frequency.get(main_frequency, InputQualityPolicy.V1)),
                main_bars, lifecycle_evidence=read.lifecycle_evidence_by_frequency.get(main_frequency, ()),
                data_interruptions=read.data_interruptions_by_frequency.get(main_frequency, ()),
            ) if main_bars else None
            addon = build_decision_v2(trend, oscillation, main, read, identity)
            for replays, strategy in ((trend, ProductStrategy.TREND), (oscillation, ProductStrategy.OSCILLATION)):
                for frequency in ProductFrequency:
                    if frequency not in replays:
                        replays[frequency] = StrategyReplay(build_product_identity(identity.product, strategy, frequency), (), (), (), ())
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
        if decision_v2:
            current_missing = f"trend_{'week' if identity.frequency is ProductFrequency.WEEKLY else 'day'}" in addon['cdv2']['missing_roles']
            status = FeatureStatus(FeatureRuntimeStatus.WARMING, EvidenceStatus.RESEARCH_EVIDENCE_ONLY, 'NEWOW_CDV2_CURRENT_CONTEXT_UNAVAILABLE') if current_missing else FeatureStatus(FeatureRuntimeStatus.READY, EvidenceStatus.RESEARCH_EVIDENCE_ONLY)
        return SectionDelivery(
            "delivered",
            status,
            ExplanationSectionValue(inputs.context, composite, target, sources, addon),
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
