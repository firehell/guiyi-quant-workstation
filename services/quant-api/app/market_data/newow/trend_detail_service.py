from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from guiyi_quant.newow.engine import NewowTrendD1Engine
from guiyi_quant.newow.models import (
    NewowCupHandleOverlay,
    NewowDailyBar,
    NewowMainMarker,
    NewowTrendFrame,
    TrendBandState,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSegmentLoader,
    ActualDominantResearchSourceTradingDayMissingError,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService

from .trend_detail_query import MAX_VISIBLE_TRADING_DAYS, NewowTrendDetailQuery


class NewowTrendDetailError(ValueError):
    """Bounded public Newow read-model failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NewowInstrumentContext:
    product: str
    frequency: str
    series_kind: str
    profile_id: str
    formula_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NewowRolloverSeam:
    previous_contract: str
    next_contract: str
    previous_bar_end: object
    next_bar_end: object
    previous_segment_id: str
    next_segment_id: str


@dataclass(frozen=True, slots=True)
class NewowTrendDetailResult:
    source_identity: str
    instrument: NewowInstrumentContext
    visible_range: tuple[date, date]
    bars: tuple[NewowDailyBar, ...]
    frames: tuple[NewowTrendFrame, ...]
    markers: tuple[NewowMainMarker, ...]
    cup_overlays: tuple[NewowCupHandleOverlay, ...]
    seams: tuple[NewowRolloverSeam, ...]
    warnings: tuple[str, ...]


class NewowTrendDetailService:
    """Request-scoped actual-dominant D1 replay with no storage bypasses."""

    def __init__(self, market_data: MarketDataService) -> None:
        self._market_data = market_data

    def query(self, query: NewowTrendDetailQuery) -> NewowTrendDetailResult:
        self._validate_query(query)
        try:
            loaded = ActualDominantResearchSegmentLoader(self._market_data).load(
                symbol=query.product,
                frequencies=(BarFrequency.D1,),
                since=query.since,
                through=query.through,
            )
        except (ActualDominantResearchSegmentIdentityError, ActualDominantResearchSourceTradingDayMissingError) as exc:
            raise NewowTrendDetailError("NEWOW_DETAIL_IDENTITY_INVALID") from exc
        except (MarketDataError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DETAIL_DATA_UNAVAILABLE") from exc

        actual = loaded.results[BarFrequency.D1].bars
        self._validate_canonical_order(actual)
        all_frames: list[NewowTrendFrame] = []
        all_seams: list[NewowRolloverSeam] = []
        previous: tuple[NewowDailyBar, ResolvedContractSegment] | None = None

        for segment in loaded.segments:
            rank_bars = tuple(
                bar
                for bar in actual
                if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
            )
            if not rank_bars:
                raise NewowTrendDetailError("NEWOW_DETAIL_IDENTITY_INVALID")
            physical = self._load_contract_prefix(query.product, segment, rank_bars[-1].trading_day)
            frames = self._replay_segment(query.product, segment, physical, rank_bars)
            eligible = tuple(frame for frame in frames if frame.bar.observation_eligible)
            if not eligible:
                raise NewowTrendDetailError("NEWOW_DETAIL_IDENTITY_INVALID")
            if previous is not None:
                previous_bar, previous_segment = previous
                all_seams.append(
                    NewowRolloverSeam(
                        previous_segment.contract,
                        segment.contract,
                        previous_bar.bar_end,
                        eligible[0].bar.bar_end,
                        previous_bar.segment_id,
                        eligible[0].bar.segment_id,
                    )
                )
            previous = (eligible[-1].bar, segment)
            all_frames.extend(eligible)

        visible_frames = tuple(
            frame
            for frame in all_frames
            if query.since <= frame.bar.trading_day <= query.through
        )
        visible_bars = tuple(frame.bar for frame in visible_frames)
        markers = tuple(marker for frame in visible_frames for marker in frame.markers)
        overlays = _latest_overlays(visible_frames)
        warnings = _warnings(visible_frames)
        context = NewowInstrumentContext(
            query.product,
            "1d",
            "actual_dominant",
            NEWOW_TREND_D1_V1.profile_id,
            (
                NEWOW_TREND_D1_V1.trend_band_formula,
                NEWOW_TREND_D1_V1.escape_formula,
                NEWOW_TREND_D1_V1.cup_handle_formula,
            ),
        )
        return NewowTrendDetailResult(
            ":".join(("actual_dominant", query.product, query.since.isoformat(), query.through.isoformat())),
            context,
            (query.since, query.through),
            visible_bars,
            visible_frames,
            markers,
            overlays,
            tuple(all_seams),
            warnings,
        )

    @staticmethod
    def _validate_query(query: object) -> None:
        if not isinstance(query, NewowTrendDetailQuery):
            raise NewowTrendDetailError("NEWOW_DETAIL_QUERY_INVALID")
        if (
            not isinstance(query.product, str)
            or not query.product.strip().islower()
            or not query.product.strip().isalpha()
            or type(query.since) is not date
            or type(query.through) is not date
            or query.since > query.through
        ):
            raise NewowTrendDetailError("NEWOW_DETAIL_QUERY_INVALID")
        if (query.through - query.since).days + 1 > MAX_VISIBLE_TRADING_DAYS:
            raise NewowTrendDetailError("NEWOW_DETAIL_VISIBLE_RANGE_EXCEEDED")

    def _load_contract_prefix(
        self,
        product: str,
        segment: ResolvedContractSegment,
        through: date,
    ) -> tuple[CanonicalBar, ...]:
        try:
            result = self._market_data.query_contract_trading_days(
                ContractTradingDayQuery(product, segment.contract, BarFrequency.D1, date(2000, 1, 1), through)
            )
        except (MarketDataError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DETAIL_DATA_UNAVAILABLE") from exc
        self._validate_canonical_order(result.bars)
        if not result.bars:
            raise NewowTrendDetailError("NEWOW_DETAIL_IDENTITY_INVALID")
        return result.bars

    def _replay_segment(
        self,
        product: str,
        segment: ResolvedContractSegment,
        physical: tuple[CanonicalBar, ...],
        rank_bars: tuple[CanonicalBar, ...],
    ) -> tuple[NewowTrendFrame, ...]:
        expected: Mapping[tuple[date, object], CanonicalBar] = {
            (bar.trading_day, bar.bar_end): bar for bar in rank_bars
        }
        segment_id = _segment_id(segment)
        engine = NewowTrendD1Engine.initial()
        frames: list[NewowTrendFrame] = []
        matched = 0
        for bar in physical:
            key = (bar.trading_day, bar.bar_end)
            ranked = expected.get(key)
            eligible = ranked is not None
            if eligible and not _same_ohlcv(bar, ranked):
                raise NewowTrendDetailError("NEWOW_DETAIL_IDENTITY_INVALID")
            frame = engine.step(
                _to_newow_bar(product, segment.contract, segment_id, bar, eligible)
            ).frame
            frames.append(frame)
            matched += int(eligible)
        if matched != len(rank_bars):
            raise NewowTrendDetailError("NEWOW_DETAIL_IDENTITY_INVALID")
        return tuple(frames)

    @staticmethod
    def _validate_canonical_order(bars: tuple[CanonicalBar, ...]) -> None:
        for previous, current in zip(bars, bars[1:], strict=False):
            if current.bar_end == previous.bar_end or current.trading_day == previous.trading_day:
                raise NewowTrendDetailError("NEWOW_DETAIL_DUPLICATE_BAR")
            if current.bar_end < previous.bar_end or current.trading_day < previous.trading_day:
                raise NewowTrendDetailError("NEWOW_DETAIL_OUT_OF_ORDER_BAR")


def _to_newow_bar(
    product: str,
    contract: str,
    segment_id: str,
    bar: CanonicalBar,
    eligible: bool,
) -> NewowDailyBar:
    if bar.volume != bar.volume.to_integral_value() or (
        bar.open_interest is not None and bar.open_interest != bar.open_interest.to_integral_value()
    ):
        raise NewowTrendDetailError("NEWOW_DETAIL_CANONICAL_INVALID")
    return NewowDailyBar(
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
        open_interest=None if bar.open_interest is None else int(bar.open_interest),
        source_identity=f"canonical:{contract}:{bar.bar_end.isoformat()}",
        observation_eligible=eligible,
        completed=True,
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


def _latest_overlays(frames: tuple[NewowTrendFrame, ...]) -> tuple[NewowCupHandleOverlay, ...]:
    latest: dict[str, NewowCupHandleOverlay] = {}
    for frame in frames:
        if frame.cup_handle is not None:
            latest[frame.cup_handle.candidate_id] = frame.cup_handle
    return tuple(latest[key] for key in sorted(latest))


def _warnings(frames: tuple[NewowTrendFrame, ...]) -> tuple[str, ...]:
    codes = {
        "NEWOW_WARMUP_INCOMPLETE"
        for frame in frames
        if frame.trend_band.state is TrendBandState.UNAVAILABLE
    }
    return tuple(sorted(codes))
