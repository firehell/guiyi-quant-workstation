from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Protocol

from .domain import (
    ActualDominantRecentBarsQuery,
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from .market_data_service import ActualDominantSourceTradingDayMissingError


class _DominantSegmentSummary(Protocol):
    @property
    def symbol(self) -> str: ...

    @property
    def contract(self) -> str: ...

    @property
    def start_trading_day(self) -> date: ...

    @property
    def end_trading_day(self) -> date: ...


class ActualDominantResearchReader(Protocol):
    def query_actual_dominant_recent_bars(
        self,
        request: ActualDominantRecentBarsQuery,
    ) -> MarketSeriesPageResult: ...

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult: ...

    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> _DominantSegmentSummary: ...


class ActualDominantResearchSegmentIdentityError(ValueError):
    """Typed shared-loader boundary for invalid rank-1 segment identity."""


class ActualDominantResearchSourceTradingDayMissingError(ValueError):
    """Typed shared-loader boundary for an absent exact source-day Bar."""


@dataclass(frozen=True, slots=True)
class ActualDominantResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesResult]
    segments: tuple[ResolvedContractSegment, ...]


@dataclass(frozen=True, slots=True)
class ActualDominantStitchedResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesPageResult]
    current_segment: ResolvedContractSegment


class ActualDominantStitchedResearchLoader:
    def __init__(self, market_data: ActualDominantResearchReader) -> None:
        self._market_data = market_data

    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        through: date,
        limit: int = 30,
    ) -> ActualDominantStitchedResearchSeries:
        requested = tuple(frequencies)
        if not requested:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 stitched identity is missing or inconsistent"
            )
        try:
            results = {
                frequency: self._market_data.query_actual_dominant_recent_bars(
                    ActualDominantRecentBarsQuery(symbol, frequency, through, limit)
                )
                for frequency in requested
            }
        except ActualDominantSourceTradingDayMissingError as exc:
            raise ActualDominantResearchSourceTradingDayMissingError from exc
        summary = self._market_data.dominant_segment_for_day(symbol, through)
        if summary.symbol != symbol:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 stitched identity is missing or inconsistent"
            )
        current_segment = ResolvedContractSegment(
            summary.contract,
            summary.start_trading_day,
            summary.end_trading_day,
        )
        _validate_stitched_current_identity(
            symbol=symbol,
            through=through,
            results=results,
            current_segment=current_segment,
        )
        return ActualDominantStitchedResearchSeries(
            MappingProxyType(results),
            current_segment,
        )


