from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Literal

from guiyi_quant.newow import (
    CHANNEL_OPTIMIZER_CAUSAL_V1,
    CHANNEL_OPTIMIZER_PAGE_V1,
    COMPOSITE_DECISION_CLEANROOM_V1,
    COMPOSITE_DECISION_PAGE_V3282,
    DIAGNOSTIC_FACTS_CLEANROOM_V1,
    DIAGNOSTIC_RULES_CLEANROOM_V1,
    FIRST_ACTION_PRINCIPLE_PAGE_V3263,
    MAIN_FORCE_CONTROL_FORMULA_VERSION,
    MAIN_RISE_PAGE_V1,
    OSCILLATION_FORMULA_VERSION,
    TARGET_ABSORB_CHANNEL_PAGE_V1,
    TARGET_ABSORB_DISPLAY_PAGE_V2,
    CleanroomCompositeDecision,
    CompositeDecision,
    DiagnosticFacts,
    DiagnosticInputs,
    DiagnosticPrimitiveIdentity,
    DiagnosticToken,
    DisplayPeriod,
    DisplayPriceSelection,
    FirstActionPrinciple,
    MultiPeriodOscillationState,
    MultiPeriodPriceFacts,
    MultiPeriodTrendState,
    NewowResearchBar,
    OscillationStatus,
    PageChannelWindowResult,
    PageSignalState,
    PriceChannelPoint,
    TrendSignal,
    WeeklyDailyTrendState,
    build_diagnostic_facts,
    calculate_cleanroom_composite_decision,
    calculate_composite_decision,
    calculate_first_action_principle,
    calculate_main_force_control,
    calculate_main_rise_series,
    calculate_price_channel,
    diagnostic_tokens,
    rank_page_channel_windows,
    select_display_prices,
)
from guiyi_quant.newow.cup_handle import cup_evaluation_ready
from guiyi_quant.newow.engine import NewowTrendD1Engine, NewowTrendD1EngineState
from guiyi_quant.newow.escape_d123 import escape_evaluation_ready
from guiyi_quant.newow.main_rise import MainRiseState
from guiyi_quant.newow.models import (
    NewowCupHandleOverlay,
    NewowDailyBar,
    NewowMainMarker,
    NewowMarkerType,
    NewowTrendBandPoint,
    NewowTrendFrame,
    TrendBandState,
)
from guiyi_quant.newow.oscillation_channel import OscillationState, step_oscillation
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.subplots import MainForceControlResult
from guiyi_quant.newow.trend_band import initial_trend_band_state, step_trend_band

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSegmentLoader,
    ActualDominantResearchSourceTradingDayMissingError,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.product_taxonomy import ProductTaxonomyEntry

from .trend_detail_query import MAX_VISIBLE_TRADING_DAYS, NewowTrendDetailQuery

_PREFIX_LIMIT = 2000
_CANONICAL_AUTHORITY = "market_data_service:canonical_v2"
_RANK1_MAPPING_AUTHORITY = "main_contract_map:rank1:canonical_v1"
_PROFILE = NEWOW_TREND_D1_PAGE_V2


class NewowTrendDetailError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NewowInstrumentContext:
    product: str
    display_name: str | None
    last_visible_physical_contract: str | None
    frequency: str
    series_kind: str
    profile_id: str
    formula_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NewowRolloverSeam:
    trading_day: date
    previous_contract: str
    next_contract: str
    previous_bar_end: datetime
    next_bar_end: datetime
    previous_segment_id: str
    next_segment_id: str


@dataclass(frozen=True, slots=True)
class NewowFrequencyPriceChannel:
    frequency: str
    points: tuple[PriceChannelPoint, ...]
    owner_segment_ids: tuple[str, ...]
    formula_version: str = TARGET_ABSORB_CHANNEL_PAGE_V1


@dataclass(frozen=True, slots=True)
class NewowPriceChannelFacts:
    daily: NewowFrequencyPriceChannel
    weekly: NewowFrequencyPriceChannel
    sixty_minute: NewowFrequencyPriceChannel
    display: DisplayPriceSelection


@dataclass(frozen=True, slots=True)
class NewowSemanticLabels:
    page_parity: Literal[True] = True
    cleanroom_separated: Literal[True] = True
    observation_only: Literal[True] = True
    causal_research_result: Literal[False] = False
    repainting_input_used: Literal[False] = False


