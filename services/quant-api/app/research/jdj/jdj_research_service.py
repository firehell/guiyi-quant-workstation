"""Read-only orchestration for exact JDJ 1m candidate research."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from statistics import median
from typing import Protocol

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    normalize_contract_for_symbol,
)
from .jdj_context import JdjContextError, build_jdj_context_series
from .jdj_policy import JdjPolicy, is_exact_jdj_policy
from .jdj_key_level_breakout import (
    JdjKeyLevelBreakoutTrace,
    reduce_jdj_key_level_breakout,
)
from .jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    JdjTriggerEvent,
)
from .jdj_research import (
    JDJ_CANDIDATE_SOURCE_EVENT_KINDS,
    JdjBatchResearchResult,
    JdjDetailedCandidateResult,
    JdjEventOutcomeRecord,
    JdjResearchRequest,
    JdjResearchResult,
    JdjSourceUnavailableError,
)
from .jdj_trend_follow import JdjTrendFollowTrace, reduce_jdj_trend_follow
from .jdj_trend_reentry import (
    JdjTrendReentryTrace,
    reduce_jdj_trend_reentry_6,
)
from app.research.n_structure.n_structure_policy import (
    NStructurePolicy,
    is_exact_n_structure_policy,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.price_outcome import (
    PriceDirection,
    PriceDirectionalOutcome,
    PriceHorizonEvaluation,
    build_price_outcomes_at,
)


_HORIZONS = (3, 5, 8, 20)
_TREND_FOLLOW = "jdj_trend_follow_1m_candidate_v1"
_TREND_REENTRY = "jdj_trend_reentry_6_1m_candidate_v1"
_KEY_LEVEL_BREAKOUT = "jdj_key_level_breakout_1m_candidate_v1"
_EVENT_TYPES = {
    _TREND_FOLLOW: JdjTrendFollowTriggerEvent,
    _TREND_REENTRY: JdjTrendReentryTriggerEvent,
    _KEY_LEVEL_BREAKOUT: JdjKeyLevelBreakoutTriggerEvent,
}
_JdjTrace = (
    JdjTrendFollowTrace
    | JdjTrendReentryTrace
    | JdjKeyLevelBreakoutTrace
)
_JdjReducer = Callable[..., _JdjTrace]


class _ResearchSegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


class JdjResearchService:
    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        products: Sequence[str],
        jdj_policy: JdjPolicy,
        n_policy: NStructurePolicy,
    ) -> None:
        if (
            not isinstance(products, Sequence)
            or isinstance(products, (str, bytes))
            or any(type(product) is not str for product in products)
        ):
            raise JdjContextError()
        normalized = tuple(
            dict.fromkeys(product.strip().lower() for product in products)
        )
        if (
            not normalized
            or any(
                not product or not product.isascii() or not product.isalpha()
                for product in normalized
            )
            or not is_exact_jdj_policy(jdj_policy)
            or not is_exact_n_structure_policy(n_policy)
        ):
            raise JdjContextError()
        self._segment_loader = segment_loader
        self._products = normalized
        self._jdj_policy = jdj_policy
        self._n_policy = n_policy

    def run(self, request: JdjResearchRequest) -> JdjResearchResult:
        if not isinstance(request, JdjResearchRequest):
            raise TypeError("request must be JdjResearchRequest")
        products = self._selected_products(request.symbol)
        detailed_results: list[JdjDetailedCandidateResult] = []
        for product in products:
            detailed, _, _ = self._load_and_evaluate(
                symbol=product,
                since=request.since,
                through=request.through,
                candidate_ids=(request.candidate_id,),
            )
            detailed_results.append(detailed[0])
        return _combine_candidate_results(
            detailed_results,
            candidate_id=request.candidate_id,
            products=products,
        )

    def run_batch(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
    ) -> JdjBatchResearchResult:
        request = JdjResearchRequest(
            since=since,
            through=through,
            symbol=symbol,
            candidate_id=_TREND_FOLLOW,
        )
        selected = self._selected_products(request.symbol)
        detailed, observed_since, observed_through = self._load_and_evaluate(
            symbol=selected[0],
            since=request.since,
            through=request.through,
            candidate_ids=tuple(JDJ_CANDIDATE_SOURCE_EVENT_KINDS),
        )
        if observed_since is None or observed_through is None:
            raise JdjSourceUnavailableError()
        return JdjBatchResearchResult(
            symbol=selected[0],
            observed_since=observed_since,
            observed_through=observed_through,
            candidates=detailed,
        )

    def _load_and_evaluate(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
        candidate_ids: tuple[str, ...],
    ) -> tuple[
        tuple[JdjDetailedCandidateResult, ...],
        date | None,
        date | None,
    ]:
        try:
            loaded = self._segment_loader.load(
                symbol=symbol,
                frequencies=(BarFrequency.M1, BarFrequency.M5),
                since=since,
                through=through,
            )
            return self._evaluate_loaded_series(
                loaded,
                symbol=symbol,
                since=since,
                through=through,
                candidate_ids=candidate_ids,
            )
        except (
            MarketDataError,
            ActualDominantResearchSegmentIdentityError,
        ):
            raise JdjSourceUnavailableError() from None

    def _evaluate_loaded_series(
        self,
        loaded: ActualDominantResearchSeries,
        *,
        symbol: str,
        since: date,
        through: date,
        candidate_ids: tuple[str, ...],
    ) -> tuple[
        tuple[JdjDetailedCandidateResult, ...],
        date | None,
        date | None,
    ]:
        if (
            not candidate_ids
            or len(set(candidate_ids)) != len(candidate_ids)
            or any(
                candidate_id not in JDJ_CANDIDATE_SOURCE_EVENT_KINDS
                for candidate_id in candidate_ids
            )
        ):
            raise JdjContextError()
        bars_1m_by_segment, bars_5m_by_segment = (
            _validated_segment_partitions(
                loaded,
                symbol=symbol,
                through=through,
            )
        )
        event_records: dict[
            str,
            list[tuple[JdjTriggerEvent, JdjEventOutcomeRecord]],
        ] = {candidate_id: [] for candidate_id in candidate_ids}
        evaluable_bar_count = 0
        observed_days: list[date] = []

        for segment, bars_1m, bars_5m in zip(
            loaded.segments,
            bars_1m_by_segment,
            bars_5m_by_segment,
            strict=True,
        ):
            contexts = build_jdj_context_series(
                bars_1m,
                bars_5m,
                contract=segment.contract,
                segment_start_trading_day=segment.start_trading_day,
                segment_end_trading_day=segment.end_trading_day,
                jdj_policy=self._jdj_policy,
                n_policy=self._n_policy,
            )
            requested_bars = tuple(
                bar for bar in bars_1m if since <= bar.trading_day <= through
            )
            evaluable_bar_count += len(requested_bars)
            observed_days.extend(bar.trading_day for bar in requested_bars)

            for candidate_id in candidate_ids:
                trace = _reducer_for_candidate(candidate_id)(
                    contexts,
                    symbol=symbol,
                    contract=segment.contract,
                    segment_start_trading_day=segment.start_trading_day,
                )
                source_event_kind = JDJ_CANDIDATE_SOURCE_EVENT_KINDS[
                    candidate_id
                ]
                for event in trace.events:
                    _validate_event_alignment(
                        event,
                        candidate_id=candidate_id,
                        source_event_kind=source_event_kind,
                        symbol=symbol,
                        segment=segment,
                        bars_1m=bars_1m,
                    )
                    if not since <= event.trading_day <= through:
                        continue
                    direction = (
                        PriceDirection.LONG
                        if event.direction is JdjDirection.LONG
                        else PriceDirection.SHORT
                    )
                    projected = build_price_outcomes_at(
                        bars_1m,
                        index=event.segment_bar_index,
                        direction=direction,
                        horizons=_HORIZONS,
                        same_trading_day_only=True,
                    )
                    event_records[candidate_id].append(
                        (
                            event,
                            JdjEventOutcomeRecord(
                                event_id=event.event_id,
                                trading_day=event.trading_day,
                                outcomes=projected,
                            ),
                        )
                    )

        detailed = tuple(
            _build_detailed_candidate_result(
                event_records[candidate_id],
                candidate_id=candidate_id,
                products=(symbol,),
                segment_count=len(loaded.segments),
                evaluable_bar_count=evaluable_bar_count,
            )
            for candidate_id in candidate_ids
        )
        return (
            detailed,
            min(observed_days) if observed_days else None,
            max(observed_days) if observed_days else None,
        )

    def _selected_products(self, symbol: str | None) -> tuple[str, ...]:
        if symbol is None:
            return self._products
        if symbol not in self._products:
            raise JdjContextError()
        return (symbol,)


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
        matches = tuple(
            index
            for index, segment in enumerate(segments)
            if (
                segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
        )
        if len(matches) != 1:
            raise ActualDominantResearchSegmentIdentityError()
        grouped[matches[0]].append(bar)
    return tuple(tuple(group) for group in grouped)


def _validated_segment_partitions(
    loaded: ActualDominantResearchSeries,
    *,
    symbol: str,
    through: date,
) -> tuple[
    tuple[tuple[CanonicalBar, ...], ...],
    tuple[tuple[CanonicalBar, ...], ...],
]:
    if not isinstance(loaded, ActualDominantResearchSeries):
        raise ActualDominantResearchSegmentIdentityError()
    segments = loaded.segments
    if (
        type(segments) is not tuple
        or not segments
        or any(
            not isinstance(segment, ResolvedContractSegment)
            or normalize_contract_for_symbol(symbol, segment.contract)
            != segment.contract
            or type(segment.start_trading_day) is not date
            or type(segment.end_trading_day) is not date
            or segment.start_trading_day > segment.end_trading_day
            for segment in segments
        )
        or any(
            current.start_trading_day <= previous.end_trading_day
            for previous, current in zip(segments, segments[1:])
        )
        or set(loaded.results) != {BarFrequency.M1, BarFrequency.M5}
    ):
        raise ActualDominantResearchSegmentIdentityError()

    partitions = []
    for frequency in (BarFrequency.M1, BarFrequency.M5):
        result = loaded.results[frequency]
        if (
            not isinstance(result, MarketSeriesResult)
            or any(not isinstance(bar, CanonicalBar) for bar in result.bars)
            or any(
                previous.bar_end >= current.bar_end
                or previous.trading_day > current.trading_day
                for previous, current in zip(result.bars, result.bars[1:])
            )
        ):
            raise ActualDominantResearchSegmentIdentityError()
        grouped = _partition_segment_bars(
            result.bars,
            segments=segments,
            through=through,
        )
        if any(not group for group in grouped):
            raise ActualDominantResearchSegmentIdentityError()
        if not _segments_are_exact_window_projection(
            result.resolved_contract_segments,
            segments,
            result.bars,
        ):
            raise ActualDominantResearchSegmentIdentityError()
        partitions.append(grouped)
    if any(
        {bar.trading_day for bar in bars_1m}
        != {bar.trading_day for bar in bars_5m}
        for bars_1m, bars_5m in zip(
            partitions[0],
            partitions[1],
            strict=True,
        )
    ):
        raise ActualDominantResearchSegmentIdentityError()
    return partitions[0], partitions[1]


def _segments_are_exact_window_projection(
    projected: tuple[ResolvedContractSegment, ...],
    true_segments: tuple[ResolvedContractSegment, ...],
    bars: tuple[CanonicalBar, ...],
) -> bool:
    if type(projected) is not tuple or len(projected) != len(true_segments):
        return False
    grouped_bars = tuple(
        tuple(
            bar
            for bar in bars
            if (
                segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
        )
        for segment in true_segments
    )
    if sum(len(group) for group in grouped_bars) != len(bars):
        return False
    for clipped, true_segment, bars in zip(
        projected,
        true_segments,
        grouped_bars,
        strict=True,
    ):
        if (
            not isinstance(clipped, ResolvedContractSegment)
            or not bars
            or clipped.contract != true_segment.contract
            or not (
                true_segment.start_trading_day
                <= clipped.start_trading_day
                <= clipped.end_trading_day
                <= true_segment.end_trading_day
            )
            or clipped.start_trading_day
            != min(bar.trading_day for bar in bars)
            or clipped.end_trading_day
            != max(bar.trading_day for bar in bars)
        ):
            return False
    return True


def _reducer_for_candidate(candidate_id: str) -> _JdjReducer:
    if candidate_id == _TREND_FOLLOW:
        return reduce_jdj_trend_follow
    if candidate_id == _TREND_REENTRY:
        return reduce_jdj_trend_reentry_6
    if candidate_id == _KEY_LEVEL_BREAKOUT:
        return reduce_jdj_key_level_breakout
    raise JdjContextError()


def _validate_event_alignment(
    event: object,
    *,
    candidate_id: str,
    source_event_kind: str,
    symbol: str,
    segment: ResolvedContractSegment,
    bars_1m: tuple[CanonicalBar, ...],
) -> None:
    event_type = _EVENT_TYPES[candidate_id]
    if not isinstance(
        event,
        (
            JdjTrendFollowTriggerEvent,
            JdjTrendReentryTriggerEvent,
            JdjKeyLevelBreakoutTriggerEvent,
        ),
    ) or not isinstance(event, event_type):
        raise JdjContextError()
    index = event.segment_bar_index
    if index >= len(bars_1m):
        raise JdjContextError()
    bar = bars_1m[index]
    if (
        event.candidate_id != candidate_id
        or event.source_event_kind != source_event_kind
        or event.symbol != symbol
        or event.contract != segment.contract
        or event.segment_start_trading_day != segment.start_trading_day
        or event.observed_at != bar.bar_end
        or event.trading_day != bar.trading_day
        or event.observation_close != bar.close
    ):
        raise JdjContextError()


def _build_detailed_candidate_result(
    event_records: Sequence[
        tuple[JdjTriggerEvent, JdjEventOutcomeRecord]
    ],
    *,
    candidate_id: str,
    products: tuple[str, ...],
    segment_count: int,
    evaluable_bar_count: int,
) -> JdjDetailedCandidateResult:
    ordered = tuple(
        sorted(event_records, key=lambda item: _event_order_key(item[0]))
    )
    events = tuple(event for event, _ in ordered)
    if len({event.event_id for event in events}) != len(events):
        raise JdjContextError()
    outcomes = {
        horizon: tuple(
            outcome
            for _, record in ordered
            if (outcome := record.outcomes[horizon]) is not None
        )
        for horizon in _HORIZONS
    }
    return JdjDetailedCandidateResult(
        result=JdjResearchResult(
            candidate_id=candidate_id,
            source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[candidate_id],
            products=products,
            segment_count=segment_count,
            evaluable_bar_count=evaluable_bar_count,
            trigger_count_long=sum(
                event.direction is JdjDirection.LONG for event in events
            ),
            trigger_count_short=sum(
                event.direction is JdjDirection.SHORT for event in events
            ),
            horizon_summary={
                horizon: _evaluate_horizon(outcomes[horizon])
                for horizon in _HORIZONS
            },
            events=events,
        ),
        event_outcomes=tuple(record for _, record in ordered),
    )


def _combine_candidate_results(
    detailed_results: Sequence[JdjDetailedCandidateResult],
    *,
    candidate_id: str,
    products: tuple[str, ...],
) -> JdjResearchResult:
    if (
        not detailed_results
        or any(
            detail.result.candidate_id != candidate_id
            for detail in detailed_results
        )
    ):
        raise JdjContextError()
    combined = _build_detailed_candidate_result(
        tuple(
            pair
            for detail in detailed_results
            for pair in zip(
                detail.result.events,
                detail.event_outcomes,
                strict=True,
            )
        ),
        candidate_id=candidate_id,
        products=products,
        segment_count=sum(
            detail.result.segment_count for detail in detailed_results
        ),
        evaluable_bar_count=sum(
            detail.result.evaluable_bar_count for detail in detailed_results
        ),
    )
    return combined.result


def _evaluate_horizon(
    outcomes: Sequence[PriceDirectionalOutcome],
) -> PriceHorizonEvaluation:
    if not outcomes:
        return PriceHorizonEvaluation(0, None, None, None)
    return PriceHorizonEvaluation(
        sample_count=len(outcomes),
        median_directional_return_bps=median(
            outcome.directional_return_bps for outcome in outcomes
        ),
        median_mfe_bps=median(outcome.mfe_bps for outcome in outcomes),
        median_mae_bps=median(outcome.mae_bps for outcome in outcomes),
    )


def _event_order_key(event: JdjTriggerEvent) -> tuple[object, ...]:
    return event.observed_at, event.segment_bar_index, event.event_id
