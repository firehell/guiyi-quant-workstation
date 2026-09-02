"""Read-only Market API backed by the canonical MarketDataService."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_market_data_service,
    build_market_home_projection,
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
    MarketHomeOverviewResponse,
    MarketPageMetaOut,
    ProductResearchResponse,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/research/home-overview", response_model=MarketHomeOverviewResponse)
def market_home_overview(
    session: Session = Depends(get_db),
) -> MarketHomeOverviewResponse:
    try:
        return build_market_home_projection(session).read()
    except MarketHomeOverviewError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc


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
