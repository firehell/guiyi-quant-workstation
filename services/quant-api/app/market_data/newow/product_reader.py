"""Request-scoped completed inputs and authoritative owner facts, without signals."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    DataInterruption,
    LIFECYCLE_REPLAY_EVIDENCE_SOURCE,
    LifecycleReplayEvidence,
    OwnerBoundary,
    ProductBar,
    ProductFrequency,
    lifecycle_input_sha256,
)
from guiyi_quant.newow.product_identity import (
    FUTURES_INPUT_POLICY_VERSION,
    InputQualityPolicy,
    build_segment_id,
    input_policy_version,
    input_quality_policy,
    source_classification_version,
    utc_timestamp,
)

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSegmentLoader,
)
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageCursorMode,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.source_quality import PriceUnavailableFact
from app.market_data.weekly_quality import WeeklySourceInterruption

from .product_query import NewowProductQuery, ProductReadWindow

_PAGE_SIZE = 2000
_MICROSECOND = timedelta(microseconds=1)
_HISTORICAL_CANDIDATE_BATCH = timedelta(days=59)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CANONICAL_SOURCE = LIFECYCLE_REPLAY_EVIDENCE_SOURCE
_OWNER_SOURCE = "main_contract_map:rank1:calendar_session_v1"


class NewowProductReadError(ValueError):
    def __init__(self, code: str, *, context: dict[str, object] | None = None) -> None:
        from app.market_data.diagnostics import safe_context

        self.code = code
        self.context = safe_context(context)
        super().__init__(code)


class NewowProductReadCancelled(RuntimeError):
    """The caller cancelled; no partial read set may escape."""


def _quality_source_identity(
    frequency: ProductFrequency,
    gap: PriceUnavailableFact | WeeklySourceInterruption,
) -> str:
    if frequency is ProductFrequency.DAILY and isinstance(gap, PriceUnavailableFact):
        return (
            "market_data_service:price_unavailable:v1:"
            f"{gap.request_sha256}:{gap.response_sha256}"
        )
    if frequency is ProductFrequency.WEEKLY and isinstance(gap, WeeklySourceInterruption):
        return (
            "market_data_service:weekly_quality:"
            f"{gap.classification_version.removeprefix('weekly-d1-quality-')}:"
            f"{gap.source_identity}"
        )
    raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")


class ProductCoverage(Protocol):
    """Existing DatabaseCoverageSource read facts, injectable without a database."""

    def product_start(self, symbol: str) -> date: ...

    def latest_complete_day(self, products: tuple[str, ...]) -> date: ...


@dataclass(frozen=True, slots=True)
class ProductReadSource:
    frequency: ProductFrequency
    source_identity: str
    bar_end: datetime | None
    as_of: datetime
    input_policy_version: str
    raw_bar_count: int
    effective_bar_count: int
    no_trade_bar_count: int
    price_unavailable_count: int = 0


@dataclass(frozen=True, slots=True)
class ResolvedPerformanceWindow:
    requested_since: date
    requested_through: date
    actual_through: date
    cutoff: datetime
    complete: bool = True
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProductReadSet:
    frequency: ProductFrequency
    bars_by_frequency: Mapping[ProductFrequency, tuple[ProductBar, ...]]
    owners: tuple[ResolvedContractSegment, ...]
    boundaries: tuple[OwnerBoundary, ...]
    display_window: ProductReadWindow
    performance_window: ProductReadWindow
    sources: Mapping[ProductFrequency, ProductReadSource]
    as_of: datetime
    lifecycle_evidence_by_frequency: Mapping[
        ProductFrequency, tuple[LifecycleReplayEvidence, ...]
    ] = field(default_factory=lambda: MappingProxyType({}))
    data_interruptions_by_frequency: Mapping[
        ProductFrequency, tuple[DataInterruption, ...]
    ] = field(default_factory=lambda: MappingProxyType({}))
    input_quality_policy: InputQualityPolicy = InputQualityPolicy.V1

    @property
    def replay_bars(self) -> tuple[ProductBar, ...]:
        """Segment-ordered inputs; each segment has its own lifecycle prefix."""
        return self.bars_by_frequency[self.frequency]

    @property
    def lifecycle_evidence(self) -> tuple[LifecycleReplayEvidence, ...]:
        return self.lifecycle_evidence_by_frequency.get(self.frequency, ())

    @property
    def data_interruptions(self) -> tuple[DataInterruption, ...]:
        return self.data_interruptions_by_frequency.get(self.frequency, ())


class _AsOfSegmentLoader(ActualDominantResearchSegmentLoader):
    """Retain the shared owner validator while bounding its day-based read."""

    def __init__(
        self,
        market_data: MarketDataService,
        through: date,
        as_of: datetime,
        check_cancelled: Callable[[], None],
        quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    ) -> None:
        super().__init__(market_data)
        self._through = through
        self._as_of = as_of
        self._check_cancelled = check_cancelled
        self._quality_policy = InputQualityPolicy(quality_policy)
        self.price_unavailable_by_frequency: dict[
            BarFrequency,
            tuple[tuple[str, PriceUnavailableFact | WeeklySourceInterruption], ...],
        ] = {}

    def _query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult:
        self._check_cancelled()
        bounded = replace(request, through=min(request.through, self._through))
        quality_query = getattr(self._market_data, "query_actual_dominant_trading_days_quality", None)
        if bounded.frequency in (BarFrequency.D1, BarFrequency.W1) and quality_query is not None:
            policy = (
                self._quality_policy
                if bounded.frequency is BarFrequency.W1
                else InputQualityPolicy.V1
            )
            result, gaps = (
                quality_query(bounded)
                if policy is InputQualityPolicy.V1
                else quality_query(
                    bounded,
                    weekly_classification_version=source_classification_version(
                        bounded.frequency.value, policy
                    ),
                )
            )
            self.price_unavailable_by_frequency[bounded.frequency] = tuple(
                (contract, gap) for contract, gap in gaps if gap.bar_end <= self._as_of
            )
        else:
            result = super()._query_actual_dominant_trading_days(bounded)
        self._check_cancelled()
        if result.requested_trading_day_window != (
            bounded.since,
            bounded.through,
        ) or any(
            result.request_identity.get(key) != value
            for key, value in {
                "series_kind": "actual_dominant",
                "symbol": request.symbol,
                "frequency": request.frequency.value,
                "contract": None,
            }.items()
        ):
            raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
        # The MDS trading-day API may include a later completed Bar of the same
        # day. It cannot enter this historical snapshot, overlap checks or seeds.
        bars = tuple(bar for bar in result.bars if bar.bar_end <= self._as_of)
        _validate_order(bars)
        if any(not bounded.since <= bar.trading_day <= bounded.through for bar in bars):
            raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
        segments = tuple(
            segment
            for segment in result.resolved_contract_segments
            # Remove only summaries whose Bars were all after as_of. An
            # originally orphaned response summary must still fail the shared
            # validator; zero-Bar owners are valid only in the global mapping.
            if not any(
                segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
                for bar in result.bars
            )
            or any(
                segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
                for bar in bars
            )
        )
        return replace(
            result,
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            resolved_contract_segments=segments,
        )


class NewowProductReader:
    def __init__(
        self,
        market_data: MarketDataService,
        *,
        coverage: ProductCoverage,
        active_products: Collection[str],
        context_frequencies: Sequence[ProductFrequency] = (),
        now: Callable[[], datetime] | None = None,
        cancelled: Callable[[], bool] | None = None,
        input_quality_policy: InputQualityPolicy | str = InputQualityPolicy.V1,
    ) -> None:
        self._market_data = market_data
        self._coverage = coverage
        self._active_products = frozenset(active_products)
        self._context_frequencies = tuple(
            ProductFrequency(value) for value in context_frequencies
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._cancelled = cancelled
        self._input_quality_policy = InputQualityPolicy(input_quality_policy)

    def historical_snapshot_candidates(
        self,
        product: str,
        *,
        as_of: datetime,
        limit: int = 20,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[tuple[date, datetime], ...]:
        """Return newest completed authoritative day cutoffs for explicit recovery."""
        cutoff = utc_timestamp(as_of)
        if (
            product not in self._active_products
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise NewowProductReadError("NEWOW_INVALID_QUERY")
        if cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")

        def check() -> None:
            self._check_cancelled()
            if cancelled is not None and cancelled():
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")

        check()
        product_start = self._coverage.product_start(product)
        batch_end = cutoff.astimezone(_SHANGHAI).date()
        candidates: list[tuple[date, datetime]] = []
        while batch_end >= product_start and len(candidates) < limit:
            check()
            batch_start = max(product_start, batch_end - _HISTORICAL_CANDIDATE_BATCH)
            batch_as_of = min(
                cutoff,
                datetime.combine(batch_end + timedelta(days=1), time.min, _SHANGHAI),
            )
            batch = self._market_data.completed_trading_days(
                symbol=product,
                start=datetime.combine(batch_start, time.min, _SHANGHAI),
                as_of=batch_as_of,
                latest=batch_end,
            )
            if (
                any(current <= previous for previous, current in zip(batch, batch[1:]))
                or any(not batch_start <= day <= batch_end for day in batch)
            ):
                raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
            for day in reversed(batch):
                check()
                session_cutoff = utc_timestamp(
                    max(
                        window.end
                        for window in self._market_data.session_windows(
                            symbol=product, trading_day=day
                        )
                    )
                    + _MICROSECOND
                )
                if session_cutoff <= cutoff:
                    candidates.append((day, session_cutoff))
                    if len(candidates) == limit:
                        break
            if batch_start == product_start:
                break
            batch_end = batch_start - timedelta(days=1)
        return tuple(candidates)

    def weekly_snapshot_candidates(
        self, product: str, *, as_of: datetime, limit: int = 2,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[tuple[date, datetime], ...]:
        """Choose bounded complete ISO weeks from Calendar and Session authority."""
        cutoff = utc_timestamp(as_of)
        if product not in self._active_products or type(limit) is not int or not 1 <= limit <= 2:
            raise NewowProductReadError("NEWOW_INVALID_QUERY")
        if cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")
        start = self._coverage.product_start(product)
        local_day = cutoff.astimezone(_SHANGHAI).date()
        monday = local_day - timedelta(days=local_day.isoweekday() - 1)
        candidates: list[tuple[date, datetime]] = []
        for _ in range(20):
            if monday + timedelta(days=6) < start or len(candidates) == limit:
                break
            self._check_cancelled()
            if cancelled is not None and cancelled():
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
            candidate = self._market_data.completed_calendar_week(
                symbol=product, week_monday=monday, as_of=cutoff,
            )
            if candidate is not None:
                candidates.append(candidate)
            monday -= timedelta(days=7)
        return tuple(candidates)

    def current_owner_context(
        self, product: str, at: datetime,
    ) -> dict[str, str | None]:
        """Read current Session owner separately from any historical snapshot."""
        instant = utc_timestamp(at)
        if product not in self._active_products or instant > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_QUERY")
        unknown = {"status": "unknown", "physical_contract": None}
        try:
            days = self._market_data.trading_days_overlapping_window(
                symbol=product, start=instant - timedelta(days=1),
                end=instant + _MICROSECOND,
            )
            active = tuple(
                day for day in days
                if any(window.start <= instant < window.end for window in
                       self._market_data.session_windows(symbol=product, trading_day=day))
            )
            if len(active) != 1:
                return unknown
            owners = self.dependency_owners(product, active[0], active[0])
        except MarketDataError:
            return unknown
        if len(owners) != 1:
            return unknown
        return {"status": "known", "physical_contract": owners[0].contract}

    def weekly_tail_unpublished(self, product: str, week_end: date) -> bool:
        if product not in self._active_products:
            raise NewowProductReadError("NEWOW_INVALID_PRODUCT")
        self._check_cancelled()
        return self._market_data.weekly_tail_unpublished(symbol=product, week_end=week_end)

    def resolve_performance_window(
        self,
        product: str,
        frequency: ProductFrequency,
        performance_since: date | None,
        performance_through: date | None,
        as_of: datetime,
    ) -> ResolvedPerformanceWindow:
        """Resolve the last authoritative completed trading day at the request instant."""

        cutoff = utc_timestamp(as_of)
        frequency = ProductFrequency(frequency)
        if cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")
        if product not in self._active_products:
            raise NewowProductReadError("NEWOW_INVALID_PRODUCT")
        self._check_cancelled()
        since = performance_since or self._coverage.product_start(product)
        latest = self._coverage.latest_complete_day((product,))
        requested_through = performance_through or min(
            latest, cutoff.astimezone(_SHANGHAI).date()
        )
        if since > requested_through:
            raise NewowProductReadError("NEWOW_INVALID_PERFORMANCE_WINDOW")
        start = datetime.combine(
            min(since, cutoff.astimezone(_SHANGHAI).date()), time.min, _SHANGHAI
        )
        requested_end = datetime.combine(requested_through, time.max, _SHANGHAI)
        days = self._market_data.trading_days_overlapping_window(
            symbol=product, start=start, end=max(cutoff + _MICROSECOND, requested_end)
        )
        if not days or any(
            current <= previous for previous, current in zip(days, days[1:])
        ):
            raise NewowProductReadError("NEWOW_DATA_UNAVAILABLE")
        if latest <= cutoff.astimezone(_SHANGHAI).date() and latest not in days:
            raise NewowProductReadError("NEWOW_DATA_UNAVAILABLE")
        complete_days = []
        for day in days:
            self._check_cancelled()
            if (
                day <= requested_through
                and day <= latest
                and max(
                    window.end
                    for window in self._market_data.session_windows(
                        symbol=product, trading_day=day
                    )
                )
                <= cutoff
            ):
                complete_days.append(day)
        if not complete_days or complete_days[-1] < since:
            raise NewowProductReadError("NEWOW_COMPLETE_TRADING_DAY_MISSING")
        actual_through = complete_days[-1]
        resolved_cutoff = max(
            window.end
            for window in self._market_data.session_windows(
                symbol=product, trading_day=actual_through
            )
        )
        requested_days = tuple(day for day in days if since <= day <= requested_through)
        complete = bool(requested_days) and actual_through == requested_days[-1]
        reason = None if complete else "NEWOW_REFERENCE_WINDOW_PARTIAL"
        # W1 completion can only be established after the owned W1 bars are read;
        # the service performs that final alignment instead of guessing by weekday.
        if frequency is ProductFrequency.WEEKLY:
            complete = False
            reason = "NEWOW_REFERENCE_WEEKLY_COMPLETION_PENDING"
        return ResolvedPerformanceWindow(
            since,
            requested_through,
            actual_through,
            utc_timestamp(resolved_cutoff),
            complete,
            reason,
        )

    def resolve_chart_window(
        self,
        product: str,
        frequency: ProductFrequency,
        limit: int,
        as_of: datetime,
    ) -> ProductReadWindow:
        """Choose a bounded authoritative trading-day viewport for recent Bars."""

        window = self._resolve_chart_window(product, frequency, limit, as_of)
        if window is None:
            raise NewowProductReadError("NEWOW_COMPLETE_TRADING_DAY_MISSING")
        return window

    def resolve_older_chart_window(
        self, product: str, frequency: ProductFrequency, limit: int,
        as_of: datetime, before: date,
    ) -> ProductReadWindow | None:
        """Use the same completed-day authority, strictly before a verified window."""
        return self._resolve_chart_window(product, frequency, limit, as_of, before)

    def _resolve_chart_window(
        self, product: str, frequency: ProductFrequency, limit: int,
        as_of: datetime, before: date | None = None,
    ) -> ProductReadWindow | None:

        cutoff = utc_timestamp(as_of)
        if cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")
        if product not in self._active_products:
            raise NewowProductReadError("NEWOW_INVALID_PRODUCT")
        if type(limit) is not int or not 1 <= limit <= 2000:
            raise NewowProductReadError("NEWOW_INVALID_CHART_LIMIT")
        self._check_cancelled()
        start_day = self._coverage.product_start(product)
        latest = self._coverage.latest_complete_day((product,))
        start = datetime.combine(start_day, time.min, _SHANGHAI)
        days = self._market_data.completed_trading_days(
            symbol=product, start=start, as_of=cutoff, latest=latest
        )
        self._check_cancelled()
        if not days or any(
            current <= previous for previous, current in zip(days, days[1:])
        ):
            raise NewowProductReadError("NEWOW_COMPLETE_TRADING_DAY_MISSING")
        if before is not None:
            days = tuple(day for day in days if day < before)
            if not days:
                return None
        bars_per_day = (
            4 if ProductFrequency(frequency) is ProductFrequency.HOURLY else 1
        )
        day_count = (limit + bars_per_day - 1) // bars_per_day
        if ProductFrequency(frequency) is ProductFrequency.WEEKLY:
            day_count *= 7
        return ProductReadWindow(days[max(0, len(days) - day_count)], days[-1])

    def load(self, query: NewowProductQuery, as_of: datetime) -> ProductReadSet:
        """Freeze one read; context periods are optional and never frequency fallbacks."""
        if not isinstance(query, NewowProductQuery):
            raise NewowProductReadError("NEWOW_INVALID_QUERY")
        cutoff = utc_timestamp(query.as_of if query.as_of is not None else as_of)
        if cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")
        if query.product not in self._active_products:
            raise NewowProductReadError("NEWOW_INVALID_PRODUCT")
        policy = input_quality_policy(
            query.frequency.value, self._input_quality_policy
        )
        self._check_cancelled()
        performance_since = query.performance_since
        if performance_since is None:
            performance_since = self._coverage.product_start(query.product)
        lower = min(query.since, performance_since)
        session_cache: dict[date, tuple[SessionWindow, ...]] = {}

        def sessions(day: date) -> tuple[SessionWindow, ...]:
            if day not in session_cache:
                self._check_cancelled()
                value = self._market_data.session_windows(
                    symbol=query.product, trading_day=day
                )
                if not value:
                    raise ActualDominantResearchSegmentIdentityError(
                        "rank1 TradingSession identity is missing or inconsistent"
                    )
                session_cache[day] = value
            return session_cache[day]

        # MDS resolves the authoritative Calendar/Session overlap, including
        # night-session trading-day identity. No local Catalog access or date
        # arithmetic is allowed at this reader boundary.
        start = datetime.combine(
            min(lower, cutoff.astimezone(_SHANGHAI).date()), time.min, _SHANGHAI
        )
        days = self._market_data.trading_days_overlapping_window(
            symbol=query.product, start=start, end=cutoff + _MICROSECOND
        )
        if not days or any(
            current <= previous for previous, current in zip(days, days[1:])
        ):
            raise NewowProductReadError("NEWOW_DATA_UNAVAILABLE")
        performance_through = query.performance_through
        if performance_through is None:
            latest = self._coverage.latest_complete_day((query.product,))
            if latest <= cutoff.astimezone(_SHANGHAI).date() and latest not in days:
                raise NewowProductReadError("NEWOW_DATA_UNAVAILABLE")
            complete = next(
                (
                    day
                    for day in reversed(days)
                    if day <= latest
                    and max(window.end for window in sessions(day)) <= cutoff
                ),
                None,
            )
            if complete is None:
                raise NewowProductReadError("NEWOW_COMPLETE_TRADING_DAY_MISSING")
            performance_through = complete
        performance = ProductReadWindow(performance_since, performance_through)
        replay_through = max(query.through, performance.through)
        frequencies = tuple(
            dict.fromkeys((query.frequency, *self._context_frequencies))
        )
        segment_loader = _AsOfSegmentLoader(
            self._market_data,
            replay_through,
            cutoff,
            self._check_cancelled,
            policy,
        )
        def load_segments(through: date):
            return segment_loader.load(
                symbol=query.product,
                frequencies=tuple(BarFrequency(frequency) for frequency in frequencies),
                since=lower,
                through=through,
                allow_empty_frequencies=(
                    (BarFrequency.W1,) if ProductFrequency.WEEKLY in frequencies else ()
                ),
            )

        try:
            loaded = load_segments(days[-1])
        except MarketDataError as exc:
            completed_days = tuple(
                day for day in days
                if max(window.end for window in sessions(day)) <= cutoff
            )
            if (
                query.frequency is not ProductFrequency.WEEKLY
                or exc.code != "MAIN_CONTRACT_MAP_MISSING"
                or not completed_days
                or completed_days[-1] == days[-1]
            ):
                raise
            days = completed_days
            loaded = load_segments(days[-1])
        owners = tuple(
            replace(segment, end_trading_day=min(segment.end_trading_day, days[-1]))
            for segment in loaded.authoritative_segments
        )
        starts = tuple(
            min(window.start for window in sessions(owner.start_trading_day))
            for owner in owners
        )
        if (
            any(
                normalize_contract_for_symbol(query.product, owner.contract)
                != owner.contract
                for owner in owners
            )
            or any(start > cutoff for start in starts)
            or any(current <= previous for previous, current in zip(starts, starts[1:]))
            or any(
                sum(
                    owner.start_trading_day <= day <= owner.end_trading_day
                    for owner in owners
                )
                != 1
                for day in days
                if day >= lower
            )
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        segment_ids = tuple(
            build_segment_id(query.product, owner.contract, start)
            for owner, start in zip(owners, starts, strict=True)
        )
        boundaries = tuple(
            OwnerBoundary(
                query.product,
                old.contract,
                new.contract,
                segment_ids[index],
                segment_ids[index + 1],
                new.start_trading_day,
                starts[index + 1],
                _OWNER_SOURCE,
            )
            for index, (old, new) in enumerate(zip(owners, owners[1:]))
        )
        grouped: dict[ProductFrequency, tuple[ProductBar, ...]] = {}
        sources: dict[ProductFrequency, ProductReadSource] = {}
        lifecycle_evidence: dict[
            ProductFrequency, tuple[LifecycleReplayEvidence, ...]
        ] = {}
        interruptions_by_frequency: dict[
            ProductFrequency, tuple[DataInterruption, ...]
        ] = {}
        for frequency in frequencies:
            frequency_gaps = segment_loader.price_unavailable_by_frequency.get(
                BarFrequency(frequency), ()
            )
            actual = loaded.results[BarFrequency(frequency)].bars
            ranked = tuple(
                tuple(
                    bar
                    for bar in actual
                    if owner.start_trading_day
                    <= bar.trading_day
                    <= owner.end_trading_day
                )
                for owner in owners
            )
            # One complete read at the largest required cutoff per physical
            # identity. Earlier owner segments use prefixes of that same read.
            contract_ends: dict[str, datetime] = {}
            owner_cutoffs: list[datetime | None] = []
            for owner, bars in zip(owners, ranked, strict=True):
                completed = tuple(
                    day for day in days
                    if owner.start_trading_day <= day <= owner.end_trading_day
                    and day <= replay_through
                    and max(window.end for window in sessions(day)) <= cutoff
                )
                owner_cutoff = (
                    max(window.end for window in sessions(completed[-1]))
                    if completed else None
                ) if frequency is ProductFrequency.DAILY else (
                    max((
                        *(bar.bar_end for bar in bars),
                        *(gap.bar_end for contract, gap in frequency_gaps
                          if contract == owner.contract
                          and owner.start_trading_day <= gap.trading_day <= owner.end_trading_day
                          and gap.bar_end <= cutoff),
                    ), default=None) if frequency is ProductFrequency.WEEKLY else
                    (bars[-1].bar_end if bars else None)
                )
                owner_cutoffs.append(owner_cutoff)
                end = owner_cutoff if frequency in (ProductFrequency.DAILY, ProductFrequency.WEEKLY) else (
                    bars[-1].bar_end if bars else None
                )
                if end is not None:
                    contract_ends[owner.contract] = max(
                        contract_ends.get(owner.contract, end), end,
                    )
            quality_prefix = (
                frequency is ProductFrequency.DAILY
                and getattr(self._market_data, "query_contract_replay_quality", None) is not None
            ) or (
                frequency is ProductFrequency.WEEKLY
                and getattr(self._market_data, "query_contract_weekly_replay_quality", None) is not None
            )
            prefix_gaps: dict[
                str, tuple[PriceUnavailableFact | WeeklySourceInterruption, ...]
            ] = {}
            if quality_prefix:
                prefixes = {}
                for contract, end in contract_ends.items():
                    if frequency is ProductFrequency.DAILY:
                        physical, daily_gaps = self._market_data.query_contract_replay_quality(
                            symbol=query.product, contract=contract,
                            through=end.astimezone(_SHANGHAI).date(), cutoff=end,
                        )
                    else:
                        quality_args = {
                            "symbol": query.product,
                            "contract": contract,
                            "through": end.astimezone(_SHANGHAI).date(),
                            "cutoff": end,
                        }
                        physical, weekly_gaps = (
                            self._market_data.query_contract_weekly_replay_quality(
                                **quality_args
                            )
                            if policy is InputQualityPolicy.V1
                            else self._market_data.query_contract_weekly_replay_quality(
                                **quality_args,
                                classification_version=source_classification_version(
                                    frequency.value, policy
                                ),
                            )
                        )
                    prefixes[contract] = physical
                    prefix_gaps[contract] = (
                        daily_gaps if frequency is ProductFrequency.DAILY else weekly_gaps
                    )
            else:
                prefixes = {
                    contract: self._read_prefix(query.product, contract, frequency, end)
                    for contract, end in contract_ends.items()
                }
            output: list[ProductBar] = []
            segment_outputs: list[tuple[ProductBar, ...]] = []
            raw_bar_count = 0
            no_trade_bar_count = 0
            interruptions: list[DataInterruption] = []
            verified_segments: list[bool] = []
            for owner, segment_id, rank_bars, owner_cutoff in zip(
                owners, segment_ids, ranked, owner_cutoffs, strict=True
            ):
                if owner_cutoff is None or (not rank_bars and not quality_prefix):
                    continue
                prefix = tuple(
                    bar
                    for bar in prefixes[owner.contract]
                    if bar.bar_end <= owner_cutoff
                )
                gaps = tuple(
                    gap for gap in prefix_gaps.get(owner.contract, ())
                    if gap.bar_end <= owner_cutoff
                )
                owned = tuple(
                    bar
                    for bar in prefix
                    if owner.start_trading_day
                    <= bar.trading_day
                    <= owner.end_trading_day
                )
                # Equality includes time, OHLCV, turnover and OI.
                if owned != rank_bars:
                    raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
                ranked_gaps = tuple(
                    gap for contract, gap in frequency_gaps
                    if contract == owner.contract
                    and owner.start_trading_day <= gap.trading_day <= owner.end_trading_day
                    and gap.bar_end <= owner_cutoff
                ) if quality_prefix else ()
                if tuple(gap for gap in gaps if owner.start_trading_day <= gap.trading_day <= owner.end_trading_day) != ranked_gaps:
                    raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
                converted, skipped = _effective_product_bars(
                    query.product,
                    frequency,
                    owner.contract,
                    segment_id,
                    prefix,
                    owner.start_trading_day,
                )
                raw_bar_count += len(prefix)
                no_trade_bar_count += skipped
                output.extend(converted)
                segment_outputs.append(converted)
                verified_segments.append(not gaps)
                interruptions.extend(DataInterruption(
                    product=query.product, frequency=frequency,
                    physical_contract=owner.contract, segment_id=segment_id,
                    trading_day=gap.trading_day, effective_at=gap.bar_end,
                    source_identity=_quality_source_identity(frequency, gap),
                ) for gap in gaps)
            for contract, prefix in prefixes.items():
                if not quality_prefix:
                    self._validate_prefix(query.product, contract, frequency, prefix[-1].bar_end, prefix)
            grouped[frequency] = tuple(output)
            interruptions_by_frequency[frequency] = tuple(sorted(
                interruptions, key=lambda gap: gap.effective_at,
            ))
            lifecycle_evidence[frequency] = tuple(
                LifecycleReplayEvidence(
                    product=query.product,
                    frequency=frequency,
                    physical_contract=segment[0].bar.physical_contract,
                    segment_id=segment[0].bar.segment_id,
                    first_bar_end=segment[0].bar.bar_end,
                    last_bar_end=segment[-1].bar.bar_end,
                    bar_count=len(segment),
                    input_sha256=lifecycle_input_sha256(segment),
                    source_identity=_CANONICAL_SOURCE,
                    verified_cutoff=segment[-1].bar.bar_end,
                )
                for segment, verified in zip(segment_outputs, verified_segments, strict=True)
                if segment and verified
            )
            sources[frequency] = ProductReadSource(
                frequency,
                _CANONICAL_SOURCE,
                actual[-1].bar_end if actual else None,
                cutoff,
                input_policy_version(
                    frequency.value,
                    policy if frequency is ProductFrequency.WEEKLY
                    else InputQualityPolicy.V1,
                ),
                raw_bar_count,
                len(output),
                no_trade_bar_count,
                len(interruptions),
            )
        self._check_cancelled()
        return ProductReadSet(
            query.frequency,
            MappingProxyType(grouped),
            owners,
            boundaries,
            ProductReadWindow(query.since, query.through),
            performance,
            MappingProxyType(sources),
            cutoff,
            MappingProxyType(lifecycle_evidence),
            MappingProxyType(interruptions_by_frequency),
            input_quality_policy=policy,
        )

    def dependency_owners(
        self, product: str, since: date, through: date,
    ) -> tuple[ResolvedContractSegment, ...]:
        """Shared rank1 identity validation before any physical prefix is read."""
        self._check_cancelled()
        if product not in self._active_products:
            raise NewowProductReadError("NEWOW_INVALID_PRODUCT")
        owners = ActualDominantResearchSegmentLoader(self._market_data).owner_segments(
            symbol=product, since=since, through=through,
        )
        if any(normalize_contract_for_symbol(product, owner.contract) != owner.contract
               for owner in owners):
            raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
        self._check_cancelled()
        return tuple(replace(owner, end_trading_day=min(owner.end_trading_day, through))
                     for owner in owners)

    def historical_metadata_evidence(
        self, *, product: str, since: date, through: date,
    ) -> dict[str, object]:
        """Expose exact MDS Calendar/Session proof for P4 source binding."""
        return self._market_data.historical_metadata_evidence(
            symbol=product, since=since, through=through,
        )

    def historical_storage_start(self, product: str) -> date:
        return self._coverage.product_start(product)

    def check_dependency(
        self, product: str, frequency: ProductFrequency,
        owner: ResolvedContractSegment, as_of: datetime,
    ) -> dict[str, object]:
        """Check one owner independently using MDS lifecycle endpoint authority."""
        self._check_cancelled()
        cutoff = utc_timestamp(as_of)
        if product not in self._active_products or cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_QUERY")
        expected = self._market_data.expected_contract_replay_endpoints(
            symbol=product, contract=owner.contract, frequency=BarFrequency(frequency),
            trading_day=owner.end_trading_day, cutoff=cutoff,
        )
        self._check_cancelled()
        owned = tuple(point for point in expected
                      if owner.start_trading_day <= point[1] <= owner.end_trading_day)
        if not owned:
            if frequency is ProductFrequency.WEEKLY:
                return {"status": "NOT_APPLICABLE", "reason": "OWNER_HAS_NO_COMPLETED_BAR"}
            raise NewowProductReadError("NEWOW_COMPLETE_PERIOD_MISSING")
        if frequency is ProductFrequency.WEEKLY:
            prefix, weekly_gaps = self._market_data.query_contract_weekly_replay_quality(
                symbol=product, contract=owner.contract,
                through=owned[-1][1], cutoff=owned[-1][0],
            )
        else:
            prefix = self._read_prefix(product, owner.contract, frequency, owned[-1][0])
            self._validate_prefix(product, owner.contract, frequency, owned[-1][0], prefix,
                                  trading_day=owned[-1][1])
            weekly_gaps = ()
        actual_ends = {bar.bar_end for bar in prefix}
        actual_ends.update(gap.week_end for gap in weekly_gaps)
        if actual_ends != {end for end, _ in expected}:
            from app.market_data.market_data_service import MarketDataError
            raise MarketDataError("CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
                                  reason="REPLAY_ENDPOINTS_MISSING")
        # Canonical coverage remains over every raw row. Only strict futures
        # no-trade facts are absent from the effective strategy observation set.
        segment = build_segment_id(product, owner.contract, owned[0][0])
        effective_bar_count = 0
        no_trade_bar_count = 0
        for bar in prefix:
            self._check_cancelled()
            if _is_strict_no_trade_fact(bar):
                no_trade_bar_count += 1
                continue
            _product_bar(product, frequency, owner.contract, segment, bar,
                         bar.trading_day >= owner.start_trading_day)
            effective_bar_count += 1
        result: dict[str, object] = {"status": "DATA_READY", "expected_bar_count": len(expected),
                "actual_bar_count": len(prefix),
                "effective_bar_count": effective_bar_count,
                "no_trade_bar_count": no_trade_bar_count,
                "input_policy_version": FUTURES_INPUT_POLICY_VERSION,
                "cutoff": owned[-1][0].isoformat()}
        if frequency is ProductFrequency.WEEKLY:
            result["price_unavailable_count"] = len(weekly_gaps)
            result["source_quality"] = "WEEKLY_INTERRUPTED" if weekly_gaps else "NORMAL"
        return result

    def _validate_prefix(
        self, product: str, contract: str, frequency: ProductFrequency, cutoff: datetime,
        prefix: tuple[CanonicalBar, ...],
        *, trading_day: date | None = None,
    ) -> None:
        self._check_cancelled()
        self._market_data.validate_contract_replay_coverage(
            symbol=product, contract=contract, frequency=BarFrequency(frequency),
            trading_day=trading_day or prefix[-1].trading_day, cutoff=cutoff, after=None, bars=prefix,
        )

    def _check_cancelled(self) -> None:
        if self._cancelled is not None and self._cancelled():
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")

    def _read_prefix(
        self, product: str, contract: str, frequency: ProductFrequency, cutoff: datetime
    ) -> tuple[CanonicalBar, ...]:
        before = cutoff
        pages: list[tuple[CanonicalBar, ...]] = []
        inclusive = True
        while True:
            self._check_cancelled()
            request = SeriesPageQuery(
                SeriesKind.CONTRACT,
                product,
                BarFrequency(frequency),
                before,
                _PAGE_SIZE,
                contract,
            )
            page = (
                self._market_data.query_page_inclusive(request)
                if inclusive
                else self._market_data.query_page(request)
            )
            self._check_cancelled()
            expected_cursor_mode = (
                SeriesPageCursorMode.INCLUSIVE
                if inclusive
                else SeriesPageCursorMode.EXCLUSIVE
            )
            if (
                page.cursor_mode is not expected_cursor_mode
                or type(page.has_more_before) is not bool
                or not page.bars
                or len(page.bars) > _PAGE_SIZE
                or page.bars[-1].bar_end > before
                or (not inclusive and page.bars[-1].bar_end == before)
                or page.next_before
                != (page.bars[0].bar_end if page.has_more_before else None)
                or any(
                    page.request_identity.get(key) != value
                    for key, value in {
                        "series_kind": "contract",
                        "symbol": product,
                        "frequency": frequency.value,
                        "contract": contract,
                        "before": before.isoformat(),
                        "limit": _PAGE_SIZE,
                    }.items()
                )
            ):
                raise NewowProductReadError("NEWOW_PREFIX_PAGINATION_INVALID")
            _validate_order(page.bars)
            pages.append(page.bars)
            if not page.has_more_before:
                break
            before = page.bars[0].bar_end
            inclusive = False
        bars = tuple(bar for page in reversed(pages) for bar in page)
        _validate_order(bars)
        return bars


def _validate_order(bars: tuple[CanonicalBar, ...]) -> None:
    if any(
        current.bar_end <= previous.bar_end
        or current.trading_day < previous.trading_day
        for previous, current in zip(bars, bars[1:])
    ):
        raise NewowProductReadError("NEWOW_DATA_OUT_OF_ORDER")


def _is_strict_no_trade_fact(bar: CanonicalBar) -> bool:
    """Classify an authoritative futures no-trade fact without synthesizing price."""
    zero = Decimal(0)
    return (
        bar.open == zero
        and bar.high == zero
        and bar.low == zero
        and bar.close == zero
        and bar.volume == zero
        and bar.turnover == zero
    )


def _effective_product_bars(
    product: str,
    frequency: ProductFrequency,
    contract: str,
    segment_id: str,
    bars: tuple[CanonicalBar, ...],
    owner_start: date,
) -> tuple[tuple[ProductBar, ...], int]:
    output: list[ProductBar] = []
    skipped = 0
    for bar in bars:
        if _is_strict_no_trade_fact(bar):
            skipped += 1
            continue
        output.append(
            _product_bar(
                product,
                frequency,
                contract,
                segment_id,
                bar,
                bar.trading_day >= owner_start,
            )
        )
    return tuple(output), skipped


def _product_bar(
    product: str,
    frequency: ProductFrequency,
    contract: str,
    segment_id: str,
    bar: CanonicalBar,
    eligible: bool,
) -> ProductBar:
    if bar.volume != bar.volume.to_integral_value() or (
        bar.open_interest is not None
        and bar.open_interest != bar.open_interest.to_integral_value()
    ):
        raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
    try:
        source_bar_sha256 = sha256(json.dumps(
            (
                bar.bar_end.isoformat(), bar.trading_day.isoformat(),
                str(bar.open), str(bar.high), str(bar.low), str(bar.close),
                str(bar.volume), str(bar.turnover),
                None if bar.open_interest is None else str(bar.open_interest),
            ),
            separators=(",", ":"),
        ).encode()).hexdigest()
        return ProductBar(
            NewowDailyBar(
                product,
                contract,
                segment_id,
                bar.trading_day,
                bar.bar_end,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                int(bar.volume),
                None if bar.open_interest is None else int(bar.open_interest),
                (
                    f"{_CANONICAL_SOURCE}:{FUTURES_INPUT_POLICY_VERSION}:"
                    f"{product}:{frequency}:{contract}"
                ),
                eligible,
                True,
            ),
            frequency,
            source_bar_sha256=source_bar_sha256,
        )
    except ValueError as exc:
        if str(exc) == "NEWOW_BAR_NONPOSITIVE_PRICE":
            raise NewowProductReadError(
                "NEWOW_SOURCE_NONPOSITIVE_PRICE",
                context={"symbol": product, "contract": contract, "frequency": frequency,
                         "trading_day": bar.trading_day, "cutoff": bar.bar_end},
            ) from exc
        raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID") from exc
