"""Source-specific read-only Historical Research Overlay HTTP API."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import (
    ActiveUniverseError,
    OperationalUniverseError,
)
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_lifecycle_policy import SubingLifecyclePolicyError
from app.market_data.composition import (
    build_subing_strategy_current_service,
    build_subing_strategy_historical_service,
    build_subing_strategy_performance_service,
)
from app.market_data.subing_strategy.contracts import (
    SUBING_STRATEGY_ID,
    SubingStrategyAction,
    SubingStrategyEpisode,
)
from app.market_data.subing_strategy.current_service import (
    SubingStrategyCurrentActiveProductError,
    SubingStrategyCurrentProjection,
    SubingStrategyCurrentRequest,
    SubingStrategyCurrentSourceIdentityError,
    SubingStrategyCurrentSourceUnavailableError,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyContextIdentityError,
)
from app.market_data.subing_strategy.policy import SubingStrategyPolicyError
from app.market_data.subing_strategy.service import (
    SubingStrategyActiveProductError,
    SubingStrategyHistoricalProjection,
    SubingStrategyHistoricalRequest,
    SubingStrategySegmentIdentityError,
    SubingStrategySourceUnavailableError,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceError,
    SubingStrategyPerformanceProjection,
    SubingStrategyPerformanceStats,
)
from app.schemas.research_overlays import (
    SubingStrategyActionOut,
    SubingStrategyBoundPivotOut,
    SubingStrategyContextUnavailableOut,
    SubingStrategyCurrentContextOut,
    SubingStrategyCurrentResponse,
    SubingStrategyEpisodeOut,
    SubingStrategyHistoricalRequestOut,
    SubingStrategyHistoricalResponse,
    SubingStrategyPolicyOut,
    SubingStrategyPendingSummaryOut,
    SubingStrategySegmentSummaryOut,
    SubingStrategyExitReasonCountOut,
    SubingStrategyPerformanceCoverageOut,
    SubingStrategyPerformanceResponse,
    SubingStrategyPerformanceStatsOut,
    SubingStrategyPerformanceSummaryOut,
)


router = APIRouter(prefix="/api/v1/market/research", tags=["market-research"])


def _strategy_action_out(action: SubingStrategyAction) -> SubingStrategyActionOut:
    pivot = action.bound_reference_pivot
    return SubingStrategyActionOut(
        action_id=action.action_id,
        episode_id=action.episode_id,
        strategy_id=action.strategy_id,
        formula_version=action.formula_version,
        kind=action.kind.value,
        symbol=action.symbol,
        contract=action.contract,
        trading_day=action.trading_day,
        segment_start_trading_day=action.segment_start_trading_day,
        opportunity_id=action.opportunity_id,
        decision_at=action.decision_at,
        effective_open_at=action.effective_open_at,
        effective_bar_end=action.effective_bar_end,
        reference_price=action.reference_price,
        fill_basis=action.fill_basis.value,
        confirmation_source=(
            action.confirmation_source.value
            if action.confirmation_source is not None
            else None
        ),
        reason_codes=list(action.reason_codes),
        direction_context_source_day=action.direction_context_source_day,
        direction_context_target_day=action.direction_context_target_day,
        bound_reference_pivot=(
            SubingStrategyBoundPivotOut(
                pivot_id=pivot.pivot_id,
                kind=pivot.kind.value,
                source_timeframe=pivot.source_timeframe.value,
                pivot_time=pivot.pivot_time,
                confirmed_at=pivot.confirmed_at,
                price=pivot.price,
                contract=pivot.contract,
                segment_start_trading_day=pivot.segment_start_trading_day,
            )
            if pivot is not None
            else None
        ),
    )


def _strategy_episode_out(episode: SubingStrategyEpisode) -> SubingStrategyEpisodeOut:
    return SubingStrategyEpisodeOut(
        episode_id=episode.episode_id,
        direction=episode.direction.value,
        entry_action=_strategy_action_out(episode.entry_action),
        exit_action=(
            _strategy_action_out(episode.exit_action)
            if episode.exit_action is not None
            else None
        ),
        state=episode.state.value,
        holding_bar_count=episode.holding_bar_count,
        reference_change_percent=episode.reference_change_percent,
        current_reference_change_percent=episode.current_reference_change_percent,
        latest_reference_price=episode.latest_reference_price,
        exit_reason_codes=list(episode.exit_reason_codes),
        structure_exit_available=episode.structure_exit_available,
    )


def _strategy_response(
    result: SubingStrategyHistoricalProjection,
) -> SubingStrategyHistoricalResponse:
    return SubingStrategyHistoricalResponse(
        request=SubingStrategyHistoricalRequestOut(
            series_kind=result.request.series_kind.value,
            symbol=result.request.symbol,
            frequency=result.request.frequency.value,
            since=result.request.since,
            through=result.request.through,
        ),
        policy=SubingStrategyPolicyOut(
            strategy_id=result.policy.strategy_id,
            formula_version=result.policy.formula_version,
            research_only=result.policy.research_only,
            series_kind=result.policy.series_kind.value,
            decision_frequency=result.policy.decision_frequency.value,
            lifecycle_policy_id=result.policy.lifecycle_policy_id,
            allowed_confirmation_sources=[
                source.value for source in result.policy.allowed_confirmation_sources
            ],
        ),
        resolved_cutoff=result.resolved_cutoff,
        segment_summaries=[
            SubingStrategySegmentSummaryOut(
                contract=summary.contract,
                start_trading_day=summary.start_trading_day,
                end_trading_day=summary.end_trading_day,
                loaded_through=summary.loaded_through,
                bar_count_1m=summary.bar_count_1m,
                bar_count_5m=summary.bar_count_5m,
                bar_count_15m=summary.bar_count_15m,
                initial_position=summary.initial_position.value,
                final_position=summary.final_position.value,
                terminal_bar_end=summary.terminal_bar_end,
                pending_action=summary.pending_action,
            )
            for summary in result.segment_summaries
        ],
        actions=[_strategy_action_out(action) for action in result.actions],
        episodes=[_strategy_episode_out(episode) for episode in result.episodes],
        context_unavailable=[
            SubingStrategyContextUnavailableOut(
                symbol=context.symbol,
                target_trading_day=context.target_trading_day,
                source_trading_day=context.source_trading_day,
                direction=context.direction.value,
                reason_codes=list(context.reason_codes),
                daily_bar_end=context.daily_bar_end,
                hourly_bar_end=context.hourly_bar_end,
                physical_contract=context.physical_contract,
            )
            for context in result.context_unavailable
        ],
        cache_state=result.cache_state,
    )


def _strategy_current_response(
    result: SubingStrategyCurrentProjection,
) -> SubingStrategyCurrentResponse:
    pending = result.pending_action
    context = result.direction_context
    return SubingStrategyCurrentResponse(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        series_kind="actual_dominant",
        symbol=result.request.symbol,
        frequency="15m",
        contract=result.contract,
        segment_start_trading_day=result.segment_start_trading_day,
        source_mode=result.source_mode,
        cutoff=result.cutoff,
        position_state=result.position_state.value,
        pending_action=(
            SubingStrategyPendingSummaryOut(
                kind=pending.kind.value,
                decision_at=pending.decision_at,
                opportunity_id=pending.opportunity_id,
                reason_codes=list(pending.reason_codes),
            )
            if pending is not None
            else None
        ),
        current_episode=(
            _strategy_episode_out(result.current_episode)
            if result.current_episode is not None
            else None
        ),
        latest_completed_episode=(
            _strategy_episode_out(result.latest_completed_episode)
            if result.latest_completed_episode is not None
            else None
        ),
        direction_context=SubingStrategyCurrentContextOut(
            symbol=context.symbol,
            target_trading_day=context.target_trading_day,
            source_trading_day=context.source_trading_day,
            direction=context.direction.value,
            reason_codes=list(context.reason_codes),
            daily_bar_end=context.daily_bar_end,
            hourly_bar_end=context.hourly_bar_end,
            physical_contract=context.physical_contract,
        ),
    )


def _performance_stats_out(
    value: SubingStrategyPerformanceStats,
) -> SubingStrategyPerformanceStatsOut:
    return SubingStrategyPerformanceStatsOut(**{
        field: getattr(value, field)
        for field in SubingStrategyPerformanceStatsOut.model_fields
    })


def _strategy_performance_response(
    result: SubingStrategyPerformanceProjection,
) -> SubingStrategyPerformanceResponse:
    return SubingStrategyPerformanceResponse(
        strategy_id=result.strategy_id,
        formula_version="subing_strategy_15m_v1",
        symbol=result.symbol,
        series_kind="actual_dominant",
        frequency="15m",
        coverage=SubingStrategyPerformanceCoverageOut(
            since=result.coverage_since,
            through=result.coverage_through,
            resolved_cutoff=result.resolved_cutoff,
            segment_count=result.segment_count,
            bar_count_15m=result.bar_count_15m,
            context_unavailable_count=result.context_unavailable_count,
        ),
        cache_state=result.cache_state,
        cache_identity_sha256=result.cache_identity_sha256,
        cache_generated_at=result.cache_generated_at,
        summary=SubingStrategyPerformanceSummaryOut(
            overall=_performance_stats_out(result.summary.overall),
            long=_performance_stats_out(result.summary.long),
            short=_performance_stats_out(result.summary.short),
            open_episodes=result.summary.open_episodes,
        ),
        exit_reason_counts=[
            SubingStrategyExitReasonCountOut(reason_code=code, count=count)
            for code, count in result.summary.exit_reason_counts
        ],
        episodes=[_strategy_episode_out(episode) for episode in result.episodes],
    )


@router.get(
    "/subing-strategy/performance",
    response_model=SubingStrategyPerformanceResponse,
)
def subing_strategy_performance(
    symbol: str = Query(...),
    session: Session = Depends(get_db),
) -> SubingStrategyPerformanceResponse:
    try:
        result = build_subing_strategy_performance_service(session).performance(symbol)
    except (
        ActiveUniverseError,
        SubingStrategyPerformanceError,
        SubingStrategyActiveProductError,
        SubingStrategySourceUnavailableError,
        SubingStrategySegmentIdentityError,
        SubingStrategyContextIdentityError,
        SubingStrategyPolicyError,
        SubingCalibrationError,
        SubingLifecyclePolicyError,
    ) as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from None
    return _strategy_performance_response(result)


@router.get(
    "/subing-strategy/current",
    response_model=SubingStrategyCurrentResponse,
)
def subing_strategy_current(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    session: Session = Depends(get_db),
) -> SubingStrategyCurrentResponse:
    try:
        request = SubingStrategyCurrentRequest(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            frequency=cast(BarFrequency, frequency),
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SUBING_STRATEGY_CURRENT_REQUEST"},
        ) from None
    try:
        result = build_subing_strategy_current_service(session).current(
            request, datetime.now(UTC)
        )
    except (
        SubingStrategyPolicyError,
        SubingCalibrationError,
        SubingLifecyclePolicyError,
        ActiveUniverseError,
        OperationalUniverseError,
        SubingStrategyCurrentActiveProductError,
        SubingStrategyCurrentSourceUnavailableError,
        SubingStrategyCurrentSourceIdentityError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except (ValueError, RuntimeError):
        raise HTTPException(
            status_code=409,
            detail={"code": "SUBING_STRATEGY_CURRENT_SOURCE_UNAVAILABLE"},
        ) from None
    return _strategy_current_response(result)


@router.get(
    "/subing-strategy/history",
    response_model=SubingStrategyHistoricalResponse,
)
def subing_strategy_history(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> SubingStrategyHistoricalResponse:
    try:
        request = SubingStrategyHistoricalRequest(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            frequency=cast(BarFrequency, frequency),
            since=since,
            through=through,
        )
        result = build_subing_strategy_historical_service(session).history(request)
    except (
        SubingStrategyPolicyError,
        SubingCalibrationError,
        SubingLifecyclePolicyError,
        ActiveUniverseError,
        SubingStrategyActiveProductError,
        SubingStrategySourceUnavailableError,
        SubingStrategySegmentIdentityError,
        SubingStrategyContextIdentityError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SUBING_STRATEGY_REQUEST"},
        ) from None
    return _strategy_response(result)
