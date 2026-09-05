from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Protocol

from .aggregation import SessionWindow
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

    def actual_dominant_segments(
        self,
        symbol: str,
        since: date,
        through: date,
    ) -> tuple[ResolvedContractSegment, ...]: ...

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
    ) -> tuple[SessionWindow, ...]: ...


class ActualDominantResearchSegmentIdentityError(ValueError):
    """Typed shared-loader boundary for invalid rank-1 segment identity."""


class ActualDominantResearchSourceTradingDayMissingError(ValueError):
    """Typed shared-loader boundary for an absent exact source-day Bar."""


@dataclass(frozen=True, slots=True)
class ActualDominantResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesResult]
    authoritative_segments: tuple[ResolvedContractSegment, ...]


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
        allow_empty_frequencies: Sequence[BarFrequency] = (),
    ) -> ActualDominantResearchSeries:
        requested_frequencies = tuple(frequencies)
        if not requested_frequencies:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        if len(set(requested_frequencies)) != len(requested_frequencies):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 frequency identity is duplicated"
            )
        allowed_empty = frozenset(allow_empty_frequencies)
        if not allowed_empty <= {BarFrequency.W1} or not allowed_empty <= set(
            requested_frequencies
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 empty-frequency identity is invalid"
            )

        authoritative_segments = self._market_data.actual_dominant_segments(
            symbol,
            since,
            through,
        )
        if not authoritative_segments:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        self._validate_authoritative_segments(
            authoritative_segments,
            since=since,
            through=through,
        )

        full = {
            frequency: self._query_actual_dominant_trading_days(
                ActualDominantTradingDayQuery(
                    symbol,
                    frequency,
                    authoritative_segments[0].start_trading_day,
                    through,
                )
            )
            for frequency in requested_frequencies
        }
        for frequency, result in full.items():
            self._validate_frequency_owner_subset(
                result,
                frequency=frequency,
                authoritative_segments=authoritative_segments,
                allow_empty=frequency in allowed_empty,
            )
        return ActualDominantResearchSeries(
            MappingProxyType(full),
            authoritative_segments,
        )

    def sessions(
        self,
        *,
        symbol: str,
        trading_days: Sequence[date],
    ) -> Mapping[date, tuple[SessionWindow, ...]]:
        days = tuple(trading_days)
        if (
            not days
            or len(set(days)) != len(days)
            or any(type(day) is not date for day in days)
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 TradingSession identity is missing or inconsistent"
            )
        windows = {
            day: self._market_data.session_windows(
                symbol=symbol,
                trading_day=day,
            )
            for day in days
        }
        if any(not value for value in windows.values()):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 TradingSession identity is missing or inconsistent"
            )
        return MappingProxyType(windows)

    def _query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        return self._market_data.query_actual_dominant_trading_days(request)

    @classmethod
    def _validate_frequency_owner_subset(
        cls,
        result: MarketSeriesResult,
        *,
        frequency: BarFrequency,
        authoritative_segments: tuple[ResolvedContractSegment, ...],
        allow_empty: bool,
    ) -> None:
        bars = result.bars
        raw_segments = result.resolved_contract_segments
        if not bars:
            if allow_empty and not raw_segments:
                return
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        if not raw_segments:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )
        for previous, current in zip(raw_segments, raw_segments[1:], strict=False):
            if current.start_trading_day > previous.end_trading_day:
                continue
            message = (
                "rank1 segment summaries overlap"
                if current.end_trading_day < previous.start_trading_day
                else "rank1 segments overlap"
            )
            raise ActualDominantResearchSegmentIdentityError(message)
        cls._validate_segment_coverage(
            {frequency: bars},
            raw_segments,
        )
        for raw_segment in raw_segments:
            raw_bars = tuple(
                bar
                for bar in bars
                if raw_segment.start_trading_day
                <= bar.trading_day
                <= raw_segment.end_trading_day
            )
            if not raw_bars:
                raise ActualDominantResearchSegmentIdentityError(
                    "rank1 segment identity conflicts with containing summary"
                )
        cls._validate_segment_coverage(
            {frequency: bars},
            authoritative_segments,
        )
        for bar in bars:
            raw_owner = next(
                segment
                for segment in raw_segments
                if segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
            authoritative_owner = next(
                segment
                for segment in authoritative_segments
                if segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
            if raw_owner.contract != authoritative_owner.contract:
                raise ActualDominantResearchSegmentIdentityError(
                    "rank1 segment identity conflicts with containing summary"
                )

    @staticmethod
    def _validate_authoritative_segments(
        segments: tuple[ResolvedContractSegment, ...],
        *,
        since: date,
        through: date,
    ) -> None:
        if (
            any(
                not segment.contract
                or type(segment.start_trading_day) is not date
                or type(segment.end_trading_day) is not date
                or segment.start_trading_day > segment.end_trading_day
                or segment.end_trading_day < since
                or segment.start_trading_day > through
                for segment in segments
            )
            or any(
                current.start_trading_day <= previous.end_trading_day
                or current.contract == previous.contract
                for previous, current in zip(segments, segments[1:], strict=False)
            )
        ):
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 segment identity is missing or inconsistent"
            )

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
