"""Read-only Historical Formal Signal replay for SuBing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.subing_calibration import SubingCalibration
from app.market_data.subing_research import (
    SubingDirection,
    SubingFactorResult,
    SubingSignalEvaluation,
    SubingSignalStatus,
    calculate_subing_factor_series,
    resolve_subing_matched_signal,
)


_SUPPORTED_FREQUENCIES = frozenset({BarFrequency.M5, BarFrequency.M15})


class SubingHistoricalSignalDirection(StrEnum):
    BUY = "buy"
    SELL = "sell"


class SubingHistoricalSignalSourceUnavailableError(RuntimeError):
    code = "SUBING_HISTORICAL_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingHistoricalSignalSegmentIdentityError(RuntimeError):
    code = "SUBING_HISTORICAL_SEGMENT_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class _ResearchSegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


@dataclass(frozen=True, slots=True)
class SubingHistoricalSignalRequest:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    since: date
    through: date

    def __post_init__(self) -> None:
        try:
            series_kind = SeriesKind(self.series_kind)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError):
            raise ValueError("unsupported SuBing Historical identity") from None
        symbol = self.symbol
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        symbol = symbol.strip().lower()
        if not symbol.isascii() or not symbol.isalpha():
            raise ValueError("symbol must contain ASCII letters only")
        if series_kind is not SeriesKind.ACTUAL_DOMINANT:
            raise ValueError("unsupported SuBing Historical series kind")
        if frequency not in _SUPPORTED_FREQUENCIES:
            raise ValueError("unsupported SuBing Historical frequency")
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("since must not be later than through")
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class SubingHistoricalSignalEvent:
    event_id: str
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    direction: SubingHistoricalSignalDirection
    trigger_timeframe: BarFrequency
    lower_tf_confirmation: bool


@dataclass(frozen=True, slots=True)
class SubingHistoricalSignalResult:
    request: SubingHistoricalSignalRequest
    events: tuple[SubingHistoricalSignalEvent, ...]


class SubingHistoricalSignalService:
    """Replay exact SuBing Formal Signals over confirmed rank-1 segments."""

    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        products: Sequence[str],
        calibration: SubingCalibration,
    ) -> None:
        normalized = tuple(
            dict.fromkeys(product.strip().lower() for product in products)
        )
        if not normalized or any(
            not product or not product.isascii() or not product.isalpha()
            for product in normalized
        ):
            raise ValueError("products must contain ASCII product symbols")
        self._segment_loader = segment_loader
        self._products = normalized
        self._calibration = calibration

    def history(
        self,
        request: SubingHistoricalSignalRequest,
    ) -> SubingHistoricalSignalResult:
        if not isinstance(request, SubingHistoricalSignalRequest):
            raise TypeError("request must be SubingHistoricalSignalRequest")
        if request.symbol not in self._products:
            raise ValueError("symbol is outside the active product scope")
        try:
            loaded = self._segment_loader.load(
                symbol=request.symbol,
                frequencies=(BarFrequency.M5, BarFrequency.M15),
                since=request.since,
                through=request.through,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise SubingHistoricalSignalSegmentIdentityError() from None
        except MarketDataError:
            raise SubingHistoricalSignalSourceUnavailableError() from None

        results = loaded.results
        if (
            results.get(BarFrequency.M5) is None
            or results.get(BarFrequency.M15) is None
            or not loaded.segments
        ):
            raise SubingHistoricalSignalSegmentIdentityError()
        bars_5m_by_segment = _partition_segment_bars(
            results[BarFrequency.M5].bars,
            segments=loaded.segments,
            through=request.through,
        )
        bars_15m_by_segment = _partition_segment_bars(
            results[BarFrequency.M15].bars,
            segments=loaded.segments,
            through=request.through,
        )
        events: list[SubingHistoricalSignalEvent] = []
        for segment, bars_5m, bars_15m in zip(
            loaded.segments,
            bars_5m_by_segment,
            bars_15m_by_segment,
            strict=True,
        ):
            if not bars_5m and not bars_15m:
                continue
            if not bars_5m or not bars_15m:
                raise SubingHistoricalSignalSegmentIdentityError()
            events.extend(
                self._segment_events(
                    request=request,
                    segment=segment,
                    bars_5m=bars_5m,
                    bars_15m=bars_15m,
                )
            )
        return SubingHistoricalSignalResult(
            request=request,
            events=tuple(sorted(events, key=lambda event: (event.bar_end, event.event_id))),
        )

    def _segment_events(
        self,
        *,
        request: SubingHistoricalSignalRequest,
        segment: ResolvedContractSegment,
        bars_5m: tuple[CanonicalBar, ...],
        bars_15m: tuple[CanonicalBar, ...],
    ) -> tuple[SubingHistoricalSignalEvent, ...]:
        factors_5m = calculate_subing_factor_series(
            bars_5m,
            timeframe=BarFrequency.M5,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            latest_bar_source="canonical",
        )
        factors_15m = calculate_subing_factor_series(
            bars_15m,
            timeframe=BarFrequency.M15,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            latest_bar_source="canonical",
        )
        if len(factors_5m) != len(bars_5m) or len(factors_15m) != len(bars_15m):
            raise SubingHistoricalSignalSegmentIdentityError()

        factor_5m_by_end = dict(zip((bar.bar_end for bar in bars_5m), factors_5m, strict=True))
        factor_15m_by_end = dict(zip((bar.bar_end for bar in bars_15m), factors_15m, strict=True))
        bar_15m_by_end = {bar.bar_end: bar for bar in bars_15m}
        if len(factor_5m_by_end) != len(bars_5m) or len(factor_15m_by_end) != len(bars_15m):
            raise SubingHistoricalSignalSegmentIdentityError()
        if any(boundary not in factor_5m_by_end for boundary in factor_15m_by_end):
            raise SubingHistoricalSignalSegmentIdentityError()

        events: list[SubingHistoricalSignalEvent] = []
        latest_15m: SubingFactorResult | None = None
        next_15m = 0
        for bar_5m, factor_5m in zip(bars_5m, factors_5m, strict=True):
            while (
                next_15m < len(bars_15m)
                and bars_15m[next_15m].bar_end <= bar_5m.bar_end
            ):
                latest_15m = factors_15m[next_15m]
                next_15m += 1
            if bar_5m.bar_end in factor_15m_by_end:
                primary = factor_15m_by_end[bar_5m.bar_end]
                companion: SubingFactorResult | None = factor_5m
                evidence_bar = bar_15m_by_end[bar_5m.bar_end]
            else:
                primary = factor_5m
                companion = latest_15m
                evidence_bar = bar_5m
            resolved = resolve_subing_matched_signal(
                primary,
                companion,
                calibration=self._calibration,
            )
            event = _resolved_event(
                request=request,
                segment=segment,
                evidence_bar=evidence_bar,
                resolved=resolved,
            )
            if event is not None:
                events.append(event)
        return tuple(events)


def _partition_segment_bars(
    bars: Sequence[CanonicalBar],
    *,
    segments: Sequence[ResolvedContractSegment],
    through: date,
) -> tuple[tuple[CanonicalBar, ...], ...]:
    grouped: list[list[CanonicalBar]] = [[] for _ in segments]
    for bar in bars:
        if bar.trading_day > through:
            continue
        matches = [
            index
            for index, segment in enumerate(segments)
            if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
        ]
        if len(matches) != 1:
            raise SubingHistoricalSignalSegmentIdentityError()
        grouped[matches[0]].append(bar)
    return tuple(
        tuple(sorted(segment_bars, key=lambda bar: bar.bar_end))
        for segment_bars in grouped
    )


def _resolved_event(
    *,
    request: SubingHistoricalSignalRequest,
    segment: ResolvedContractSegment,
    evidence_bar: CanonicalBar,
    resolved: SubingSignalEvaluation | None,
) -> SubingHistoricalSignalEvent | None:
    if resolved is None or resolved.status is not SubingSignalStatus.MATCHED:
        return None
    trigger_timeframe = resolved.trigger_timeframe
    direction = resolved.direction
    bar_end = resolved.bar_end
    if (
        trigger_timeframe not in _SUPPORTED_FREQUENCIES
        or bar_end != evidence_bar.bar_end
        or direction not in {SubingDirection.LONG, SubingDirection.SHORT}
    ):
        raise SubingHistoricalSignalSegmentIdentityError()
    if trigger_timeframe is not request.frequency:
        return None
    if not request.since <= evidence_bar.trading_day <= request.through:
        return None
    projected_direction = (
        SubingHistoricalSignalDirection.BUY
        if direction is SubingDirection.LONG
        else SubingHistoricalSignalDirection.SELL
    )
    event_id = "|".join(
        (
            "subing_historical_signal_v1",
            request.symbol,
            segment.contract,
            segment.start_trading_day.isoformat(),
            evidence_bar.bar_end.isoformat(),
            trigger_timeframe.value,
            projected_direction.value,
        )
    )
    return SubingHistoricalSignalEvent(
        event_id=event_id,
        bar_end=evidence_bar.bar_end,
        trading_day=evidence_bar.trading_day,
        contract=segment.contract,
        segment_start_trading_day=segment.start_trading_day,
        direction=projected_direction,
        trigger_timeframe=trigger_timeframe,
        lower_tf_confirmation=resolved.lower_tf_confirmation,
    )
