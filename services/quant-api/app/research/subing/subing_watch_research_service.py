"""Read-only Historical diagnostics for the frozen SuBing Watch kernel."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from guiyi_quant.indicators.subing_watch_15m import SUBING_WATCH_FORMULA_VERSION

from app.market_data.actual_dominant_research import (
    ActualDominantResearchReader,
    ActualDominantResearchSegmentLoader,
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSourceTradingDayMissingError,
)
from app.market_data.domain import BarFrequency, CanonicalBar, ResolvedContractSegment
from app.market_data.market_data_service import MarketDataError
from app.market_data.price_outcome import (
    PriceDirection,
    PriceDirectionalOutcome,
    build_price_outcomes_at,
    summarize_price_outcomes,
)
from app.market_data.subing_watch.contracts import (
    SubingWatchEvaluation,
    SubingWatchPolicy,
    SubingWatchSourceIdentity,
)
from app.market_data.subing_watch.replay import replay_subing_watch_segment


_ALLOWED_FORWARD_BARS = (1, 2, 4, 8)
RangeState = Literal[
    "range_unavailable", "no_active_range", "intact", "broken_up", "broken_down"
]
HigherTimeframeAlignment = Literal["aligned", "opposed", "neutral", "unavailable"]

_RANGE_STATES: tuple[RangeState, ...] = (
    "range_unavailable",
    "no_active_range",
    "intact",
    "broken_up",
    "broken_down",
)
_HIGHER_TIMEFRAME_ALIGNMENTS: tuple[HigherTimeframeAlignment, ...] = (
    "aligned",
    "opposed",
    "neutral",
    "unavailable",
)
_METRIC_QUANTUM = Decimal("0.000001")
FORMULA_VERSION = SUBING_WATCH_FORMULA_VERSION


class SubingWatchResearchError(ValueError):
    code = "SUBING_WATCH_RESEARCH_INVALID"

    def __init__(self, code: str | None = None) -> None:
        self.code = code or type(self).code
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingWatchResearchRequest:
    since: date
    through: date
    symbols: tuple[str, ...] | Literal["active"]
    forward_bars: tuple[int, ...]

    def __post_init__(self) -> None:
        symbols_valid = (type(self.symbols) is str and self.symbols == "active") or (
            type(self.symbols) is tuple
            and bool(self.symbols)
            and len(set(self.symbols)) == len(self.symbols)
            and all(_valid_symbol(symbol) for symbol in self.symbols)
            and "active" not in self.symbols
        )
        forward_valid = (
            type(self.forward_bars) is tuple
            and tuple(sorted(set(self.forward_bars))) == self.forward_bars
            and all(
                type(horizon) is int and horizon in _ALLOWED_FORWARD_BARS
                for horizon in self.forward_bars
            )
        )
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
            or not symbols_valid
            or not forward_valid
        ):
            raise ValueError("SUBING_WATCH_RESEARCH_REQUEST_INVALID")


@dataclass(frozen=True, slots=True)
class SubingWatchRate:
    numerator: int
    denominator: int
    value: Decimal | None


@dataclass(frozen=True, slots=True)
class SubingWatchClustering:
    adjacent_pair_count: int
    same_direction_pair_count: int
    rate: SubingWatchRate


@dataclass(frozen=True, slots=True)
class SubingWatchContextAvailability:
    available_count: int
    candidate_count: int
    rate: SubingWatchRate


@dataclass(frozen=True, slots=True)
class SubingWatchForwardDiagnostics:
    horizon: int
    sample_count: int
    truncated_count: int
    median_directional_close_change_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None


@dataclass(frozen=True, slots=True)
class SubingWatchProductDiagnostics:
    symbol: str
    candidate_count: int
    direction_counts: Mapping[str, int]
    candidates_per_trading_day: Mapping[str, int]
    same_direction_clustering: SubingWatchClustering
    session_distribution: Mapping[str, int]
    context_availability: SubingWatchContextAvailability
    range_state_distribution: Mapping[str, int]
    higher_timeframe_alignment_distribution: Mapping[str, int]
    forward_diagnostics: Mapping[int, SubingWatchForwardDiagnostics]

    def __post_init__(self) -> None:
        for field_name in (
            "direction_counts",
            "candidates_per_trading_day",
            "session_distribution",
            "range_state_distribution",
            "higher_timeframe_alignment_distribution",
            "forward_diagnostics",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(sorted(value.items()))),
            )


@dataclass(frozen=True, slots=True)
class SubingWatchResearchResult:
    products: tuple[SubingWatchProductDiagnostics, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    evaluation: SubingWatchEvaluation
    segment_bars: tuple[CanonicalBar, ...]
    segment_bar_index: int

    @property
    def direction(self) -> Literal["buy", "sell"]:
        if len(self.evaluation.observation_types) != 1:
            raise SubingWatchResearchError()
        return self.evaluation.observation_types[0]


class SubingWatchResearchService:
    """Replay physical rank-1 segments and summarize Candidate observations."""

    def __init__(
        self,
        market_data: ActualDominantResearchReader,
        *,
        products: Sequence[str],
        policy: SubingWatchPolicy,
    ) -> None:
        normalized = tuple(sorted(set(products)))
        if (
            not normalized
            or any(not _valid_symbol(product) for product in normalized)
            or type(policy) is not SubingWatchPolicy
        ):
            raise SubingWatchResearchError()
        self._loader = ActualDominantResearchSegmentLoader(market_data)
        self._products = normalized
        self._policy = policy

    def run(self, request: SubingWatchResearchRequest) -> SubingWatchResearchResult:
        if type(request) is not SubingWatchResearchRequest:
            raise TypeError("request must be SubingWatchResearchRequest")
        products = self._select_products(request.symbols)
        diagnostics = tuple(
            self._diagnose_product(product, request) for product in products
        )
        return SubingWatchResearchResult(diagnostics)

    def _select_products(
        self,
        requested: tuple[str, ...] | Literal["active"],
    ) -> tuple[str, ...]:
        if requested == "active":
            return self._products
        if any(symbol not in self._products for symbol in requested):
            raise SubingWatchResearchError(
                "SUBING_WATCH_RESEARCH_SYMBOL_INVALID"
            )
        return tuple(sorted(requested))

    def _diagnose_product(
        self,
        symbol: str,
        request: SubingWatchResearchRequest,
    ) -> SubingWatchProductDiagnostics:
        resolved = self._loader.load(
            symbol=symbol,
            frequencies=(BarFrequency.M15,),
            since=request.since,
            through=request.through,
        )
        bars_15m = resolved.results[BarFrequency.M15].bars
        bars_60m = self._load_optional_higher_timeframe(
            symbol,
            request,
            expected_segments=resolved.segments,
        )
        candidates: list[_Candidate] = []
        for segment in resolved.segments:
            segment_15m = _segment_bars(bars_15m, segment)
            if not segment_15m:
                continue
            segment_60m = _segment_bars(bars_60m, segment)
            identity = SubingWatchSourceIdentity(
                symbol=symbol,
                contract=segment.contract,
                segment_start_trading_day=segment.start_trading_day,
            )
            projection = replay_subing_watch_segment(
                identity,
                segment_15m,
                segment_60m,
                self._policy,
            )
            bars_by_identity = {
                (bar.bar_end, bar.trading_day): index
                for index, bar in enumerate(segment_15m)
            }
            for evaluation in projection.evaluations:
                if (
                    evaluation.outcome != "evaluated_candidate"
                    or not request.since
                    <= evaluation.trading_day
                    <= request.through
                ):
                    continue
                located = bars_by_identity.get(
                    (evaluation.bar_end, evaluation.trading_day)
                )
                if located is None:
                    raise SubingWatchResearchError()
                candidates.append(
                    _Candidate(evaluation, segment_15m, located)
                )
        return self._summarize(symbol, candidates, request.forward_bars)

    def _load_optional_higher_timeframe(
        self,
        symbol: str,
        request: SubingWatchResearchRequest,
        *,
        expected_segments: tuple[ResolvedContractSegment, ...],
    ) -> tuple[CanonicalBar, ...]:
        try:
            resolved = self._loader.load(
                symbol=symbol,
                frequencies=(BarFrequency.H1,),
                since=request.since,
                through=request.through,
            )
        except (
            ActualDominantResearchSegmentIdentityError,
            ActualDominantResearchSourceTradingDayMissingError,
            MarketDataError,
        ):
            return ()
        if resolved.segments != expected_segments:
            return ()
        result = resolved.results.get(BarFrequency.H1)
        return result.bars if result is not None else ()

    def _summarize(
        self,
        symbol: str,
        candidates: Sequence[_Candidate],
        forward_bars: tuple[int, ...],
    ) -> SubingWatchProductDiagnostics:
        if not candidates:
            return empty_subing_watch_product_diagnostics(symbol, forward_bars)
        ordered = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.evaluation.trading_day,
                    item.evaluation.bar_end,
                    item.evaluation.source_identity.contract,
                ),
            )
        )
        directions = Counter(candidate.direction for candidate in ordered)
        days = Counter(candidate.evaluation.trading_day.isoformat() for candidate in ordered)
        adjacency = tuple(
            (previous, current)
            for previous, current in zip(ordered, ordered[1:], strict=False)
            if previous.evaluation.trading_day == current.evaluation.trading_day
        )
        same_direction_count = sum(
            previous.direction == current.direction
            for previous, current in adjacency
        )
        context_count = sum(_context_available(item.evaluation) for item in ordered)
        range_counts = Counter(
            item.evaluation.context.range_state for item in ordered
        )
        higher_counts = Counter(
            item.evaluation.context.higher_timeframe_alignment for item in ordered
        )
        sessions = self._session_distribution(symbol, ordered)
        return SubingWatchProductDiagnostics(
            symbol=symbol,
            candidate_count=len(ordered),
            direction_counts=MappingProxyType(
                {"buy": directions["buy"], "sell": directions["sell"]}
            ),
            candidates_per_trading_day=MappingProxyType(dict(sorted(days.items()))),
            same_direction_clustering=SubingWatchClustering(
                adjacent_pair_count=len(adjacency),
                same_direction_pair_count=same_direction_count,
                rate=_rate(same_direction_count, len(adjacency)),
            ),
            session_distribution=MappingProxyType(sessions),
            context_availability=SubingWatchContextAvailability(
                available_count=context_count,
                candidate_count=len(ordered),
                rate=_rate(context_count, len(ordered)),
            ),
            range_state_distribution=MappingProxyType(
                {key: range_counts[key] for key in _RANGE_STATES}
            ),
            higher_timeframe_alignment_distribution=MappingProxyType(
                {key: higher_counts[key] for key in _HIGHER_TIMEFRAME_ALIGNMENTS}
            ),
            forward_diagnostics=MappingProxyType(
                _forward_diagnostics(ordered, forward_bars)
            ),
        )

    def _session_distribution(
        self,
        symbol: str,
        candidates: Sequence[_Candidate],
    ) -> dict[str, int]:
        trading_days = tuple(
            sorted({candidate.evaluation.trading_day for candidate in candidates})
        )
        sessions = self._loader.sessions(symbol=symbol, trading_days=trading_days)
        counts: Counter[str] = Counter()
        for candidate in candidates:
            windows = tuple(
                sorted(
                    sessions[candidate.evaluation.trading_day],
                    key=lambda window: (window.start, window.end),
                )
            )
            matches = tuple(
                index
                for index, window in enumerate(windows, start=1)
                if window.start < candidate.evaluation.bar_end <= window.end
            )
            if len(matches) != 1:
                raise SubingWatchResearchError(
                    "SUBING_WATCH_RESEARCH_SESSION_INVALID"
                )
            counts[f"session_{matches[0]}"] += 1
        return dict(sorted(counts.items()))


def empty_subing_watch_product_diagnostics(
    symbol: str,
    forward_bars: tuple[int, ...],
) -> SubingWatchProductDiagnostics:
    if not _valid_symbol(symbol):
        raise SubingWatchResearchError()
    return SubingWatchProductDiagnostics(
        symbol=symbol,
        candidate_count=0,
        direction_counts=MappingProxyType({"buy": 0, "sell": 0}),
        candidates_per_trading_day=MappingProxyType({}),
        same_direction_clustering=SubingWatchClustering(0, 0, _rate(0, 0)),
        session_distribution=MappingProxyType({}),
        context_availability=SubingWatchContextAvailability(0, 0, _rate(0, 0)),
        range_state_distribution=MappingProxyType(
            {key: 0 for key in _RANGE_STATES}
        ),
        higher_timeframe_alignment_distribution=MappingProxyType(
            {key: 0 for key in _HIGHER_TIMEFRAME_ALIGNMENTS}
        ),
        forward_diagnostics=MappingProxyType(
            {
                horizon: SubingWatchForwardDiagnostics(
                    horizon, 0, 0, None, None, None
                )
                for horizon in forward_bars
            }
        ),
    )


def _segment_bars(
    bars: Sequence[CanonicalBar],
    segment: ResolvedContractSegment,
) -> tuple[CanonicalBar, ...]:
    return tuple(
        bar
        for bar in bars
        if segment.start_trading_day
        <= bar.trading_day
        <= segment.end_trading_day
    )


def _valid_symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip().lower()
        and value.isascii()
        and value.isalpha()
    )


def _rate(numerator: int, denominator: int) -> SubingWatchRate:
    value = None if denominator == 0 else Decimal(numerator) / Decimal(denominator)
    return SubingWatchRate(numerator, denominator, value)


def _context_available(evaluation: SubingWatchEvaluation) -> bool:
    context = evaluation.context
    return all(
        value is not None
        for value in (
            context.ma21_slope_5_bps_per_bar,
            context.distance_to_ma21_atr14,
            context.macd_zero_distance_atr14,
            context.volume_ratio_20,
        )
    )


def _forward_diagnostics(
    candidates: Sequence[_Candidate],
    horizons: tuple[int, ...],
) -> dict[int, SubingWatchForwardDiagnostics]:
    if not horizons:
        return {}
    outcomes: dict[int, list[PriceDirectionalOutcome]] = {
        horizon: [] for horizon in horizons
    }
    for candidate in candidates:
        projected = build_price_outcomes_at(
            candidate.segment_bars,
            index=candidate.segment_bar_index,
            direction=(
                PriceDirection.LONG
                if candidate.direction == "buy"
                else PriceDirection.SHORT
            ),
            horizons=horizons,
            same_trading_day_only=False,
        )
        for horizon, outcome in projected.items():
            if outcome is not None:
                outcomes[horizon].append(outcome)
    result: dict[int, SubingWatchForwardDiagnostics] = {}
    for horizon in horizons:
        summary = summarize_price_outcomes(outcomes[horizon])
        result[horizon] = SubingWatchForwardDiagnostics(
            horizon=horizon,
            sample_count=summary.sample_count,
            truncated_count=len(candidates) - summary.sample_count,
            median_directional_close_change_bps=_quantize_metric(
                summary.median_directional_return_bps
            ),
            median_mfe_bps=_quantize_metric(summary.median_mfe_bps),
            median_mae_bps=_quantize_metric(summary.median_mae_bps),
        )
    return result


def _quantize_metric(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(_METRIC_QUANTUM)
