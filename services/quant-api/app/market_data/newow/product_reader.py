"""Request-scoped completed inputs and authoritative owner facts, without signals."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    OwnerBoundary,
    ProductBar,
    ProductFrequency,
)
from guiyi_quant.newow.product_identity import build_segment_id, utc_timestamp

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
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from app.market_data.market_data_service import MarketDataService

from .product_query import NewowProductQuery, ProductReadWindow

_PAGE_SIZE = 2000
_MICROSECOND = timedelta(microseconds=1)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CANONICAL_SOURCE = "market_data_service:canonical_v2"
_OWNER_SOURCE = "main_contract_map:rank1:calendar_session_v1"


class NewowProductReadError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class NewowProductReadCancelled(RuntimeError):
    """The caller cancelled; no partial read set may escape."""


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

    @property
    def replay_bars(self) -> tuple[ProductBar, ...]:
        """Segment-ordered inputs; each segment has its own lifecycle prefix."""
        return self.bars_by_frequency[self.frequency]


class _AsOfSegmentLoader(ActualDominantResearchSegmentLoader):
    """Retain the shared owner validator while bounding its day-based read."""

    def __init__(
        self,
        market_data: MarketDataService,
        through: date,
        as_of: datetime,
        check_cancelled: Callable[[], None],
    ) -> None:
        super().__init__(market_data)
        self._through = through
        self._as_of = as_of
        self._check_cancelled = check_cancelled

    def _query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult:
        self._check_cancelled()
        bounded = replace(request, through=min(request.through, self._through))
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
    ) -> None:
        self._market_data = market_data
        self._coverage = coverage
        self._active_products = frozenset(active_products)
        self._context_frequencies = tuple(
            ProductFrequency(value) for value in context_frequencies
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._cancelled = cancelled

    def load(self, query: NewowProductQuery, as_of: datetime) -> ProductReadSet:
        """Freeze one read; context periods are optional and never frequency fallbacks."""
        if not isinstance(query, NewowProductQuery):
            raise NewowProductReadError("NEWOW_INVALID_QUERY")
        cutoff = utc_timestamp(query.as_of if query.as_of is not None else as_of)
        if cutoff > utc_timestamp(self._now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")
        if query.product not in self._active_products:
            raise NewowProductReadError("NEWOW_INVALID_PRODUCT")
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
        frequencies = tuple(
            dict.fromkeys((query.frequency, *self._context_frequencies))
        )
        loaded = _AsOfSegmentLoader(
            self._market_data,
            max(query.through, performance.through),
            cutoff,
            self._check_cancelled,
        ).load(
            symbol=query.product,
            frequencies=tuple(BarFrequency(frequency) for frequency in frequencies),
            since=lower,
            through=days[-1],
            allow_empty_frequencies=(
                (BarFrequency.W1,) if ProductFrequency.WEEKLY in frequencies else ()
            ),
        )
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
        for frequency in frequencies:
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
            for owner, bars in zip(owners, ranked, strict=True):
                if bars:
                    contract_ends[owner.contract] = max(
                        contract_ends.get(owner.contract, bars[-1].bar_end),
                        bars[-1].bar_end,
                    )
            prefixes = {
                contract: self._read_prefix(query.product, contract, frequency, end)
                for contract, end in contract_ends.items()
            }
            output: list[ProductBar] = []
            for owner, segment_id, rank_bars in zip(
                owners, segment_ids, ranked, strict=True
            ):
                if not rank_bars:  # In particular, a valid W1 owner can have no Bar.
                    continue
                prefix = tuple(
                    bar
                    for bar in prefixes[owner.contract]
                    if bar.bar_end <= rank_bars[-1].bar_end
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
                output.extend(
                    _product_bar(
                        query.product,
                        frequency,
                        owner.contract,
                        segment_id,
                        bar,
                        bar.trading_day >= owner.start_trading_day,
                    )
                    for bar in prefix
                )
            for contract, prefix in prefixes.items():
                self._check_cancelled()
                self._market_data.validate_contract_replay_coverage(
                    symbol=query.product,
                    contract=contract,
                    frequency=BarFrequency(frequency),
                    trading_day=prefix[-1].trading_day,
                    cutoff=prefix[-1].bar_end,
                    after=None,
                    bars=prefix,
                )
            grouped[frequency] = tuple(output)
            sources[frequency] = ProductReadSource(
                frequency,
                _CANONICAL_SOURCE,
                actual[-1].bar_end if actual else None,
                cutoff,
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
            if (
                type(page.has_more_before) is not bool
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
                f"{_CANONICAL_SOURCE}:{product}:{frequency}:{contract}",
                eligible,
                True,
            ),
            frequency,
        )
    except ValueError as exc:
        raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID") from exc
