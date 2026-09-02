from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

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
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import MarketDataError, MarketDataService

from .trend_detail_query import MAX_VISIBLE_TRADING_DAYS, NewowTrendDetailQuery

_PREFIX_LIMIT = 2000
_CANONICAL_AUTHORITY = "market_data_service:canonical_v2"


class NewowTrendDetailError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NewowInstrumentContext:
    product: str
    display_name: str | None
    latest_physical_contract: str | None
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
class NewowTrendDetailResult:
    calculation_identity: str
    request_identity: str
    instrument: NewowInstrumentContext
    bars: tuple[NewowDailyBar, ...]
    frames: tuple[NewowTrendFrame, ...]
    markers: tuple[NewowMainMarker, ...]
    cup_handles: tuple[NewowCupHandleOverlay, ...]
    rollover_seams: tuple[NewowRolloverSeam, ...]
    warnings: tuple[str, ...]


class NewowTrendDetailService:
    """Stateless request-scoped actual-dominant D1 replay."""

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
        except (
            ActualDominantResearchSegmentIdentityError,
            ActualDominantResearchSourceTradingDayMissingError,
        ) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID") from exc
        except (MarketDataError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_UNAVAILABLE") from exc

        actual = loaded.results[BarFrequency.D1].bars
        self._validate_canonical_order(actual)
        if (
            sum(query.since <= bar.trading_day <= query.through for bar in actual)
            > MAX_VISIBLE_TRADING_DAYS
        ):
            raise NewowTrendDetailError("NEWOW_RANGE_TOO_LARGE")
        calculation_identity = _calculation_identity(query.product, loaded.segments)
        all_frames: list[NewowTrendFrame] = []
        all_seams: list[NewowRolloverSeam] = []
        previous: tuple[NewowDailyBar, ResolvedContractSegment] | None = None
        for segment in loaded.segments:
            rank_bars = tuple(
                bar
                for bar in actual
                if segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
            if not rank_bars:
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            frames = self._replay_segment(
                query.product,
                segment,
                calculation_identity,
                self._load_contract_prefix(
                    query.product, segment.contract, rank_bars[-1].bar_end
                ),
                rank_bars,
            )
            eligible = tuple(
                frame for frame in frames if frame.bar.observation_eligible
            )
            if not eligible:
                raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            if previous is not None:
                previous_bar, previous_segment = previous
                all_seams.append(
                    NewowRolloverSeam(
                        eligible[0].bar.trading_day,
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

        frames = tuple(
            frame
            for frame in all_frames
            if query.since <= frame.bar.trading_day <= query.through
        )
        context = NewowInstrumentContext(
            query.product,
            None,
            None,
            "1d",
            "actual_dominant",
            NEWOW_TREND_D1_V1.profile_id,
            _formula_versions(),
        )
        return NewowTrendDetailResult(
            calculation_identity,
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
                for seam in all_seams
                if query.since <= seam.trading_day <= query.through
            ),
            _warnings(frames),
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
        self, product: str, contract: str, through: datetime
    ) -> tuple[CanonicalBar, ...]:
        try:
            page = self._market_data.query_page(
                SeriesPageQuery(
                    SeriesKind.CONTRACT,
                    product,
                    BarFrequency.D1,
                    through + timedelta(microseconds=1),
                    _PREFIX_LIMIT,
                    contract,
                )
            )
        except (MarketDataError, ValueError) as exc:
            raise NewowTrendDetailError("NEWOW_DATA_UNAVAILABLE") from exc
        if page.has_more_before:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        self._validate_canonical_order(page.bars)
        if not page.bars:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        return page.bars

    def _replay_segment(
        self,
        product: str,
        segment: ResolvedContractSegment,
        calculation_identity: str,
        physical: tuple[CanonicalBar, ...],
        rank_bars: tuple[CanonicalBar, ...],
    ) -> tuple[NewowTrendFrame, ...]:
        expected: Mapping[tuple[date, datetime], CanonicalBar] = {
            (bar.trading_day, bar.bar_end): bar for bar in rank_bars
        }
        engine = NewowTrendD1Engine.initial()
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
        return tuple(frames)

    @staticmethod
    def _validate_canonical_order(bars: tuple[CanonicalBar, ...]) -> None:
        if any(
            current.bar_end <= previous.bar_end
            or current.trading_day <= previous.trading_day
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


def _formula_versions() -> tuple[str, ...]:
    return (
        NEWOW_TREND_D1_V1.trend_band_formula,
        NEWOW_TREND_D1_V1.escape_formula,
        NEWOW_TREND_D1_V1.cup_handle_formula,
    )


def _calculation_identity(
    product: str, segments: tuple[ResolvedContractSegment, ...]
) -> str:
    mapping = ",".join(
        f"{segment.contract}@{segment.start_trading_day.isoformat()}-{segment.end_trading_day.isoformat()}"
        for segment in segments
    )
    return "|".join(
        (
            _CANONICAL_AUTHORITY,
            product,
            "actual_dominant",
            "1d",
            NEWOW_TREND_D1_V1.profile_id,
            *_formula_versions(),
            mapping,
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


def _warnings(frames: tuple[NewowTrendFrame, ...]) -> tuple[str, ...]:
    if not any(
        frame.trend_band.state is TrendBandState.UNAVAILABLE for frame in frames
    ):
        return ()
    return (
        "NEWOW_CUP_WARMUP_INSUFFICIENT",
        "NEWOW_D123_WARMUP_INSUFFICIENT",
        "NEWOW_TREND_WARMUP_INSUFFICIENT",
    )
