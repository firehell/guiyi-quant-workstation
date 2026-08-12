"""Market 行情只读 HTTP API。

所有数据经 ``MarketDataService`` 查询 Canonical Parquet 与八表 Catalog；消费者不得
绕过完整性校验。合同类错误映射为 422，数据可用性/冲突类错误映射为 409。
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_market_data_service,
    build_market_radar_service,
    build_market_research_service,
)
from app.market_data.domain import (
    BarFrequency,
    ContractError,
    SeriesKind,
    SeriesPageQuery,
    parse_rfc3339_instant,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.market_research_service import ResearchSeriesIdentity
from app.schemas.market import (
    ContractSegmentOut,
    CoverageOut,
    DominantContractListResponse,
    DominantContractOut,
    MarketBarOut,
    MarketBarsPageResponse,
    MarketPageMetaOut,
    MarketRadarItemOut,
    MarketRadarResponse,
    MarketRadarSectorOut,
    MarketRadarSummaryOut,
    ProductResearchResponse,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])


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


@router.get("/dominants", response_model=DominantContractListResponse)
def market_dominants(session: Session = Depends(get_db)) -> DominantContractListResponse:
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


@router.get("/research/radar", response_model=MarketRadarResponse)
def market_radar(session: Session = Depends(get_db)) -> MarketRadarResponse:
    """返回完整 active universe 的只读 Radar；freshness 异常显式降级。"""
    snapshot = build_market_radar_service(session).snapshot()
    items = [_radar_item(item) for item in snapshot.items]
    return MarketRadarResponse(
        status=snapshot.status,
        expected_as_of=snapshot.expected_as_of,
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
