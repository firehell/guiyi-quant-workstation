"""Owned, explicit product facts; no strategy formula computes test expectations."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageCursorMode,
    SeriesPageQuery,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    FeatureStatus,
    OwnerBoundary,
    ProductBar,
    ProductIdentity,
    StrategyAction,
    StrategyFrame,
    StrategyReplay,
)
from guiyi_quant.newow.product_identity import build_segment_id


@dataclass(frozen=True)
class CaseWindow:
    """Test-only bounds, to be consumed by the later statistics task."""

    since: datetime
    through: datetime


@dataclass(frozen=True)
class ProductCase:
    identity: ProductIdentity
    bars: tuple[ProductBar, ...]
    replay: StrategyReplay
    entry: StrategyAction
    exit: StrategyAction | None
    boundaries: tuple[OwnerBoundary, ...]
    as_of: datetime
    window: CaseWindow


class ProductCases:
    def paged_reader(
        self, prefix_bars=4001, page_size=2000, frequency="60m", context_frequencies=()
    ):
        """A real product reader over owned, recording MDS/coverage facts."""
        from app.market_data.newow.product_query import NewowProductQuery
        from app.market_data.newow.product_reader import NewowProductReader

        fake = _PagedMarketData(prefix_bars, page_size, frequency, context_frequencies)
        self.as_of = fake.as_of
        reader = NewowProductReader(
            cast(MarketDataService, fake),
            coverage=fake.coverage,
            active_products=("rb",),
            context_frequencies=context_frequencies,
            now=lambda: fake.as_of,
        )
        query = NewowProductQuery(
            product="rb",
            strategy="trend",
            frequency=frequency,
            since=fake.segments[0].start_trading_day,
            through=fake.segments[-1].end_trading_day,
            performance_since=fake.segments[0].start_trading_day,
            performance_through=fake.segments[-1].end_trading_day,
        )
        return reader, query, fake

    def closed(self, strategy="trend", frequency="1d", entry="100", exit="110"):
        formulas = {
            "trend": ("newow_trend_band_page_v2",),
            "oscillation": (
                "newow_oscillation_hhv_llv10_page_v1",
                "newow_hhv_llv_channel_page_v1",
            ),
            "main_rise": ("newow_main_rise_ma35_ma45_page_v1",),
        }
        identity = ProductIdentity("rb", strategy, frequency, formulas[strategy])
        start = datetime(2026, 1, 5, tzinfo=UTC)
        segment = build_segment_id("rb", "RB2605", start)
        times = (
            (datetime(2026, 1, 5, 2, tzinfo=UTC), datetime(2026, 1, 5, 3, tzinfo=UTC))
            if frequency == "60m"
            else (
                datetime(2026, 1, 5, 7, tzinfo=UTC),
                datetime(2026, 1, 6, 7, tzinfo=UTC),
            )
        )
        bars = tuple(
            ProductBar(
                bar=NewowDailyBar(
                    product="rb",
                    physical_contract="RB2605",
                    segment_id=segment,
                    trading_day=end.date(),
                    bar_end=end,
                    open=Decimal(price),
                    high=Decimal(price) * Decimal("1.1"),
                    low=Decimal(price) * Decimal("0.9"),
                    close=Decimal(price),
                    volume=100,
                    open_interest=200,
                    source_identity=f"owned:{index}",
                    observation_eligible=True,
                    completed=True,
                ),
                frequency=frequency,
            )
            for index, (end, price) in enumerate(zip(times, (entry, exit), strict=True))
        )
        build = self.action(identity, bars[0], "BUILD", entry)
        clear = self.action(
            identity, bars[1], "CLEAR", exit, related_build_id=build.signal_id
        )
        replay = self.replay(identity, bars, (build, clear), ("BUILD", "CLEAR"))
        return ProductCase(
            identity,
            bars,
            replay,
            build,
            clear,
            (),
            datetime(2026, 1, 9, 16, tzinfo=UTC),
            CaseWindow(start, datetime(2026, 1, 9, 16, tzinfo=UTC)),
        )

    def action(self, identity, bar, kind, price, **kwargs):
        return StrategyAction(
            identity=identity,
            physical_contract=bar.bar.physical_contract,
            segment_id=bar.bar.segment_id,
            bar_end=bar.bar.bar_end,
            trading_day=bar.bar.trading_day,
            kind=kind,
            reference_price=Decimal(price),
            anchor_price=Decimal(price),
            source_marker_id=f"owned:{kind}:{bar.bar.bar_end.isoformat()}",
            **kwargs,
        )

    def replay(self, identity, bars, actions, states):
        frames = tuple(
            StrategyFrame(
                bar=bar,
                main_state=state,
                main_values=(("reference", bar.bar.close),),
                actions=tuple(a for a in actions if a.bar_end == bar.bar.bar_end),
                availability=FeatureStatus("ready", "ACTIVE_CODE_VERIFIED"),
            )
            for bar, state in zip(bars, states, strict=True)
        )
        return StrategyReplay(identity, frames, actions, (), ())

    def open(self):
        case = self.closed()
        return replace(
            case,
            exit=None,
            replay=self.replay(
                case.identity,
                case.bars,
                (case.entry,),
                ("BUILD", "HOLD"),
            ),
        )

    def interrupted(self, mark="90"):
        case = self.open()
        value = Decimal(mark)
        last = replace(
            case.bars[-1],
            bar=replace(
                case.bars[-1].bar,
                open=value,
                high=value * Decimal("1.1"),
                low=value * Decimal("0.9"),
                close=value,
            ),
        )
        bars = (case.bars[0], last)
        effective_at = datetime(2026, 1, 7, tzinfo=UTC)
        boundary = OwnerBoundary(
            product="rb",
            old_contract="RB2605",
            new_contract="RB2610",
            old_segment_id=case.entry.segment_id,
            new_segment_id=build_segment_id("rb", "RB2610", effective_at),
            effective_trading_day=date(2026, 1, 7),
            effective_at=effective_at,
            source_identity="owned:authoritative-owner-boundary",
        )
        return replace(
            case,
            bars=bars,
            boundaries=(boundary,),
            replay=self.replay(
                case.identity,
                bars,
                (case.entry,),
                ("BUILD", "HOLD"),
            ),
        )

    def same_bar_rebuild(self):
        case = self.closed(strategy="oscillation")
        rebuild = self.action(case.identity, case.bars[-1], "BUILD", "105", sequence=1)
        return replace(
            case,
            replay=self.replay(
                case.identity,
                case.bars,
                (case.entry, case.exit, rebuild),
                ("BUILD", "BUILD"),
            ),
        )

    def warmup_only_build(self):
        case = self.closed()
        first = replace(
            case.bars[0], bar=replace(case.bars[0].bar, observation_eligible=False)
        )
        entry = replace(case.entry, trade_eligibility="WARMUP_ONLY")
        clear = replace(case.exit, trade_eligibility="NO_ELIGIBLE_ENTRY")
        bars = (first, case.bars[1])
        return replace(
            case,
            bars=bars,
            entry=entry,
            exit=clear,
            replay=self.replay(
                case.identity,
                bars,
                (entry, clear),
                ("BUILD", "CLEAR"),
            ),
        )


class _PagedCoverage:
    def __init__(self, start, through):
        self.start = start
        self.through = through
        self.requests = []

    def product_start(self, symbol):
        self.requests.append(("product_start", symbol))
        return self.start

    def latest_complete_day(self, products):
        self.requests.append(("latest_complete_day", products))
        return self.through


class _PagedMarketData:
    """Only the read seams used by paged_reader; never opens a real service."""

    def __init__(self, count, page_size, frequency, context_frequencies):
        start = date(2023, 1, 2)
        self.page_size = page_size
        self.actual = {}
        self.physical = {}
        self.physical_page_requests = []
        self.inclusive_page_requests = []
        self.physical_page_sizes = []
        self.actual_requests = []
        self.owner_requests = []
        self.coverage_requests = []
        self.session_requests = []
        self.failures = {}
        self.page_transform = lambda request, page: page
        self.actual_transform = lambda request, result: result
        for period in dict.fromkeys((frequency, *context_frequencies)):
            bars = []
            for index in range(count):
                day = start + timedelta(
                    days=index // 4
                    if period == "60m"
                    else index * (7 if period == "1w" else 1)
                )
                end = datetime.combine(day, datetime.min.time(), UTC) + timedelta(
                    hours=2 + index % 4 if period == "60m" else 7
                )
                bars.append(
                    CanonicalBar(
                        end,
                        day,
                        Decimal("100"),
                        Decimal("110"),
                        Decimal("90"),
                        Decimal("101"),
                        Decimal("10"),
                        None,
                        Decimal("20"),
                    )
                )
            self.physical[("RB2605", BarFrequency(period))] = tuple(bars)
        through = max(bars[-1].trading_day for bars in self.physical.values())
        owner_start = start + timedelta(days=2) if count > 8 else start
        self.segments = (ResolvedContractSegment("RB2605", owner_start, through),)
        for (_, period), bars in self.physical.items():
            self.actual[period] = tuple(
                bar for bar in bars if bar.trading_day >= owner_start
            )
        self.expected_physical = dict(self.physical)
        self.sessions = {
            day: (
                SessionWindow(
                    datetime.combine(day, datetime.min.time(), UTC)
                    + timedelta(hours=1),
                    datetime.combine(day, datetime.min.time(), UTC)
                    + timedelta(hours=7),
                ),
            )
            for day in (
                start + timedelta(days=index)
                for index in range((through - start).days + 1)
            )
        }
        self.as_of = datetime.combine(through, datetime.min.time(), UTC) + timedelta(
            hours=8
        )
        self.coverage = _PagedCoverage(owner_start, through)
        self.catalog = self

    def _fail(self, stage):
        if stage in self.failures:
            raise self.failures[stage]

    def trading_days_overlapping_window(self, symbol, start, end):
        self._fail("calendar")
        return tuple(
            day
            for day, windows in sorted(self.sessions.items())
            if any(window.start < end and start < window.end for window in windows)
        )

    def actual_dominant_segments(self, symbol, since, through):
        self.owner_requests.append((symbol, since, through))
        self._fail("owner")
        return tuple(
            segment
            for segment in self.segments
            if segment.end_trading_day >= since and segment.start_trading_day <= through
        )

    def session_windows(self, *, symbol, trading_day):
        self.session_requests.append((symbol, trading_day))
        self._fail("session")
        if not self.sessions.get(trading_day):
            raise MarketDataError("TRADING_SESSION_MISSING")
        return self.sessions[trading_day]

    def query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ):
        self.actual_requests.append(request)
        self._fail("actual")
        bars = tuple(
            bar
            for bar in self.actual[request.frequency]
            if request.since <= bar.trading_day <= request.through
        )
        resolved = tuple(
            ResolvedContractSegment(
                segment.contract, owned[0].trading_day, owned[-1].trading_day
            )
            for segment in self.segments
            if (
                owned := tuple(
                    bar
                    for bar in bars
                    if segment.start_trading_day
                    <= bar.trading_day
                    <= segment.end_trading_day
                )
            )
        )
        return self.actual_transform(
            request,
            MarketSeriesResult(
                {
                    "series_kind": "actual_dominant",
                    "symbol": request.symbol,
                    "frequency": request.frequency.value,
                    "contract": None,
                    "start": min(
                        window.start for window in self.sessions[request.since]
                    ).isoformat(),
                    "end": max(
                        window.end for window in self.sessions[request.through]
                    ).isoformat(),
                },
                bars,
                (bars[0].bar_end, bars[-1].bar_end) if bars else None,
                resolved,
                (request.since, request.through),
            ),
        )

    def query_page(self, request: SeriesPageQuery):
        self.physical_page_requests.append(request)
        return self._physical_page(
            request,
            inclusive_before=False,
            cursor_mode=SeriesPageCursorMode.EXCLUSIVE,
        )

    def query_page_inclusive(self, request: SeriesPageQuery):
        self.inclusive_page_requests.append(request)
        self.physical_page_requests.append(request)
        return self._physical_page(
            request,
            inclusive_before=True,
            cursor_mode=SeriesPageCursorMode.INCLUSIVE,
        )

    def _physical_page(
        self,
        request: SeriesPageQuery,
        *,
        inclusive_before: bool,
        cursor_mode: SeriesPageCursorMode,
    ):
        self._fail("physical")
        assert request.series_kind is SeriesKind.CONTRACT
        assert request.contract is not None
        values = tuple(
            bar
            for bar in self.physical[(request.contract, request.frequency)]
            if request.before is None
            or bar.bar_end < request.before
            or (inclusive_before and bar.bar_end == request.before)
        )
        limit = min(request.limit, self.page_size)
        page = values[-limit:]
        self.physical_page_sizes.append(len(page))
        return self.page_transform(
            request,
            MarketSeriesPageResult(
                {
                    "series_kind": "contract",
                    "symbol": request.symbol,
                    "contract": request.contract,
                    "frequency": request.frequency.value,
                    "before": request.before.isoformat() if request.before else None,
                    "limit": request.limit,
                },
                page,
                (page[0].bar_end, page[-1].bar_end) if page else None,
                len(values) > limit,
                page[0].bar_end if len(values) > limit else None,
                (),
                cursor_mode,
            ),
        )

    def validate_contract_replay_coverage(
        self, *, symbol, contract, frequency, trading_day, cutoff, after, bars
    ):
        self.coverage_requests.append(
            (symbol, contract, frequency, trading_day, cutoff, after)
        )
        self._fail("lifecycle")
        expected = tuple(
            bar
            for bar in self.expected_physical[(contract, frequency)]
            if bar.bar_end <= cutoff and (after is None or bar.bar_end > after)
        )
        if tuple((bar.bar_end, bar.trading_day) for bar in bars) != tuple(
            (bar.bar_end, bar.trading_day) for bar in expected
        ):
            raise MarketDataError("CONTRACT_REPLAY_COVERAGE_UNAVAILABLE")
