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
from guiyi_quant.newow.escape_d123 import initial_escape_state, step_escape_d123
from guiyi_quant.newow.main_rise import (
    MAIN_RISE_PAGE_V1,
    initial_main_rise_state,
    step_main_rise,
)
from guiyi_quant.newow.oscillation_channel import (
    OscillationAction,
    OscillationState,
    step_oscillation,
)
from guiyi_quant.newow.product_contracts import (
    ActionKind,
    FeatureStatus,
    MainState,
    OwnerBoundary,
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
    StrategyAction,
    StrategyFrame,
    StrategyReplay,
)
from guiyi_quant.newow.product_identity import build_segment_id
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.trend_band import initial_trend_band_state, step_trend_band


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


@dataclass(frozen=True)
class PrimitiveOracle:
    main_values: tuple
    hint_facts: tuple[tuple[datetime, str, Decimal], ...]


@dataclass(frozen=True)
class PrimitiveInput:
    identity: ProductIdentity
    bars: tuple[ProductBar, ...]

    def run_original_primitive(self) -> PrimitiveOracle:
        """Map direct primitive outputs without importing the product adapter."""
        if self.identity.strategy == "trend":
            return _trend_oracle(self.identity, self.bars)
        if self.identity.strategy == "oscillation":
            return _oscillation_oracle(self.identity, self.bars)
        return _main_rise_oracle(self.identity, self.bars)


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _action(
    identity: ProductIdentity,
    bar: ProductBar,
    kind: str,
    price: Decimal,
    sequence: int,
    *,
    related_build_id: str | None = None,
    source_marker_id: str | None = None,
    source_related_marker_ids: tuple[str, ...] = (),
) -> StrategyAction:
    return StrategyAction(
        identity=identity,
        physical_contract=bar.bar.physical_contract,
        segment_id=bar.bar.segment_id,
        bar_end=bar.bar.bar_end,
        trading_day=bar.bar.trading_day,
        kind=ActionKind(kind),
        reference_price=price,
        anchor_price=price,
        sequence=sequence,
        related_build_id=related_build_id,
        source_marker_id=source_marker_id,
        source_related_marker_ids=source_related_marker_ids,
    )


def _trend_oracle(
    identity: ProductIdentity, bars: tuple[ProductBar, ...]
) -> PrimitiveOracle:
    trend_state = initial_trend_band_state()
    escape_state = initial_escape_state()
    source_builds: dict[str, StrategyAction] = {}
    rows = []
    hints: list[tuple[datetime, str, Decimal]] = []
    for product_bar in bars:
        result = step_trend_band(
            trend_state, product_bar.bar, profile=NEWOW_TREND_D1_PAGE_V2
        )
        trend_state = result.state
        escape = step_escape_d123(
            escape_state, product_bar.bar, profile=NEWOW_TREND_D1_PAGE_V2
        )
        escape_state = escape.state
        actions: tuple[StrategyAction, ...] = ()
        if result.marker is not None:
            marker = result.marker
            related = None
            if marker.marker_type == "CLEAR":
                assert len(marker.related_marker_ids) == 1
                related = source_builds[marker.related_marker_ids[0]].signal_id
            action = _action(
                identity,
                product_bar,
                marker.marker_type,
                marker.price,
                0,
                related_build_id=related,
                source_marker_id=marker.marker_id,
                source_related_marker_ids=marker.related_marker_ids,
            )
            if action.kind is ActionKind.BUILD:
                source_builds[marker.marker_id] = action
            actions = (action,)
        point = result.point
        state = (
            MainState.BUILD
            if actions and actions[-1].kind is ActionKind.BUILD
            else MainState.CLEAR
            if actions
            else MainState.HOLD
            if point.state == "YELLOW"
            else MainState.FLAT
            if point.state == "BLUE"
            else MainState.UNAVAILABLE
        )
        rows.append(
            (
                product_bar.bar.bar_end,
                state,
                (("a", _decimal(point.b_value)), ("b", _decimal(point.c_value))),
                actions,
            )
        )
        hints.extend(
            (product_bar.bar.bar_end, marker.marker_type.value, marker.price)
            for marker in escape.markers
        )
    return PrimitiveOracle(tuple(rows), tuple(hints))


def _oscillation_oracle(
    identity: ProductIdentity, bars: tuple[ProductBar, ...]
) -> PrimitiveOracle:
    state = OscillationState()
    open_build: StrategyAction | None = None
    rows = []
    for product_bar in bars:
        result = step_oscillation(state, product_bar.bar)
        state = result.state
        actions = []
        for sequence, signal in enumerate(result.signals):
            related = None
            if signal.action is OscillationAction.CLEAR:
                assert open_build is not None
                related = open_build.signal_id
            action = _action(
                identity,
                product_bar,
                signal.action,
                signal.price,
                sequence,
                related_build_id=related,
            )
            open_build = action if action.kind is ActionKind.BUILD else None
            actions.append(action)
        channel = result.channel
        values = (
            (
                ("upper", None),
                ("lower", None),
                ("width", None),
                ("close_position", None),
            )
            if channel is None
            else (
                ("upper", channel.upper),
                ("lower", channel.lower),
                ("width", channel.width),
                ("close_position", channel.close_position),
            )
        )
        main_state = (
            MainState.BUILD
            if actions and actions[-1].kind is ActionKind.BUILD
            else MainState.CLEAR
            if actions
            else MainState.HOLD
            if result.state.holding
            else MainState.FLAT
        )
        rows.append((product_bar.bar.bar_end, main_state, values, tuple(actions)))
    return PrimitiveOracle(tuple(rows), ())