@dataclass(frozen=True, slots=True)
class NewowTrendDetailResult:
    calculation_identity: str
    data_revision_identity: str | None
    request_identity: str
    instrument: NewowInstrumentContext
    bars: tuple[NewowDailyBar, ...]
    frames: tuple[NewowTrendFrame, ...]
    markers: tuple[NewowMainMarker, ...]
    cup_handles: tuple[NewowCupHandleOverlay, ...]
    rollover_seams: tuple[NewowRolloverSeam, ...]
    price_channel: NewowPriceChannelFacts
    page_window_comparison: tuple[PageChannelWindowResult, ...]
    composite_page: CompositeDecision | None
    composite_cleanroom: CleanroomCompositeDecision | None
    first_action_principle: FirstActionPrinciple
    diagnostic_facts: DiagnosticFacts
    diagnostic_tokens: tuple[DiagnosticToken, ...]
    semantic_labels: NewowSemanticLabels
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SegmentReplay:
    frames: tuple[NewowTrendFrame, ...]
    final_state: NewowTrendD1EngineState


@dataclass(frozen=True, slots=True)
class _FrequencyReplay:
    frequency: BarFrequency
    visible_bars: tuple[NewowResearchBar, ...]
    channel_points: tuple[PriceChannelPoint, ...]
    owner_segment_ids: tuple[str, ...]
    trend_signal: TrendSignal
    page_signal: PageSignalState
    oscillation_status: OscillationStatus
    latest_segment_daily_bars: tuple[NewowDailyBar, ...]
    latest_segment_research_bars: tuple[NewowResearchBar, ...]
    latest_segment_trend_points: tuple[NewowTrendBandPoint, ...]
    latest_oscillation_state: OscillationState
    frames: tuple[NewowTrendFrame, ...] = ()
    final_engine_state: NewowTrendD1EngineState | None = None
    rollover_seams: tuple[NewowRolloverSeam, ...] = ()


