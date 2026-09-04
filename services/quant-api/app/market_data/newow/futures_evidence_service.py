"""Read-only assembly of trusted inputs for later Newow futures evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping, Protocol

from guiyi_quant.newow import NewowResearchBar, NewowStrategyReplaySegment

from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.domain import (
    BarFrequency,
    ContractTradingDayQuery,
    MarketSeriesResult,
)

from .futures_validation import (
    NewowFuturesSeriesError,
    build_newow_research_bars,
    build_newow_strategy_replay_segments,
)


class PhysicalPrefixReader(Protocol):
    def query_contract_trading_days(
        self, request: ContractTradingDayQuery
    ) -> MarketSeriesResult: ...


@dataclass(frozen=True, slots=True)
class NewowFuturesEvidenceInput:
    execution_bars: tuple[NewowResearchBar, ...]
    strategy_replay_segments: tuple[NewowStrategyReplaySegment, ...]


def build_newow_futures_evidence_inputs(
    market_data: PhysicalPrefixReader,
    loaded: ActualDominantResearchSeries,
    *,
    expected_product: str,
    frequencies: tuple[BarFrequency, ...],
    through: date,
) -> Mapping[BarFrequency, NewowFuturesEvidenceInput]:
    """Assemble inputs without reading physical prefixes beyond one fold horizon."""

    if (
        not frequencies
        or len(set(frequencies)) != len(frequencies)
        or set(loaded.results) != set(frequencies)
        or type(through) is not date
    ):
        raise NewowFuturesSeriesError
    assembled: dict[BarFrequency, NewowFuturesEvidenceInput] = {}
    for frequency in frequencies:
        execution_bars = tuple(
            bar
            for bar in build_newow_research_bars(
                loaded.results[frequency],
                authoritative_segments=loaded.authoritative_segments,
                expected_product=expected_product,
                expected_frequency=frequency,
            )
            if bar.trading_day <= through
        )
        if not execution_bars:
            raise NewowFuturesSeriesError
        observed_segments = tuple(
            segment
            for segment in loaded.authoritative_segments
            if any(
                bar.physical_contract == segment.contract
                and segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
                for bar in execution_bars
            )
        )
        physical_results = tuple(
            market_data.query_contract_trading_days(
                ContractTradingDayQuery(
                    expected_product,
                    segment.contract,
                    frequency,
                    date.min,
                    max(
                        bar.trading_day
                        for bar in execution_bars
                        if bar.physical_contract == segment.contract
                        and segment.start_trading_day
                        <= bar.trading_day
                        <= segment.end_trading_day
                    ),
                )
            )
            for segment in observed_segments
        )
        assembled[frequency] = NewowFuturesEvidenceInput(
            execution_bars,
            build_newow_strategy_replay_segments(
                execution_bars,
                authoritative_segments=loaded.authoritative_segments,
                physical_prefix_results=physical_results,
                expected_product=expected_product,
                expected_frequency=frequency,
            ),
        )
    return MappingProxyType(assembled)