def _main_rise_oracle(
    identity: ProductIdentity, bars: tuple[ProductBar, ...]
) -> PrimitiveOracle:
    state = initial_main_rise_state()
    open_build: StrategyAction | None = None
    rows = []
    hints: list[tuple[datetime, str, Decimal]] = []
    for product_bar in bars:
        result = step_main_rise(state, product_bar.bar, formulas=MAIN_RISE_PAGE_V1)
        state = result.state
        actions: tuple[StrategyAction, ...] = ()
        if result.band_signal is not None:
            signal = result.band_signal
            related = None
            if signal.action == "CLEAR":
                assert open_build is not None
                related = open_build.signal_id
            action = _action(
                identity,
                product_bar,
                signal.action,
                signal.price,
                0,
                related_build_id=related,
            )
            open_build = action if action.kind is ActionKind.BUILD else None
            actions = (action,)
        main_state = (
            MainState.BUILD
            if actions and actions[-1].kind is ActionKind.BUILD
            else MainState.CLEAR
            if actions
            else MainState.HOLD
            if result.band_state == "YELLOW"
            else MainState.FLAT
            if result.band_state == "BLUE"
            else MainState.UNAVAILABLE
        )
        rows.append(
            (
                product_bar.bar.bar_end,
                main_state,
                (("ma35", _decimal(result.ma35)), ("ma45", _decimal(result.ma45))),
                actions,
            )
        )
        hints.extend(
            (product_bar.bar.bar_end, marker.marker_type.value, marker.price)
            for marker in result.escape_markers
        )
        if result.reduce_signal is not None:
            hints.append((product_bar.bar.bar_end, "J", result.reduce_signal.price))
        hints.extend(
            (product_bar.bar.bar_end, marker.kind.value, marker.price)
            for marker in result.buy_markers
        )
        if result.magic11.marker is not None:
            hints.append(
                (
                    product_bar.bar.bar_end,
                    f"MAGIC11:{result.magic11.marker.label.value}",
                    result.magic11.marker.price,
                )
            )
    return PrimitiveOracle(tuple(rows), tuple(hints))


class ProductCases:
    def primitive_input(self, strategy: str, frequency: str) -> PrimitiveInput:
        """Owned synthetic OHLC with enough turns to exercise every active wrapper."""
        formulas = {
            "trend": (
                "newow_trend_band_page_v2",
                "newow_escape_d123_page_v2",
            ),
            "oscillation": (
                "newow_oscillation_hhv_llv10_page_v1",
                "newow_hhv_llv_channel_page_v1",
            ),
            "main_rise": tuple(
                getattr(MAIN_RISE_PAGE_V1, name)
                for name in (
                    "band_formula",
                    "j_reduce_formula",
                    "escape_formula",
                    "buy_formula",
                    "magic11_formula",
                )
            ),
        }
        identity = ProductIdentity(
            "rb",
            ProductStrategy(strategy),
            ProductFrequency(frequency),
            formulas[strategy],
        )
        segment = build_segment_id("rb", "RB2710", datetime(2026, 1, 1, tzinfo=UTC))
        bars = []
        for index in range(90):
            phase = index % 24
            center = Decimal(
                100 + (phase if phase < 12 else 24 - phase) * 3 + (index // 24) * 2
            )
            if frequency == "60m":
                trading_day = date(2026, 1, 1) + timedelta(days=index // 4)
                bar_end = datetime.combine(
                    trading_day, datetime.min.time(), UTC
                ) + timedelta(hours=2 + index % 4)
            else:
                step_days = 7 if frequency == "1w" else 1
                trading_day = date(2026, 1, 1) + timedelta(days=index * step_days)
                bar_end = datetime.combine(
                    trading_day, datetime.min.time(), UTC
                ) + timedelta(hours=7)
            eligible = strategy != "main_rise" or index >= 50
            bars.append(
                ProductBar(
                    NewowDailyBar(
                        product="rb",
                        physical_contract="RB2710",
                        segment_id=segment,
                        trading_day=trading_day,
                        bar_end=bar_end,
                        open=center,
                        high=center + Decimal("2"),
                        low=center - Decimal("2"),
                        close=center,
                        volume=600 if index % 13 == 0 else 100,
                        open_interest=200,
                        source_identity=f"owned:primitive:{strategy}:{frequency}:{index}",
                        observation_eligible=eligible,
                        completed=True,
                    ),
                    ProductFrequency(frequency),
                )
            )
        return PrimitiveInput(identity, tuple(bars))

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
