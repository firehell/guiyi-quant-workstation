from datetime import date, datetime, time, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_core.contracts import (
    BAR_FREQUENCY_VALUES,
    BarFrequency,
    BarQuery,
    ContractValidationError,
    DataCoreError,
    DatasetKind,
    UnsupportedFrequencyError,
    parse_bar_frequency,
)
from app.db.session import get_db
from app.models.data_center import Contract
from app.schemas.market import (
    CanonicalBarsResponse,
    CanonicalMarketIndicatorsResponse,
    CanonicalMarketMacdIndicatorResponse,
    DominantContractListResponse,
    MarketCoverageSummary,
    MarketWorkbenchCoverage,
    SymbolOut,
)
from app.services.canonical_market_data import (
    CanonicalMarketDataService,
    build_canonical_reader as _canonical_reader,
    get_canonical_coverage,
)
from app.services.market_dominant_reader import DominantContractReader
from app.services.market_indicators import (
    get_canonical_market_indicators,
    get_canonical_market_macd_indicator,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])
compat_router = APIRouter(tags=["compat"])


@compat_router.get("/api/symbols", response_model=list[SymbolOut])
def get_symbols(session: Session = Depends(get_db)) -> list[SymbolOut]:
    """Compat contract list for Market Web; not a Profile/Binding selector."""
    contracts = list(
        session.scalars(
            select(Contract).order_by(
                Contract.exchange_code,
                Contract.instrument_symbol,
                Contract.contract_code,
            )
        )
    )
    return [
        SymbolOut(
            symbol=contract.contract_code,
            name=contract.name or contract.contract_code,
            exchange=contract.exchange_code,
        )
        for contract in contracts
    ]


def _historical_frequency(frequency: str = Query(...)) -> BarFrequency:
    try:
        return parse_bar_frequency(frequency)
    except UnsupportedFrequencyError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_FREQUENCY",
                "facts": {
                    "field": "frequency",
                    "value": str(frequency),
                    "allowed": BAR_FREQUENCY_VALUES,
                },
            },
        ) from exc


@router.get("/bars/canonical", response_model=CanonicalBarsResponse)
def canonical_market_bars(
    dataset_kind: DatasetKind = Query(...),
    symbol: str = Query(...),
    frequency: BarFrequency = Depends(_historical_frequency),
    start: str = Query(...),
    end: str = Query(...),
    contract_or_series: str | None = None,
    session: Session = Depends(get_db),
) -> CanonicalBarsResponse:
    """JM historical V2: explicit identity/window, no Profile or tail fallback."""
    try:
        query = BarQuery(
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
            frequency=frequency,
            start=_parse_rfc3339_datetime(start),
            end=_parse_rfc3339_datetime(end),
        )
        return CanonicalMarketDataService(
            session,
            reader=_canonical_reader(session),
        ).get_bars(query)
    except ContractValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except DataCoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc


