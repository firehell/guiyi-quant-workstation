"""Read-only Market API backed by the canonical MarketDataService."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_market_data_service,
    build_market_home_overview_service,
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
from app.market_data.market_home_overview import MarketHomeOverviewError
from app.market_data.market_research_service import ResearchSeriesIdentity
from app.schemas.market import (
    ContractSegmentOut,
    CoverageOut,
    DominantContractListResponse,
    DominantContractOut,
    MarketBarOut,
    MarketBarsPageResponse,
    MarketHomeItemOut,
    MarketHomeOverviewResponse,
    MarketHomeSectorOut,
    MarketHomeSummaryOut,
    MarketPageMetaOut,
    ProductResearchResponse,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/research/home-overview", response_model=MarketHomeOverviewResponse)
def market_home_overview(
    session: Session = Depends(get_db),
) -> MarketHomeOverviewResponse:
    try:
        snapshot = build_market_home_overview_service(session).snapshot()
    except MarketHomeOverviewError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    return MarketHomeOverviewResponse(
        status=snapshot.status,
        target_as_of=snapshot.target_as_of,
        data_as_of=snapshot.data_as_of,
        freshness=snapshot.freshness,
        active_count=snapshot.active_count,
        participant_count=snapshot.participant_count,
        stale_count=snapshot.stale_count,
        unavailable_count=snapshot.unavailable_count,
        summary=MarketHomeSummaryOut(
            price_up_count=snapshot.summary.price_up_count,
            price_down_count=snapshot.summary.price_down_count,
            price_flat_count=snapshot.summary.price_flat_count,
            daily_up_count=snapshot.summary.daily_up_count,
            daily_down_count=snapshot.summary.daily_down_count,
            daily_neutral_count=snapshot.summary.daily_neutral_count,
            daily_unavailable_count=snapshot.summary.daily_unavailable_count,
            aligned_up_count=snapshot.summary.aligned_up_count,
            aligned_down_count=snapshot.summary.aligned_down_count,
        ),
        items=[
            MarketHomeItemOut(
                symbol=item.symbol,
                product_name=item.product_name,
                sector=item.sector,
                exchange=item.exchange,
                actual_contract=item.actual_contract,
                dominant_mapping_date=item.dominant_mapping_date,
                data_as_of=item.data_as_of,
                close=item.close,
                price_change_1d=item.price_change_1d,
                price_change_5d=item.price_change_5d,
                volume_ratio20=item.volume_ratio20,
                oi_change_1d=item.oi_change_1d,
                atr14_percentile252=item.atr14_percentile252,
                daily_trend=item.daily_trend,
                weekly_trend=item.weekly_trend,
                reason_codes=list(item.reason_codes),
            )
            for item in snapshot.items
        ],
        sectors=[
            MarketHomeSectorOut(
                sector=sector.sector,
                active_count=sector.active_count,
                participant_count=sector.participant_count,
                median_price_change_1d=sector.median_price_change_1d,
            )
            for sector in snapshot.sectors
        ],
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
            CoverageOut(start=result.canonical_coverage[0], end=result.canonical_coverage[1])
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
