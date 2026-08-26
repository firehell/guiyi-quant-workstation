from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from types import MappingProxyType

from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyDirectionContext,
)


class FakeSegmentLoader:
    def __init__(
        self,
        result: ActualDominantResearchSeries | Exception,
    ) -> None:
        self.result = result
        self.requests: list[
            tuple[str, tuple[BarFrequency, ...], date, date]
        ] = []

    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries:
        self.requests.append((symbol, tuple(frequencies), since, through))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeDirectionContextResolver:
    def __init__(
        self,
        contexts: Mapping[date, SubingStrategyDirectionContext],
    ) -> None:
        self.contexts = contexts
        self.requests: list[tuple[str, tuple[date, ...]]] = []

    def resolve(
        self,
        symbol: str,
        target_days: Sequence[date],
    ) -> Mapping[date, SubingStrategyDirectionContext]:
        days = tuple(target_days)
        self.requests.append((symbol, days))
        return MappingProxyType({day: self.contexts[day] for day in days})


def loaded_series(
    *,
    segments: tuple[ResolvedContractSegment, ...],
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
) -> ActualDominantResearchSeries:
    def result(
        frequency: BarFrequency,
        bars: tuple[CanonicalBar, ...],
    ) -> MarketSeriesResult:
        return MarketSeriesResult(
            request_identity={
                "series_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": frequency.value,
            },
            bars=bars,
            coverage=((bars[0].bar_end, bars[-1].bar_end) if bars else None),
            resolved_contract_segments=segments,
        )

    return ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M5: result(BarFrequency.M5, bars_5m),
                BarFrequency.M15: result(BarFrequency.M15, bars_15m),
            }
        ),
        segments=segments,
    )
