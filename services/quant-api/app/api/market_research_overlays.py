"""Source-specific read-only Historical Research Overlay HTTP API."""

from __future__ import annotations

from datetime import date
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import ActiveUniverseError
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_lifecycle_policy import SubingLifecyclePolicyError
from app.market_data.composition import (
    build_subing_historical_signal_service,
    build_subing_strategy_historical_service,
)
from app.market_data.subing_historical_signal_service import (
    SubingHistoricalSignalRequest,
    SubingHistoricalSignalSegmentIdentityError,
    SubingHistoricalSignalSourceUnavailableError,
)
from app.market_data.subing_strategy.contracts import SubingStrategyAction
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
from app.schemas.research_overlays import (
    SubingHistoricalSignalEventOut,
    SubingHistoricalSignalRequestOut,
    SubingHistoricalSignalResponse,
    SubingStrategyActionOut,
    SubingStrategyBoundPivotOut,
    SubingStrategyContextUnavailableOut,
    SubingStrategyEpisodeOut,
    SubingStrategyHistoricalRequestOut,
    SubingStrategyHistoricalResponse,
    SubingStrategyPolicyOut,
    SubingStrategySegmentSummaryOut,
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
        episodes=[
            SubingStrategyEpisodeOut(
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
                current_reference_change_percent=(
                    episode.current_reference_change_percent
                ),
                latest_reference_price=episode.latest_reference_price,
                exit_reason_codes=list(episode.exit_reason_codes),
                structure_exit_available=episode.structure_exit_available,
            )
            for episode in result.episodes
        ],
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


@router.get("/subing/history", response_model=SubingHistoricalSignalResponse)
def subing_historical_signals(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    since: date = Query(...),
    through: date = Query(...),
    session: Session = Depends(get_db),
) -> SubingHistoricalSignalResponse:
    try:
        request = SubingHistoricalSignalRequest(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            frequency=cast(BarFrequency, frequency),
            since=since,
            through=through,
        )
        result = build_subing_historical_signal_service(session).history(request)
    except SubingCalibrationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except ActiveUniverseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SUBING_HISTORICAL_REQUEST"},
        ) from None
    except (
        SubingHistoricalSignalSegmentIdentityError,
        SubingHistoricalSignalSourceUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from None
    return SubingHistoricalSignalResponse(
        request=SubingHistoricalSignalRequestOut(
            series_kind=result.request.series_kind.value,
            symbol=result.request.symbol,
            frequency=result.request.frequency.value,
            since=result.request.since,
            through=result.request.through,
        ),
        events=[
            SubingHistoricalSignalEventOut(
                event_id=event.event_id,
                bar_end=event.bar_end,
                trading_day=event.trading_day,
                contract=event.contract,
                segment_start_trading_day=event.segment_start_trading_day,
                direction=event.direction.value,
                trigger_timeframe=event.trigger_timeframe.value,
                lower_tf_confirmation=event.lower_tf_confirmation,
            )
            for event in result.events
        ],
    )