@router.get(
    "/indicators/canonical",
    response_model=CanonicalMarketIndicatorsResponse,
)
def canonical_market_indicators(
    dataset_kind: DatasetKind = Query(...),
    symbol: str = Query(...),
    frequency: BarFrequency = Depends(_historical_frequency),
    start: str = Query(...),
    end: str = Query(...),
    contract_or_series: str | None = None,
    indicator_codes: str = Query(default="ema21"),
    display_bar_count: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> CanonicalMarketIndicatorsResponse:
    try:
        display_start = _parse_rfc3339_datetime(start)
        display_end = _parse_rfc3339_datetime(end)
        requested_codes = [item.strip() for item in indicator_codes.split(",") if item.strip()]
        warmup_bars = max(
            ({"ema10": 9, "ema21": 20, "ema60": 59}.get(item, 0) for item in requested_codes),
            default=0,
        )
        service = CanonicalMarketDataService(
            session,
            reader=_canonical_reader(session),
        )
        bars_response = _canonical_bars_with_effective_warmup(
            service,
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
            frequency=frequency,
            display_start=display_start,
            display_end=display_end,
            warmup_bars=warmup_bars,
        )
        return get_canonical_market_indicators(
            bars_response,
            indicator_codes=requested_codes,
            display_bar_count=display_bar_count,
            display_start=display_start,
            display_end=display_end,
        )
    except ContractValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except DataCoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc


@router.get(
    "/indicators/macd/canonical",
    response_model=CanonicalMarketMacdIndicatorResponse,
)
def canonical_market_macd_indicator(
    dataset_kind: DatasetKind = Query(...),
    symbol: str = Query(...),
    frequency: BarFrequency = Depends(_historical_frequency),
    start: str = Query(...),
    end: str = Query(...),
    contract_or_series: str | None = None,
    session: Session = Depends(get_db),
) -> CanonicalMarketMacdIndicatorResponse:
    try:
        query = BarQuery(
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
            frequency=frequency,
            start=_parse_rfc3339_datetime(start),
            end=_parse_rfc3339_datetime(end),
        )
        bars_response = CanonicalMarketDataService(
            session,
            reader=_canonical_reader(session),
        ).get_bars(query)
        return get_canonical_market_macd_indicator(bars_response)
    except ContractValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except DataCoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc


@router.get(
    "/coverage/canonical",
    response_model=MarketWorkbenchCoverage,
)
def canonical_market_coverage(
    symbol: str = Query(default="jm"),
    session: Session = Depends(get_db),
) -> MarketWorkbenchCoverage:
    try:
        return get_canonical_coverage(session, symbol=symbol)
    except DataCoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc


@router.get("/workbench/coverage", response_model=Union[MarketWorkbenchCoverage, MarketCoverageSummary])
def market_workbench_coverage(
    symbol: str = Query(default="jm"),
    session: Session = Depends(get_db),
) -> MarketWorkbenchCoverage:
    try:
        return get_canonical_coverage(session, symbol=symbol)
    except DataCoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc


@router.get("/dominants", response_model=DominantContractListResponse)
def market_dominants(
    exchange: str | None = None,
    quote_ready: bool | None = None,
    search: str | None = None,
    symbol: str | None = None,
    session: Session = Depends(get_db),
) -> DominantContractListResponse:
    return DominantContractReader(session).list_dominants(
        exchange=exchange,
        quote_ready=quote_ready,
        search=search,
        symbol=symbol,
    )


def _parse_query_datetime(value: str, end_of_day: bool) -> datetime:
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid datetime: {value}") from exc
    return parsed.replace(tzinfo=None)


def _parse_rfc3339_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(
            facts={"field": "datetime", "reason": "rfc3339_required"}
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(
            facts={"field": "datetime", "reason": "timezone_required"}
        )
    return parsed


def _frequency_delta(frequency: BarFrequency) -> timedelta:
    return {
        BarFrequency.M1: timedelta(minutes=1),
        BarFrequency.M5: timedelta(minutes=5),
        BarFrequency.M15: timedelta(minutes=15),
        BarFrequency.M30: timedelta(minutes=30),
        BarFrequency.H1: timedelta(hours=1),
        BarFrequency.D1: timedelta(days=1),
        BarFrequency.W1: timedelta(days=7),
    }[frequency]


def _canonical_bars_with_effective_warmup(
    service: CanonicalMarketDataService,
    *,
    dataset_kind: DatasetKind,
    symbol: str,
    contract_or_series: str | None,
    frequency: BarFrequency,
    display_start: datetime,
    display_end: datetime,
    warmup_bars: int,
):
    attempts = 1 if warmup_bars == 0 else 16
    response = None
    for attempt in range(attempts):
        span = _frequency_delta(frequency) * max(1, warmup_bars) * (2**attempt)
        query = BarQuery(
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
            frequency=frequency,
            start=display_start - span,
            end=display_end,
        )
        response = service.get_bars(query)
        prior_count = sum(
            _parse_rfc3339_datetime(str(bar["time"])) < display_start
            for bar in response.bars
        )
        if prior_count >= warmup_bars:
            return response
    raise ContractValidationError(
        facts={
            "field": "warmup_bars",
            "reason": "effective_trading_bars_missing",
            "required": warmup_bars,
        }
    )
