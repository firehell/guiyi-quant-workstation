"""Completed JM matrix inputs from the shared MDS rank-1 and physical readers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import (
    BarFrequency,
    ContractTradingDayQuery,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.futures_validation import (
    build_newow_research_bars,
    build_newow_strategy_replay_segments,
)
from app.market_data.newow.jm_pilot_research import _input_sha256, load_jm_pilot_input
from app.market_data.newow.product_reader import NewowProductReader
from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.research_backtest import (
    NewowResearchBar,
    NewowStrategyReplaySegment,
    validate_research_bars,
)


MATRIX_FREQUENCIES = frozenset({
    ProductFrequency.FIVE_MINUTE,
    ProductFrequency.QUARTER_HOURLY,
    ProductFrequency.HALF_HOURLY,
    ProductFrequency.HOURLY,
    ProductFrequency.DAILY,
    ProductFrequency.WEEKLY,
})


@dataclass(frozen=True, slots=True)
class MatrixInput:
    bars: tuple[NewowResearchBar, ...]
    replay_segments: tuple[NewowStrategyReplaySegment, ...]
    requested_since: date
    actual_through: date
    input_sha256: str
    frequency: ProductFrequency

    def __post_init__(self) -> None:
        if (
            self.frequency not in MATRIX_FREQUENCIES
            or type(self.requested_since) is not date
            or type(self.actual_through) is not date
            or self.requested_since > self.actual_through
            or len(self.input_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.input_sha256)
            or not self.bars
            or not self.replay_segments
            or any(
                bar.product != "jm"
                or bar.frequency != self.frequency.value
                or not bar.observation_eligible
                or bar.trading_day < self.requested_since
                or bar.trading_day > self.actual_through
                for bar in self.bars
            )
        ):
            raise ValueError("JM_MATRIX_INPUT_INVALID")
        validate_research_bars(self.bars)
        eligible = tuple(
            bar for segment in self.replay_segments for bar in segment.bars
            if bar.observation_eligible
        )
        if eligible != self.bars or _input_sha256(self.replay_segments) != self.input_sha256:
            raise ValueError("JM_MATRIX_INPUT_INVALID")


def _physical_since(frequency: BarFrequency, owner_start: date) -> date:
    if frequency in {
        BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1,
    }:
        return owner_start - timedelta(days=30)
    # MDS clips the request to the authoritative listed date and validates
    # every completed physical endpoint. Daily/weekly warm-up is all available
    # same-contract history, never an arbitrary 30-day prefix.
    return date.min


def _check_daily_weekly_quality(
    market_data: MarketDataService,
    *,
    frequency: BarFrequency,
    physical: MarketSeriesResult,
    contract: str,
) -> None:
    if not physical.bars:
        raise ValueError("JM_MATRIX_PHYSICAL_PREFIX_MISSING")
    if frequency is BarFrequency.D1:
        checked, daily_gaps = market_data.query_contract_replay_quality_union(
            symbol="jm", contract=contract,
            through=physical.bars[-1].trading_day,
            cutoff=physical.bars[-1].bar_end,
        )
        has_gaps = bool(daily_gaps)
    elif frequency is BarFrequency.W1:
        checked, weekly_gaps = market_data.query_contract_weekly_replay_quality(
            symbol="jm", contract=contract,
            through=physical.bars[-1].trading_day,
            cutoff=physical.bars[-1].bar_end,
        )
        has_gaps = bool(weekly_gaps)
    else:
        return
    if has_gaps or tuple(checked) != physical.bars:
        raise ValueError("JM_MATRIX_PHYSICAL_PREFIX_QUALITY_GAP")


def _last_completed_weekly_endpoint(
    market_data: MarketDataService,
    *,
    owners: tuple[ResolvedContractSegment, ...],
    actual_through: date,
    cutoff: datetime,
) -> tuple[date, datetime]:
    endpoints = tuple(
        (day, end)
        for owner in owners
        for end, day in market_data.expected_contract_replay_endpoints(
            symbol="jm", contract=owner.contract, frequency=BarFrequency.W1,
            trading_day=min(owner.end_trading_day, actual_through), cutoff=cutoff,
            since=owner.start_trading_day,
        )
        if owner.start_trading_day <= day <= min(owner.end_trading_day, actual_through)
    )
    if not endpoints:
        raise ValueError("JM_MATRIX_COMPLETED_WEEKLY_INPUT_MISSING")
    return max(endpoints, key=lambda item: item[1])


def load_matrix_input(
    market_data: MarketDataService,
    reader: NewowProductReader,
    frequency: ProductFrequency,
    *,
    since: date,
    requested_through: date,
    as_of: datetime,
) -> MatrixInput:
    """Load one fixed JM signal clock; execution uses a separate MDS 1m clock."""

    try:
        frequency = ProductFrequency(frequency)
    except ValueError:
        raise ValueError("JM_MATRIX_FREQUENCY_INVALID") from None
    if (
        frequency not in MATRIX_FREQUENCIES
        or type(since) is not date
        or type(requested_through) is not date
        or since > requested_through
        or not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise ValueError("JM_MATRIX_WINDOW_INVALID")
    window = reader.resolve_performance_window(
        "jm", frequency, since, requested_through, as_of,
    )
    through = window.actual_through
    if frequency is ProductFrequency.FIVE_MINUTE:
        pilot = load_jm_pilot_input(market_data, since=since, actual_through=through)
        return MatrixInput(
            pilot.bars, pilot.replay_segments, since, through,
            pilot.input_sha256, frequency,
        )

    bar_frequency = BarFrequency(frequency.value)
    loaded = ActualDominantResearchSegmentLoader(market_data).load(
        symbol="jm", frequencies=(bar_frequency,), since=since, through=through,
    )
    actual = build_newow_research_bars(
        loaded.results[bar_frequency],
        authoritative_segments=loaded.authoritative_segments,
        expected_product="jm", expected_frequency=bar_frequency,
    )
    observed = tuple(
        owner for owner in loaded.authoritative_segments
        if any(
            owner.start_trading_day <= bar.trading_day <= owner.end_trading_day
            for bar in actual
        )
    )
    physical = tuple(
        market_data.query_contract_trading_days(ContractTradingDayQuery(
            "jm", owner.contract, bar_frequency,
            _physical_since(bar_frequency, owner.start_trading_day),
            max(
                bar.trading_day for bar in actual
                if owner.start_trading_day <= bar.trading_day <= owner.end_trading_day
            ),
        ))
        for owner in observed
    )
    for owner, result in zip(observed, physical, strict=True):
        _check_daily_weekly_quality(
            market_data, frequency=bar_frequency, physical=result,
            contract=owner.contract,
        )
    replay = build_newow_strategy_replay_segments(
        actual,
        authoritative_segments=loaded.authoritative_segments,
        physical_prefix_results=physical,
        expected_product="jm", expected_frequency=bar_frequency,
    )
    scoped = tuple(
        NewowStrategyReplaySegment(tuple(
            bar if bar.trading_day >= since else replace(
                bar, observation_eligible=False, series_kind="contract",
                source_identity=(
                    f"canonical:contract:jm:{frequency.value}:"
                    f"{bar.physical_contract}:"
                    f"{bar.trading_day.isoformat()}:{bar.bar_end.isoformat()}"
                ),
            )
            for bar in segment.bars
        ))
        for segment in replay
    )
    scored = tuple(bar for bar in actual if bar.trading_day >= since)
    if not scored:
        raise ValueError("JM_MATRIX_COMPLETED_INPUT_MISSING")
    if frequency is ProductFrequency.WEEKLY:
        last_day, last_end = _last_completed_weekly_endpoint(
            market_data, owners=loaded.authoritative_segments,
            actual_through=through, cutoff=window.cutoff,
        )
        if (scored[-1].trading_day, scored[-1].bar_end) != (last_day, last_end):
            raise ValueError("JM_MATRIX_COMPLETED_WEEKLY_INPUT_MISSING")
    elif scored[-1].trading_day != through:
        raise ValueError("JM_MATRIX_COMPLETED_INPUT_MISSING")
    return MatrixInput(scored, scoped, since, through, _input_sha256(scoped), frequency)