class ActualDominantResearchSegmentLoader:
    def __init__(
        self,
        market_data: ActualDominantResearchReader,
    ) -> None:
        self._market_data = market_data

    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries:
        requested_frequencies = tuple(frequencies)
        if not requested_frequencies:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )

        probe = {
            frequency: self._query_actual_dominant_trading_days(
                ActualDominantTradingDayQuery(
                    symbol,
                    frequency,
                    since,
                    through,
                )
            )
            for frequency in requested_frequencies
        }
        probe_segments = {
            frequency: self._restore_true_segments(
                symbol,
                probe[frequency],
                frequency=frequency,
                since=since,
                through=through,
            )
            for frequency in requested_frequencies
        }
        segments = probe_segments[requested_frequencies[0]]
        if not segments or any(
            probe_segments[frequency] != segments
            for frequency in requested_frequencies[1:]
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )

        full = {
            frequency: self._query_actual_dominant_trading_days(
                ActualDominantTradingDayQuery(
                    symbol,
                    frequency,
                    segments[0].start_trading_day,
                    through,
                )
            )
            for frequency in requested_frequencies
        }
        full_segments = {
            frequency: self._restore_true_segments(
                symbol,
                full[frequency],
                frequency=frequency,
                since=segments[0].start_trading_day,
                through=through,
            )
            for frequency in requested_frequencies
        }
        if any(
            full_segments[frequency] != segments
            for frequency in requested_frequencies
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 probe/full segment identity is inconsistent"
            )
        return ActualDominantResearchSeries(MappingProxyType(full), segments)

    def _query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        return self._market_data.query_actual_dominant_trading_days(request)

    def _dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> _DominantSegmentSummary:
        return self._market_data.dominant_segment_for_day(symbol, trading_day)

    def _restore_true_segments(
        self,
        symbol: str,
        result: MarketSeriesResult,
        *,
        frequency: BarFrequency,
        since: date,
        through: date,
    ) -> tuple[ResolvedContractSegment, ...]:
        bars = tuple(
            bar for bar in result.bars if since <= bar.trading_day <= through
        )
        raw_segments = result.resolved_contract_segments
        if not bars or not raw_segments:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        self._validate_segment_coverage(
            {frequency: bars},
            raw_segments,
        )

        restored: list[ResolvedContractSegment] = []
        for raw_segment in raw_segments:
            segment_days = tuple(
                bar.trading_day
                for bar in bars
                if raw_segment.start_trading_day
                <= bar.trading_day
                <= raw_segment.end_trading_day
            )
            if not segment_days:
                continue
            representative = segment_days[0]
            summary = self._dominant_segment_for_day(
                symbol,
                representative,
            )
            if (
                summary.symbol != symbol
                or summary.contract != raw_segment.contract
                or any(
                    not (
                        summary.start_trading_day
                        <= segment_day
                        <= summary.end_trading_day
                    )
                    for segment_day in segment_days
                )
                or not (
                    summary.start_trading_day
                    <= representative
                    <= summary.end_trading_day
                )
            ):
                raise ActualDominantResearchSegmentIdentityError(
                    "rank1 segment identity conflicts with containing summary"
                )
            try:
                segment = ResolvedContractSegment(
                    summary.contract,
                    summary.start_trading_day,
                    summary.end_trading_day,
                )
            except (TypeError, ValueError):
                raise ActualDominantResearchSegmentIdentityError(
                    "rank1 segment identity conflicts with containing summary"
                ) from None
            if restored and segment == restored[-1]:
                continue
            if restored and segment.start_trading_day <= restored[-1].end_trading_day:
                raise ActualDominantResearchSegmentIdentityError(
                    "rank1 segment summaries overlap"
                )
            restored.append(segment)
        if not restored:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        self._validate_segment_coverage(
            {frequency: bars},
            tuple(restored),
        )
        return tuple(restored)

    @staticmethod
    def _validate_segment_coverage(
        requested: Mapping[BarFrequency, tuple[CanonicalBar, ...]],
        segments: tuple[ResolvedContractSegment, ...],
    ) -> None:
        for frequency, bars in requested.items():
            covered: set[tuple[datetime, date]] = set()
            for segment in segments:
                for bar in bars:
                    if (
                        segment.start_trading_day
                        <= bar.trading_day
                        <= segment.end_trading_day
                    ):
                        identity = (bar.bar_end, bar.trading_day)
                        if identity in covered:
                            raise ActualDominantResearchSegmentIdentityError(
                                "rank1 segments overlap"
                            )
                        covered.add(identity)
            if len(covered) != len(bars):
                raise ActualDominantResearchSegmentIdentityError(
                    f"rank1 segment identity is incomplete for {frequency.value}"
                )


def _validate_stitched_current_identity(
    *,
    symbol: str,
    through: date,
    results: Mapping[BarFrequency, MarketSeriesPageResult],
    current_segment: ResolvedContractSegment,
) -> None:
    if (
        not symbol
        or not (
            current_segment.start_trading_day
            <= through
            <= current_segment.end_trading_day
        )
    ):
        raise ActualDominantResearchSegmentIdentityError(
            "rank1 stitched identity is missing or inconsistent"
        )

    for result in results.values():
        if not result.bars:
            raise ActualDominantResearchSourceTradingDayMissingError
        if any(bar.trading_day > through for bar in result.bars) or any(
            current.bar_end <= previous.bar_end
            for previous, current in zip(
                result.bars,
                result.bars[1:],
                strict=False,
            )
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 stitched identity is missing or inconsistent"
            )
        if result.bars[-1].trading_day < through:
            raise ActualDominantResearchSourceTradingDayMissingError
        if result.bars[-1].trading_day != through:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 stitched identity is missing or inconsistent"
            )
        latest_day = result.bars[-1].trading_day
        latest_owners = tuple(
            segment.contract
            for segment in result.resolved_contract_segments
            if segment.start_trading_day
            <= latest_day
            <= segment.end_trading_day
        )
        if latest_owners != (current_segment.contract,):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 stitched identity is missing or inconsistent"
            )
