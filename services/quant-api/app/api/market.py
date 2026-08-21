"""Market 行情只读 HTTP API。

所有数据经 ``MarketDataService`` 查询 Canonical Parquet 与八表 Catalog；消费者不得
绕过完整性校验。合同类错误映射为 422，数据可用性/冲突类错误映射为 409。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_main_force_mirror_v2_service,
    build_market_data_service,
    build_market_radar_service,
    build_market_research_service,
    build_subing_read_service,
)
from app.market_data.domain import (
    BarFrequency,
    ContractError,
    SeriesKind,
    SeriesPageQuery,
    parse_rfc3339_instant,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.main_force_mirror_v2_service import (
    MainForceMirrorV2Error,
    MainForceMirrorV2PageResult,
)
from app.market_data.market_research_service import ResearchSeriesIdentity
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_lifecycle import SubingLifecycleSnapshot
from app.market_data.subing_read_service import SubingReadRequest
from app.market_data.subing_research import SubingFactorResult, SubingSignalEvaluation
from app.schemas.market import (
    ContractSegmentOut,
    CoverageOut,
    DominantContractListResponse,
    DominantContractOut,
    MarketBarOut,
    MarketBarsPageResponse,
    MainForceMirrorV2IndicatorOut,
    MainForceMirrorV2MemberCoverageOut,
    MainForceMirrorV2MemberDatasetOut,
    MainForceMirrorV2PageResponse,
    MainForceMirrorV2PointOut,
    MarketPageMetaOut,
    MarketRadarItemOut,
    MarketRadarResponse,
    MarketRadarSectorOut,
    MarketRadarSummaryOut,
    ProductResearchResponse,
    SubingConditionOut,
    SubingFactorResultOut,
    SubingFactorSnapshotOut,
    SubingLifecyclePivotOut,
    SubingLifecycleSnapshotOut,
    SubingLifecycleTransitionOut,
    SubingResearchResponse,
    SubingSignalOut,
)
from guiyi_quant.indicators.main_force_mirror_v2 import (
    round_half_away_from_zero_binary64,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])

_MFM_V2_REQUEST_CODES = frozenset(
    {
        "MFM_V2_UNSUPPORTED_FREQUENCY",
        "MFM_V2_UNSUPPORTED_SERIES_KIND",
        "MFM_V2_CONTRACT_INVALID",
        "MFM_V2_REQUEST_INVALID",
    }
)
_MFM_V2_CONFLICT_CODES = frozenset(
    {
        "MFM_V2_MARKET_IDENTITY_CONFLICT",
        "MFM_V2_PHYSICAL_CONTRACT_MISSING",
        "MFM_V2_MEMBER_DATASET_INVALID",
        "MFM_V2_MEMBER_DATASET_IDENTITY_CONFLICT",
    }
)


@router.get("/bars/page", response_model=MarketBarsPageResponse)
def canonical_market_bars_page(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    before: str | None = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=2000),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MarketBarsPageResponse:
    """按独占历史游标读取 Canonical K 线页。"""
    try:
        request = SeriesPageQuery(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            contract=contract,
            frequency=cast(BarFrequency, frequency),
            before=(
                parse_rfc3339_instant(before, field="datetime")
                if before is not None
                else None
            ),
            limit=limit,
        )
        result = build_market_data_service(session).query_page(request)
    except ContractError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    return MarketBarsPageResponse(
        request=dict(result.request_identity),
        bars=[
            MarketBarOut(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
            for bar in result.bars
        ],
        canonical_coverage=(
            CoverageOut(
                start=result.canonical_coverage[0],
                end=result.canonical_coverage[1],
            )
            if result.canonical_coverage
            else None
        ),
        page=MarketPageMetaOut(
            has_more_before=result.has_more_before,
            next_before=result.next_before,
        ),
        resolved_contract_segments=[
            ContractSegmentOut(
                contract=item.contract,
                start_trading_day=item.start_trading_day,
                end_trading_day=item.end_trading_day,
            )
            for item in result.resolved_contract_segments
        ],
    )


@router.get(
    "/research/main-force-mirror",
    response_model=MainForceMirrorV2PageResponse,
)
def main_force_mirror_v2_page(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    before: str | None = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=2000),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MainForceMirrorV2PageResponse:
    """Return confirmed historical V2 observations for one exact page."""
    try:
        request = SeriesPageQuery(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            contract=contract,
            frequency=cast(BarFrequency, frequency),
            before=(
                parse_rfc3339_instant(before, field="datetime")
                if before is not None
                else None
            ),
            limit=limit,
        )
        result = build_main_force_mirror_v2_service(session).query_page(request)
        return to_main_force_mirror_v2_response(result)
    except ContractError as exc:
        field = exc.facts.get("field")
        code = (
            "MFM_V2_UNSUPPORTED_SERIES_KIND"
            if field == "series_kind"
            else "MFM_V2_UNSUPPORTED_FREQUENCY"
            if field == "frequency"
            else "MFM_V2_CONTRACT_INVALID"
            if field == "contract"
            else "MFM_V2_REQUEST_INVALID"
        )
        raise HTTPException(status_code=422, detail={"code": code}) from None
    except MainForceMirrorV2Error as exc:
        code = (
            exc.code
            if exc.code in _MFM_V2_REQUEST_CODES | _MFM_V2_CONFLICT_CODES
            else "MFM_V2_MARKET_IDENTITY_CONFLICT"
        )
        status_code = 422 if code in _MFM_V2_REQUEST_CODES else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": code},
        ) from None


def to_main_force_mirror_v2_response(
    result: MainForceMirrorV2PageResult,
) -> MainForceMirrorV2PageResponse:
    dataset = result.member_dataset
    return MainForceMirrorV2PageResponse(
        request=dict(result.request_identity),
        indicator=MainForceMirrorV2IndicatorOut(
            indicator_code="main_force_mirror_v2",
            indicator_version="futures-member-research-v2",
            formal_policy_id="main_force_mirror_observation_v2",
            parameters_hash=result.parameters_hash,
            interpretation=(
                "directional_position_pressure_proxy_not_measured_fund_flow"
            ),
            observation_only=True,
            historical_only=True,
            auto_order=False,
        ),
        member_dataset=MainForceMirrorV2MemberDatasetOut(
            status=dataset.status,
            dataset_id=dataset.dataset_id,
            schema_version=dataset.schema_version,
            admitted_product=dataset.admitted_product,
            coverage=(
                MainForceMirrorV2MemberCoverageOut(
                    start=dataset.coverage[0],
                    end=dataset.coverage[1],
                )
                if dataset.coverage is not None
                else None
            ),
        ),
        points=[_main_force_mirror_v2_point(point) for point in result.points],
        page=MarketPageMetaOut(
            has_more_before=result.has_more_before,
            next_before=result.next_before,
        ),
        resolved_contract_segments=[
            ContractSegmentOut(
                contract=item.contract,
                start_trading_day=item.start_trading_day,
                end_trading_day=item.end_trading_day,
            )
            for item in result.resolved_contract_segments
        ],
    )


def _main_force_mirror_v2_point(point) -> MainForceMirrorV2PointOut:
    if point.physical_contract is None:
        raise MainForceMirrorV2Error("MFM_V2_PHYSICAL_CONTRACT_MISSING")
    member = point.member
    return MainForceMirrorV2PointOut(
        bar_end=point.bar_end,
        trading_day=point.trading_day,
        physical_contract=point.physical_contract,
        pressure_ready=point.pressure_ready,
        pressure_state=point.pressure_state,
        instant_pressure=_v2_number(point.instant_pressure),
        accumulated_ready=point.accumulated_ready,
        accumulated_pressure=_v2_number(point.accumulated_pressure),
        caution_ready=point.caution_ready,
        caution=point.caution,
        long_caution_score=_v2_number(point.long_caution_score),
        short_caution_score=_v2_number(point.short_caution_score),
        caution_reason_codes=list(point.caution_reason_codes),
        member_status=member.status if member is not None else "unavailable",
        member_trade_date=(member.member_trade_date if member is not None else None),
        member_direction=(member.direction if member is not None else None),
        member_change_bias=_v2_number(
            member.change_bias if member is not None else None
        ),
        member_strength=_v2_number(member.strength if member is not None else None),
        position_skew=_v2_number(
            member.position_skew if member is not None else None
        ),
        top5_volume_share=_v2_number(
            member.top5_volume_share if member is not None else None
        ),
        relation_to_accumulated=(
            member.relation_to_accumulated if member is not None else "unavailable"
        ),
        relation_to_caution=(
            member.relation_to_caution if member is not None else "unavailable"
        ),
        unavailable_reason=(
            member.unavailable_reason if member is not None else None
        ),
    )


def _v2_number(value: float | None) -> float | None:
    return (
        None
        if value is None
        else round_half_away_from_zero_binary64(float(value), 6)
    )


@router.get("/dominants", response_model=DominantContractListResponse)
def market_dominants(
    session: Session = Depends(get_db),
) -> DominantContractListResponse:
    """列出各品种最新主力合约映射（来自 MainContractMap）。"""
    items = build_market_data_service(session).list_latest_dominants()
    return DominantContractListResponse(
        items=[
            DominantContractOut(
                product=item.symbol,
                product_name=item.product_name,
                sector=item.sector,
                exchange=item.exchange,
                actual_contract=item.actual_contract,
                dominant_mapping_date=item.dominant_mapping_date,
            )
            for item in items
        ]
    )


@router.get("/research/product", response_model=ProductResearchResponse)
def product_research(
    symbol: str = Query(...),
    series_kind: str = Query(...),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ProductResearchResponse:
    """按当前图表 identity 返回只读 Product Research 快照。"""
    try:
        snapshot = build_market_research_service(session).product_snapshot(
            ResearchSeriesIdentity(
                symbol=symbol,
                series_kind=cast(SeriesKind, series_kind),
                contract=contract,
            )
        )
    except ContractError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    metrics = snapshot.metrics
    return ProductResearchResponse(
        symbol=snapshot.symbol,
        product_name=snapshot.product_name,
        sector=snapshot.sector,
        exchange=snapshot.exchange,
        series_kind=snapshot.series_kind.value,
        contract=snapshot.contract,
        as_of=snapshot.as_of,
        current_dominant=snapshot.current_dominant,
        dominant_mapping_date=snapshot.dominant_mapping_date,
        daily_trend=metrics.daily_trend,
        weekly_trend=metrics.weekly_trend,
        position20=metrics.position20,
        distance_to_20d_high=metrics.distance_to_20d_high,
        distance_to_20d_low=metrics.distance_to_20d_low,
        volume_ratio20=metrics.volume_ratio20,
        oi_change_1d=metrics.oi_change_1d,
        turnover_change_5d=metrics.turnover_change_5d,
        atr14_percentile252=metrics.atr14_percentile252,
        recent_daily=[
            MarketBarOut(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
            for bar in snapshot.recent_daily
        ],
    )


@router.get("/research/subing", response_model=SubingResearchResponse)
def subing_research(
    symbol: str = Query(...),
    frequency: str = Query(...),
    session: Session = Depends(get_db),
) -> SubingResearchResponse:
    """返回 current-rank1 SuBing Factor Observation 只读快照。"""
    try:
        request = SubingReadRequest(
            symbol=symbol,
            frequency=cast(BarFrequency, frequency),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SUBING_REQUEST"},
        ) from exc

    try:
        snapshot = build_subing_read_service(session).snapshot(
            request,
            datetime.now(UTC),
        )
    except (MarketDataError, SubingCalibrationError) as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc

    return SubingResearchResponse(
        symbol=snapshot.symbol,
        product_name=snapshot.product_name,
        frequency=snapshot.frequency.value,
        actual_contract=snapshot.actual_contract,
        dominant_mapping_date=snapshot.dominant_mapping_date,
        segment_start_trading_day=snapshot.segment_start_trading_day,
        source_mode=snapshot.source_mode,
        live_observation=snapshot.live_observation,
        live_reason=snapshot.live_reason,
        macd_policy_id=snapshot.macd_policy_id,
        signal_macd_policy_id=snapshot.signal_macd_policy_id,
        calibration_state=snapshot.calibration_state,
        calibration_id=snapshot.calibration_id,
        primary=_subing_factor_result(snapshot.primary),
        companion=(
            _subing_factor_result(snapshot.companion)
            if snapshot.companion is not None
            else None
        ),
        primary_signal=_subing_signal(snapshot.primary_signal),
        resolved_signal=(
            _subing_signal(snapshot.resolved_signal)
            if snapshot.resolved_signal is not None
            else None
        ),
        lifecycle=_subing_lifecycle(snapshot.lifecycle),
    )


@router.get("/research/radar", response_model=MarketRadarResponse)
def market_radar(session: Session = Depends(get_db)) -> MarketRadarResponse:
    """返回完整 active universe 的只读 Radar；freshness 异常显式降级。"""
    snapshot = build_market_radar_service(session).snapshot()
    items = [_radar_item(item) for item in snapshot.items]
    return MarketRadarResponse(
        status=snapshot.status,
        expected_as_of=snapshot.expected_as_of,
        target_as_of=snapshot.target_as_of,
        data_as_of=snapshot.data_as_of,
        freshness_state=snapshot.freshness_state,
        freshness_message=snapshot.freshness_message,
        active_count=snapshot.active_count,
        participant_count=snapshot.participant_count,
        stale=list(snapshot.stale),
        unavailable=list(snapshot.unavailable),
        summary=MarketRadarSummaryOut(
            up_count=sum(
                item.metrics.price_change_1d is not None
                and item.metrics.price_change_1d > 0
                for item in snapshot.items
            ),
            down_count=sum(
                item.metrics.price_change_1d is not None
                and item.metrics.price_change_1d < 0
                for item in snapshot.items
            ),
            volume_expansion_count=sum(
                "volume_expansion" in item.reason_codes for item in snapshot.items
            ),
            oi_increase_count=sum(
                "oi_increase" in item.reason_codes for item in snapshot.items
            ),
            high_volatility_count=sum(
                "high_volatility" in item.reason_codes for item in snapshot.items
            ),
        ),
        items=items,
        attention=[_radar_item(item) for item in snapshot.attention],
        sector_summary=[
            MarketRadarSectorOut(
                sector=item.sector,
                total_count=item.total_count,
                participant_count=item.participant_count,
                up_count=item.up_count,
                down_count=item.down_count,
                median_price_change_1d=item.median_price_change_1d,
                attention_count=item.attention_count,
            )
            for item in snapshot.sector_summary
        ],
    )


def _radar_item(item) -> MarketRadarItemOut:
    metrics = item.metrics
    return MarketRadarItemOut(
        symbol=item.symbol,
        product_name=item.product_name,
        sector=item.sector,
        price_change_1d=metrics.price_change_1d,
        price_change_5d=metrics.price_change_5d,
        volume_ratio20=metrics.volume_ratio20,
        oi_change_1d=metrics.oi_change_1d,
        atr14_percentile252=metrics.atr14_percentile252,
        position20=metrics.position20,
        turnover=item.turnover,
        reason_codes=list(item.reason_codes),
    )


def _subing_factor_result(result: SubingFactorResult) -> SubingFactorResultOut:
    snapshot = result.snapshot
    return SubingFactorResultOut(
        status=result.status.value,
        snapshot=(
            SubingFactorSnapshotOut(
                timeframe=snapshot.timeframe.value,
                bar_end=snapshot.bar_end,
                trading_day=snapshot.trading_day,
                contract=snapshot.contract,
                segment_start_trading_day=snapshot.segment_start_trading_day,
                bar_source=snapshot.bar_source,
                close=snapshot.close,
                ema21=snapshot.ema21,
                price_side=snapshot.price_side.value,
                slope_5_raw=snapshot.slope_5_raw,
                slope_10_raw=snapshot.slope_10_raw,
                slope_5_bps_per_bar=snapshot.slope_5_bps_per_bar,
                slope_10_bps_per_bar=snapshot.slope_10_bps_per_bar,
                macd_dif=snapshot.macd_dif,
                macd_dea=snapshot.macd_dea,
                macd_histogram=snapshot.macd_histogram,
                macd_cross=snapshot.macd_cross.value,
                macd_cross_level=snapshot.macd_cross_level,
                macd_zero_distance_abs=snapshot.macd_zero_distance_abs,
                macd_zero_distance_bps=snapshot.macd_zero_distance_bps,
                volume=snapshot.volume,
                previous_volume=snapshot.previous_volume,
                volume_ratio_prev=snapshot.volume_ratio_prev,
            )
            if snapshot is not None
            else None
        ),
    )


def _subing_signal(signal: SubingSignalEvaluation) -> SubingSignalOut:
    return SubingSignalOut(
        status=signal.status.value,
        direction=signal.direction.value,
        trigger_timeframe=(
            signal.trigger_timeframe.value
            if signal.trigger_timeframe is not None
            else None
        ),
        lower_tf_confirmation=signal.lower_tf_confirmation,
        resolution=signal.resolution.value if signal.resolution is not None else None,
        conditions=[
            SubingConditionOut(code=condition.code, state=condition.state.value)
            for condition in signal.conditions
        ],
        error_code=signal.error_code,
    )


def _subing_lifecycle(snapshot: SubingLifecycleSnapshot) -> SubingLifecycleSnapshotOut:
    """Project the immutable research snapshot without evaluating lifecycle logic."""
    pivot = snapshot.bound_reference_pivot
    transition = snapshot.latest_transition
    return SubingLifecycleSnapshotOut(
        formula_version=snapshot.formula_version,
        policy_id=snapshot.policy_id,
        research_only=snapshot.research_only,
        observed_at=snapshot.observed_at,
        anchor_bar_end=snapshot.anchor_bar_end,
        availability=snapshot.availability.value,
        unavailable_reason=snapshot.unavailable_reason,
        direction=snapshot.direction.value,
        stage=snapshot.stage.value,
        opportunity_key=_subing_opportunity_key(snapshot),
        entry_progress=(
            snapshot.entry_progress.value if snapshot.entry_progress is not None else None
        ),
        trigger_kind=snapshot.trigger_kind,
        trigger_timeframe=(
            snapshot.trigger_timeframe.value
            if snapshot.trigger_timeframe is not None
            else None
        ),
        triggered_at=snapshot.triggered_at,
        confirmation_source=(
            snapshot.confirmation_source.value
            if snapshot.confirmation_source is not None
            else None
        ),
        confirmed_at=snapshot.confirmed_at,
        hold_count=snapshot.hold_count,
        hold_required=snapshot.hold_required,
        bound_reference_pivot=(
            SubingLifecyclePivotOut(
                pivot_id=pivot.pivot_id,
                kind=pivot.kind.value,
                timeframe=pivot.source_timeframe.value,
                pivot_time=pivot.pivot_time,
                confirmed_at=pivot.confirmed_at,
                price=pivot.price,
                contract=pivot.contract,
                segment_start_trading_day=pivot.segment_start_trading_day,
            )
            if pivot is not None
            else None
        ),
        rebreak_reference_price=snapshot.rebreak_reference_price,
        retest_at=snapshot.retest_at,
        retest_rebreak_count=snapshot.retest_rebreak_count,
        volume_ratio_prev=snapshot.volume_ratio_prev,
        open_interest_delta=snapshot.open_interest_delta,
        current_risk_codes=list(snapshot.current_risk_codes),
        risk_progress=snapshot.risk_progress,
        lower_tf_risk_count=snapshot.lower_tf_risk_count,
        last_confirmed_stage=snapshot.last_confirmed_stage.value,
        last_confirmed_at=snapshot.last_confirmed_at,
        latest_transition=(
            SubingLifecycleTransitionOut(
                transition_id=transition.transition_id,
                transition_at=transition.transition_at,
                from_stage=transition.from_stage.value,
                to_stage=transition.to_stage.value,
                reason_codes=list(transition.reason_codes),
            )
            if transition is not None
            else None
        ),
        crossed_trading_day=snapshot.crossed_trading_day,
        boundary_reset=snapshot.boundary_reset,
        formal_v1_matched=snapshot.formal_v1_matched,
    )


def _subing_opportunity_key(snapshot: SubingLifecycleSnapshot) -> str | None:
    key = snapshot.opportunity_key
    if key is None:
        return None
    return ":".join(
        (
            key.policy_id,
            key.symbol,
            key.contract,
            key.segment_start_trading_day.isoformat(),
            key.direction.value,
            key.origin_at.isoformat(),
        )
    )
