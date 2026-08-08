from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import build_market_data_service
from app.market_data.domain import BarFrequency, ContractError, SeriesKind, SeriesQuery
from app.market_data.service import MarketDataError
from app.models import Instrument, MainContractMap, MarketDataset, MarketPartition
from app.schemas.market import (
    ContractSegmentOut,
    CoverageOut,
    DatasetCoverageOut,
    DominantContractListResponse,
    DominantContractOut,
    MarketBarOut,
    MarketBarsResponse,
    MarketCoverageResponse,
)


router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/bars/canonical", response_model=MarketBarsResponse)
def canonical_market_bars(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MarketBarsResponse:
    try:
        request = SeriesQuery(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            contract=contract,
            frequency=cast(BarFrequency, frequency),
            start=_instant(start),
            end=_instant(end),
        )
        result = build_market_data_service(session).query(request)
    except ContractError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    return MarketBarsResponse(
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
        coverage=(
            CoverageOut(start=result.coverage[0], end=result.coverage[1])
            if result.coverage
            else None
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
    mappings = session.scalars(
        select(MainContractMap).order_by(
            MainContractMap.symbol,
            MainContractMap.trade_date.desc(),
        )
    )
    latest: dict[str, MainContractMap] = {}
    for row in mappings:
        latest.setdefault(row.symbol, row)
    instruments = {
        row.symbol: row for row in session.scalars(select(Instrument))
    }
    return DominantContractListResponse(
        items=[
            DominantContractOut(
                product=symbol,
                product_name=instruments[symbol].name if symbol in instruments else symbol.upper(),
                exchange=(
                    instruments[symbol].exchange_code if symbol in instruments else ""
                ),
                actual_contract=row.contract_code,
                dominant_mapping_date=row.trade_date,
            )
            for symbol, row in sorted(latest.items())
        ]
    )


@router.get("/coverage/canonical", response_model=MarketCoverageResponse)
def canonical_market_coverage(
    symbol: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MarketCoverageResponse:
    query = select(MarketDataset)
    if symbol:
        query = query.where(MarketDataset.symbol == symbol.strip().lower())
    items = []
    for dataset in session.scalars(query.order_by(MarketDataset.symbol, MarketDataset.frequency)):
        partitions = tuple(
            session.scalars(
                select(MarketPartition)
                .where(MarketPartition.dataset_id == dataset.id)
                .order_by(MarketPartition.year, MarketPartition.month)
            )
        )
        if not partitions:
            continue
        items.append(
            DatasetCoverageOut(
                kind=dataset.kind,
                symbol=dataset.symbol,
                series_or_contract=dataset.series_or_contract,
                frequency=dataset.frequency,
                start=partitions[0].coverage_start,
                end=partitions[-1].coverage_end,
                row_count=sum(item.row_count for item in partitions),
                partition_count=len(partitions),
            )
        )
    return MarketCoverageResponse(items=items)


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(field="datetime", reason="rfc3339_required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(field="datetime", reason="timezone_required")
    return parsed