class NewowTrendDetailService:
    """Stateless request-scoped actual-dominant multi-period replay."""

    def __init__(
        self,
        market_data: MarketDataService,
        *,
        taxonomy: Mapping[str, ProductTaxonomyEntry] | None = None,
    ) -> None:
        self._market_data = market_data
        self._taxonomy = taxonomy

    def query(self, query: NewowTrendDetailQuery) -> NewowTrendDetailResult:
        self._validate_query(query)
        try:
            loaded = ActualDominantResearchSegmentLoader(self._market_data).load(
                symbol=query.product,
                frequencies=(BarFrequency.D1, BarFrequency.W1, BarFrequency.H1),
                since=query.since,
                through=query.through,
            )
        except (
            ActualDominantResearchSegmentIdentityError,
            ActualDominantResearchSourceTradingDayMissingError,
        ) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID") from exc
        except (MarketDataError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_UNAVAILABLE") from exc

        actual = loaded.results[BarFrequency.D1].bars
        self._validate_canonical_order(actual, require_unique_trading_day=True)
        if (
            sum(query.since <= bar.trading_day <= query.through for bar in actual)
            > MAX_VISIBLE_TRADING_DAYS
        ):
            raise NewowTrendDetailError("NEWOW_RANGE_TOO_LARGE")
        calculation_identity = _calculation_identity(query.product)
        try:
            frequency_replays = {
                frequency: self._replay_frequency(
                    product=query.product,
                    frequency=frequency,
                    calculation_identity=calculation_identity,
                    actual=loaded.results[frequency].bars,
                    owner_segments=loaded.results[
                        frequency
                    ].resolved_contract_segments,
                    authoritative_segments=loaded.authoritative_segments,
                )
                for frequency in (
                    BarFrequency.D1,
                    BarFrequency.W1,
                    BarFrequency.H1,
                )
            }
        except NewowTrendDetailError:
            raise
        except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID") from exc
        daily = frequency_replays[BarFrequency.D1]
        weekly = frequency_replays[BarFrequency.W1]
        hourly = frequency_replays[BarFrequency.H1]

        frames = tuple(
            frame
            for frame in daily.frames
            if query.since <= frame.bar.trading_day <= query.through
        )
        if not frames:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        display = _display_prices(daily, weekly)
        trend = MultiPeriodTrendState(
            weekly.trend_signal,
            daily.trend_signal,
            hourly.trend_signal,
        )
        oscillation = MultiPeriodOscillationState(
            weekly.oscillation_status,
            daily.oscillation_status,
            hourly.oscillation_status,
        )
        composite_warning: tuple[str, ...] = ()
        try:
            composite_page = calculate_composite_decision(
                trend=trend,
                oscillation=oscillation,
                daily_bars=daily.latest_segment_research_bars,
            )
            composite_cleanroom = calculate_cleanroom_composite_decision(
                trend=trend,
                oscillation=oscillation,
                daily_bars=daily.latest_segment_research_bars,
            )
        except ValueError as exc:
            code = str(exc)
            if code == "NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT":
                composite_page = None
                composite_cleanroom = None
                composite_warning = (code,)
            elif code != "NEWOW_COMPOSITE_STATE_UNSUPPORTED":
                code = "NEWOW_DATA_IDENTITY_INVALID"
                raise NewowTrendDetailError(code) from exc
            else:
                raise NewowTrendDetailError(code) from exc
        try:
            first_action = calculate_first_action_principle(
                trend=WeeklyDailyTrendState(trend.weekly, trend.daily),
                oscillation=oscillation,
            )
            diagnostics = _diagnostics(
                daily=daily,
                weekly=weekly,
                display=display,
                current_frame=frames[-1],
            )
            page_comparison = rank_page_channel_windows(
                daily.latest_segment_research_bars
            )
        except ValueError as exc:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID") from exc
        taxonomy_entry = self._taxonomy.get(query.product) if self._taxonomy else None
        context = NewowInstrumentContext(
            query.product,
            taxonomy_entry.name if taxonomy_entry is not None else None,
            frames[-1].bar.physical_contract if frames else None,
            "1d",
            "actual_dominant",
            _PROFILE.profile_id,
            _formula_versions(),
        )
        return NewowTrendDetailResult(
            calculation_identity,
            None,  # No stable Catalog/MainContractMap revision digest is exposed; never fabricate one.
            ":".join(
                (
                    calculation_identity,
                    query.since.isoformat(),
                    query.through.isoformat(),
                )
            ),
            context,
            tuple(frame.bar for frame in frames),
            frames,
            tuple(marker for frame in frames for marker in frame.markers),
            _latest_overlays(frames),
            tuple(
                seam
                for seam in daily.rollover_seams
                if query.since <= seam.trading_day <= query.through
            ),
            NewowPriceChannelFacts(
                _channel_facts(daily, query.since, query.through),
                _channel_facts(weekly, query.since, query.through),
                _channel_facts(hourly, query.since, query.through),
                display,
            ),
            page_comparison,
            composite_page,
            composite_cleanroom,
            first_action,
            diagnostics,
            diagnostic_tokens(diagnostics),
            NewowSemanticLabels(),
            (
                *_warnings(
                    frames[-1] if frames else None,
                    daily.final_engine_state,
                ),
                *composite_warning,
            ),
        )

    @staticmethod
    def _validate_query(query: object) -> None:
        if not isinstance(query, NewowTrendDetailQuery):
            raise NewowTrendDetailError("NEWOW_INVALID_RANGE")
        if (
            not isinstance(query.product, str)
            or re.fullmatch(r"[a-z]+", query.product.strip()) is None
        ):
            raise NewowTrendDetailError("NEWOW_INVALID_PRODUCT")
        if (
            type(query.since) is not date
            or type(query.through) is not date
            or query.since > query.through
        ):
            raise NewowTrendDetailError("NEWOW_INVALID_RANGE")

    def _load_contract_prefix(
        self,
        product: str,
        frequency: BarFrequency,
        contract: str,
        through: datetime,
    ) -> tuple[CanonicalBar, ...]:
        try:
            page = self._market_data.query_page(
                SeriesPageQuery(
                    SeriesKind.CONTRACT,
                    product,
                    frequency,
                    through + timedelta(microseconds=1),
                    _PREFIX_LIMIT,
                    contract,
                )
            )
        except (MarketDataError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_UNAVAILABLE") from exc
        if page.has_more_before:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        self._validate_canonical_order(
            page.bars,
            require_unique_trading_day=frequency is not BarFrequency.H1,
        )
        if not page.bars:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        return page.bars

    def _replay_frequency(
        self,
        *,
        product: str,
        frequency: BarFrequency,
        calculation_identity: str,
        actual: tuple[CanonicalBar, ...],
        owner_segments: tuple[ResolvedContractSegment, ...],
        authoritative_segments: tuple[ResolvedContractSegment, ...],
    ) -> _FrequencyReplay:
        self._validate_canonical_order(
            actual,
            require_unique_trading_day=frequency is not BarFrequency.H1,
        )
        visible_bars: list[NewowResearchBar] = []
        visible_channels: list[PriceChannelPoint] = []
        owner_segment_ids: list[str] = []
        all_frames: list[NewowTrendFrame] = []
        seams: list[NewowRolloverSeam] = []
        previous_frame: NewowTrendFrame | None = None
        previous_segment: ResolvedContractSegment | None = None
        final_engine_state: NewowTrendD1EngineState | None = None
        latest_trend_signal = TrendSignal.IDLE
        latest_page_signal = PageSignalState.WAIT
        latest_oscillation_status = OscillationStatus.IDLE
        latest_daily_bars: tuple[NewowDailyBar, ...] = ()
        latest_research_bars: tuple[NewowResearchBar, ...] = ()
        latest_trend_points: tuple[NewowTrendBandPoint, ...] = ()
        latest_oscillation_state = OscillationState()

        for owner in owner_segments:
            rank_bars = tuple(
                bar
                for bar in actual
                if owner.start_trading_day
                <= bar.trading_day
                <= owner.end_trading_day
            )
            if not rank_bars:
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            segment = _authoritative_owner(
                owner, rank_bars, authoritative_segments
            )
            segment_id = _segment_id(segment)
            owner_segment_ids.append(segment_id)
            physical = self._load_contract_prefix(
                product,
                frequency,
                segment.contract,
                rank_bars[-1].bar_end,
            )
            expected = {
                (bar.trading_day, bar.bar_end): bar for bar in rank_bars
            }
            daily_bars: list[NewowDailyBar] = []
            research_bars: list[NewowResearchBar] = []
            matched = 0
            for bar in physical:
                ranked = expected.get((bar.trading_day, bar.bar_end))
                if ranked is not None and not _same_ohlcv(bar, ranked):
                    raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
                eligible = ranked is not None
                daily_bars.append(
                    _to_newow_bar(
                        product,
                        segment.contract,
                        segment_id,
                        calculation_identity,
                        bar,
                        eligible,
                    )
                )
                research_bars.append(
                    _to_research_bar(
                        product,
                        frequency,
                        segment.contract,
                        segment_id,
                        calculation_identity,
                        bar,
                        eligible,
                    )
                )
                matched += int(eligible)
            if matched != len(rank_bars):
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")

            frozen_daily = tuple(daily_bars)
            frozen_research = tuple(research_bars)
            channels = calculate_price_channel(frozen_research, window=10)
            trend_state = initial_trend_band_state()
            oscillation_state = OscillationState()
            trend_points: list[NewowTrendBandPoint] = []
            eligible_marker: NewowMainMarker | None = None
            eligible_point: NewowTrendBandPoint | None = None
            eligible_oscillation_state: OscillationState | None = None
            for daily_bar, channel in zip(
                frozen_daily, channels, strict=True
            ):
                trend_result = step_trend_band(
                    trend_state, daily_bar, profile=_PROFILE
                )
                trend_state = trend_result.state
                trend_points.append(trend_result.point)
                oscillation_result = step_oscillation(
                    oscillation_state, daily_bar
                )
                oscillation_state = oscillation_result.state
                if daily_bar.observation_eligible:
                    visible_bars.append(
                        frozen_research[len(trend_points) - 1]
                    )
                    visible_channels.append(channel)
                    eligible_marker = trend_result.marker
                    eligible_point = trend_result.point
                    eligible_oscillation_state = oscillation_state
            if eligible_point is None or eligible_oscillation_state is None:
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            latest_trend_signal = _trend_signal(
                eligible_point, eligible_marker, frequency=frequency
            )
            latest_page_signal = _page_signal(latest_trend_signal)
            latest_oscillation_status = _oscillation_status(
                eligible_oscillation_state
            )
            latest_daily_bars = frozen_daily
            latest_research_bars = frozen_research
            latest_trend_points = tuple(trend_points)
            latest_oscillation_state = eligible_oscillation_state

            if frequency is BarFrequency.D1:
                replay = self._replay_segment(
                    product,
                    segment,
                    calculation_identity,
                    physical,
                    rank_bars,
                )
                eligible_frames = tuple(
                    frame
                    for frame in replay.frames
                    if frame.bar.observation_eligible
                )
                if not eligible_frames:
                    raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
                if previous_frame is not None and previous_segment is not None:
                    seams.append(
                        NewowRolloverSeam(
                            eligible_frames[0].bar.trading_day,
                            previous_segment.contract,
                            segment.contract,
                            previous_frame.bar.bar_end,
                            eligible_frames[0].bar.bar_end,
                            previous_frame.bar.segment_id,
                            eligible_frames[0].bar.segment_id,
                        )
                    )
                previous_frame = eligible_frames[-1]
                previous_segment = segment
                all_frames.extend(eligible_frames)
                final_engine_state = replay.final_state

        if not visible_bars or not latest_research_bars:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        return _FrequencyReplay(
            frequency,
            tuple(visible_bars),
            tuple(visible_channels),
            tuple(owner_segment_ids),
            latest_trend_signal,
            latest_page_signal,
            latest_oscillation_status,
            latest_daily_bars,
            latest_research_bars,
            latest_trend_points,
            latest_oscillation_state,
            tuple(all_frames),
            final_engine_state,
            tuple(seams),
        )

    def _replay_segment(
        self,
        product: str,
        segment: ResolvedContractSegment,
        calculation_identity: str,
        physical: tuple[CanonicalBar, ...],
        rank_bars: tuple[CanonicalBar, ...],
    ) -> _SegmentReplay:
        expected: Mapping[tuple[date, datetime], CanonicalBar] = {
            (bar.trading_day, bar.bar_end): bar for bar in rank_bars
        }
        engine = NewowTrendD1Engine.initial(profile=_PROFILE)
        frames: list[NewowTrendFrame] = []
        matched = 0
        for bar in physical:
            ranked = expected.get((bar.trading_day, bar.bar_end))
            if ranked is not None and not _same_ohlcv(bar, ranked):
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            eligible = ranked is not None
            try:
                frames.append(
                    engine.step(
                        _to_newow_bar(
                            product,
                            segment.contract,
                            _segment_id(segment),
                            calculation_identity,
                            bar,
                            eligible,
                        )
                    ).frame
                )
            except (
                ArithmeticError,
                AttributeError,
                LookupError,
                TypeError,
                ValueError,
            ) as exc:
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID") from exc
            matched += int(eligible)
        if matched != len(rank_bars):
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        return _SegmentReplay(tuple(frames), engine.state)

    @staticmethod
    def _validate_canonical_order(
        bars: tuple[CanonicalBar, ...], *, require_unique_trading_day: bool
    ) -> None:
        if any(
            current.bar_end <= previous.bar_end
            or (
                require_unique_trading_day
                and current.trading_day <= previous.trading_day
            )
            or current.trading_day < previous.trading_day
            for previous, current in zip(bars, bars[1:], strict=False)
        ):
            raise NewowTrendDetailError("NEWOW_DATA_OUT_OF_ORDER")


def _to_newow_bar(
    product: str,
    contract: str,
    segment_id: str,
    calculation_identity: str,
    bar: CanonicalBar,
    eligible: bool,
) -> NewowDailyBar:
    if bar.volume != bar.volume.to_integral_value() or (
        bar.open_interest is not None
        and bar.open_interest != bar.open_interest.to_integral_value()
    ):
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return NewowDailyBar(
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
        calculation_identity,
        eligible,
        True,
    )


def _to_research_bar(
    product: str,
    frequency: BarFrequency,
    contract: str,
    segment_id: str,
    calculation_identity: str,
    bar: CanonicalBar,
    eligible: bool,
) -> NewowResearchBar:
    if bar.volume != bar.volume.to_integral_value() or (
        bar.open_interest is not None
        and bar.open_interest != bar.open_interest.to_integral_value()
    ):
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return NewowResearchBar(
        product=product,
        physical_contract=contract,
        segment_id=segment_id,
        trading_day=bar.trading_day,
        bar_end=bar.bar_end,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume),
        open_interest=(
            None if bar.open_interest is None else int(bar.open_interest)
        ),
        source_identity="|".join(
            (calculation_identity, frequency.value, bar.bar_end.isoformat())
        ),
        observation_eligible=eligible,
        completed=True,
        frequency=frequency.value,
    )


def _authoritative_owner(
    owner: ResolvedContractSegment,
    bars: tuple[CanonicalBar, ...],
    authoritative: tuple[ResolvedContractSegment, ...],
) -> ResolvedContractSegment:
    candidates = tuple(
        segment
        for segment in authoritative
        if segment.contract == owner.contract
        and segment.start_trading_day <= owner.start_trading_day
        and owner.end_trading_day <= segment.end_trading_day
        and all(
            segment.start_trading_day
            <= bar.trading_day
            <= segment.end_trading_day
            for bar in bars
        )
    )
    if len(candidates) != 1:
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return candidates[0]


def _trend_signal(
    point: NewowTrendBandPoint,
    marker: NewowMainMarker | None,
    *,
    frequency: BarFrequency,
) -> TrendSignal:
    if point.state is TrendBandState.UNAVAILABLE:
        return TrendSignal.IDLE
    if frequency is not BarFrequency.H1 and marker is not None:
        if marker.marker_type is NewowMarkerType.BUILD:
            return TrendSignal.BUY
        if marker.marker_type is NewowMarkerType.CLEAR:
            return TrendSignal.SELL
    return (
        TrendSignal.HOLD
        if point.state is TrendBandState.YELLOW
        else TrendSignal.WAIT
    )


def _page_signal(signal: TrendSignal) -> PageSignalState:
    return {
        TrendSignal.BUY: PageSignalState.BUY,
        TrendSignal.HOLD: PageSignalState.HOLD,
        TrendSignal.SELL: PageSignalState.SELL,
        TrendSignal.WAIT: PageSignalState.WAIT,
        TrendSignal.IDLE: PageSignalState.WAIT,
    }[signal]


def _oscillation_status(state: OscillationState) -> OscillationStatus:
    if state.history_count < 10:
        return OscillationStatus.IDLE
    return (
        OscillationStatus.HOLDING
        if state.holding
        else OscillationStatus.CLEARED
    )


def _channel_facts(
    replay: _FrequencyReplay,
    since: date,
    through: date,
) -> NewowFrequencyPriceChannel:
    selected = tuple(
        (bar, point)
        for bar, point in zip(
            replay.visible_bars, replay.channel_points, strict=True
        )
        if since <= bar.trading_day <= through
    )
    return NewowFrequencyPriceChannel(
        replay.frequency.value,
        tuple(point for _, point in selected),
        tuple(dict.fromkeys(bar.segment_id for bar, _ in selected)),
    )


def _display_prices(
    daily: _FrequencyReplay, weekly: _FrequencyReplay
) -> DisplayPriceSelection:
    latest_daily = daily.channel_points[-1]
    latest_weekly = weekly.channel_points[-1]
    current = daily.visible_bars[-1]
    previous_close = (
        daily.latest_segment_research_bars[-2].close
        if len(daily.latest_segment_research_bars) >= 2
        else None
    )
    return select_display_prices(
        MultiPeriodPriceFacts(
            target_daily=latest_daily.target,
            target_weekly=latest_weekly.target,
            absorb_daily=latest_daily.absorb,
            absorb_weekly=latest_weekly.absorb,
            signal_daily=daily.page_signal,
            signal_weekly=weekly.page_signal,
            cross_weekly_buy=weekly.page_signal is PageSignalState.BUY,
        ),
        view_period=DisplayPeriod.DAY,
        current_price=current.close,
        previous_close=previous_close,
    )


def _diagnostics(
    *,
    daily: _FrequencyReplay,
    weekly: _FrequencyReplay,
    display: DisplayPriceSelection,
    current_frame: NewowTrendFrame,
) -> DiagnosticFacts:
    bars = daily.latest_segment_daily_bars
    latest = bars[-1]
    main_force: MainForceControlResult | None = calculate_main_force_control(bars)
    main_rise_results = calculate_main_rise_series(bars)
    main_rise: MainRiseState | None = (
        main_rise_results[-1].state if main_rise_results else None
    )
    cup = current_frame.cup_handle

    def identity(formula_version: str) -> DiagnosticPrimitiveIdentity:
        return DiagnosticPrimitiveIdentity(
            latest.bar_end,
            latest.physical_contract,
            latest.segment_id,
            formula_version,
        )

    return build_diagnostic_facts(
        DiagnosticInputs(
            bars=bars,
            display_prices=display,
            trend_points=daily.latest_segment_trend_points,
            trend_formula_version=_PROFILE.trend_band_formula,
            oscillation_state=daily.latest_oscillation_state,
            oscillation_identity=identity(OSCILLATION_FORMULA_VERSION),
            main_force=main_force,
            main_force_identity=(
                identity(MAIN_FORCE_CONTROL_FORMULA_VERSION)
                if main_force is not None
                else None
            ),
            main_rise_state=main_rise,
            main_rise_identity=(
                identity(MAIN_RISE_PAGE_V1.band_formula)
                if main_rise is not None
                else None
            ),
            cup_overlay=cup,
            cup_identity=(
                identity(_PROFILE.cup_handle_formula) if cup is not None else None
            ),
            weekly_signal=weekly.page_signal,
            daily_signal=daily.page_signal,
        )
    )


def _formula_versions() -> tuple[str, ...]:
    return (
        _PROFILE.trend_band_formula,
        _PROFILE.escape_formula,
        _PROFILE.cup_handle_formula,
        OSCILLATION_FORMULA_VERSION,
        MAIN_FORCE_CONTROL_FORMULA_VERSION,
        MAIN_RISE_PAGE_V1.band_formula,
        TARGET_ABSORB_CHANNEL_PAGE_V1,
        TARGET_ABSORB_DISPLAY_PAGE_V2,
        CHANNEL_OPTIMIZER_PAGE_V1,
        CHANNEL_OPTIMIZER_CAUSAL_V1,
        COMPOSITE_DECISION_PAGE_V3282,
        COMPOSITE_DECISION_CLEANROOM_V1,
        FIRST_ACTION_PRINCIPLE_PAGE_V3263,
        DIAGNOSTIC_FACTS_CLEANROOM_V1,
        DIAGNOSTIC_RULES_CLEANROOM_V1,
    )


def _calculation_identity(product: str) -> str:
    """Identity binds stable Canonical/rank-1 authorities, never a request window."""
    return "|".join(
        (
            _CANONICAL_AUTHORITY,
            _RANK1_MAPPING_AUTHORITY,
            product,
            "actual_dominant",
            "1d+1w+60m",
            _PROFILE.profile_id,
            *_formula_versions(),
        )
    )


def _same_ohlcv(left: CanonicalBar, right: CanonicalBar) -> bool:
    return (
        left.open,
        left.high,
        left.low,
        left.close,
        left.volume,
        left.open_interest,
    ) == (
        right.open,
        right.high,
        right.low,
        right.close,
        right.volume,
        right.open_interest,
    )


def _segment_id(segment: ResolvedContractSegment) -> str:
    return f"{segment.contract}:{segment.start_trading_day.isoformat()}:{segment.end_trading_day.isoformat()}"


def _latest_overlays(
    frames: tuple[NewowTrendFrame, ...],
) -> tuple[NewowCupHandleOverlay, ...]:
    latest: dict[str, NewowCupHandleOverlay] = {}
    for frame in frames:
        if frame.cup_handle is not None:
            latest[frame.cup_handle.candidate_id] = frame.cup_handle
    return tuple(latest[key] for key in sorted(latest))


def _warnings(
    latest: NewowTrendFrame | None, state: NewowTrendD1EngineState | None
) -> tuple[str, ...]:
    """Top-level availability is the latest visible bar only, never history."""
    if latest is None or state is None:
        return (
            "NEWOW_TREND_WARMUP_INSUFFICIENT",
            "NEWOW_D123_WARMUP_INSUFFICIENT",
            "NEWOW_CUP_WARMUP_INSUFFICIENT",
        )
    warnings: list[str] = []
    if latest.trend_band.state is TrendBandState.UNAVAILABLE:
        warnings.append("NEWOW_TREND_WARMUP_INSUFFICIENT")
    if not escape_evaluation_ready(state.escape_state, profile=_PROFILE):
        warnings.append("NEWOW_D123_WARMUP_INSUFFICIENT")
    if not cup_evaluation_ready(state.cup_handle_state, profile=_PROFILE):
        warnings.append("NEWOW_CUP_WARMUP_INSUFFICIENT")
    return tuple(warnings)
