from datetime import date, datetime, time, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    ContractValidationError,
    DataCoreError,
    DatasetKind,
)
from app.db.session import get_db
from app.schemas.market import (
    CanonicalBarsResponse,
    CanonicalMarketIndicatorsResponse,
    CanonicalMarketMacdIndicatorResponse,
    DominantContractListResponse,
    LiveMarketBarsResponse,
    LiveTargetContractsResponse,
    MarketIndicatorsResponse,
    MarketMacdIndicatorResponse,
    MarketBarsResponse,
    MarketCoverageSummary,
    MarketWorkbenchCoverage,
)
from app.services.live_market_reader import LiveMarketReader, SUPPORTED_LIVE_PERIODS
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.active_dataset import (
    ActiveDatasetDomainError,
    DatasetRequest,
    validate_dataset_request,
)
from app.services.market_data_service import MarketDataService
from app.services.canonical_market_data import (
    CanonicalMarketDataService,
    build_canonical_reader as _canonical_reader,
    get_canonical_coverage,
)
from app.services.market_dominant_reader import DominantContractReader, QuoteContractError
from app.services.market_indicators import (
    get_canonical_market_indicators,
    get_canonical_market_macd_indicator,
    get_market_indicators,
)
from app.services.market_workbench import (
    MARKET_ACCESS_MODES,
    MarketAccessError,
    WEB_MACD_LEGACY_V1_POLICY,
    get_market_bars,
    get_market_macd_indicator,
    get_workbench_coverage,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/bars/canonical", response_model=CanonicalBarsResponse)
def canonical_market_bars(
    dataset_kind: DatasetKind = Query(...),
    symbol: str = Query(...),
    frequency: BarFrequency = Query(...),
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
    frequency: BarFrequency = Query(...),
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
        query = BarQuery(
            dataset_kind=dataset_kind,
            symbol=symbol,
            contract_or_series=contract_or_series,
            frequency=frequency,
            start=display_start - _frequency_delta(frequency) * warmup_bars,
            end=display_end,
        )
        bars_response = CanonicalMarketDataService(
            session,
            reader=_canonical_reader(session),
        ).get_bars(query)
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
    frequency: BarFrequency = Query(...),
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
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    include_paths: bool = False,
    summary: bool = False,
    profile_id: str | None = None,
    access_mode: str = Query(default="browser"),
    session: Session = Depends(get_db),
) -> MarketWorkbenchCoverage | MarketCoverageSummary:
    _validate_access_mode(access_mode)
    try:
        return get_workbench_coverage(
            session,
            symbol=symbol,
            contract=contract,
            period=period,
            include_paths=include_paths,
            summary=summary,
            profile_id=profile_id,
            access_mode=access_mode,
        )
    except MarketAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


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


@router.get("/live/targets", response_model=LiveTargetContractsResponse)
def live_market_targets(
    trade_date: date | None = None,
    required_date: date | None = None,
    session: Session = Depends(get_db),
) -> dict:
    return LiveTargetContractResolver(session).list_targets(
        trade_date=trade_date,
        required_date=required_date,
    )


@router.get("/live/coverage", response_model=Union[MarketWorkbenchCoverage, MarketCoverageSummary])
def live_market_coverage(
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    include_paths: bool = False,
    summary: bool = False,
    session: Session = Depends(get_db),
) -> MarketWorkbenchCoverage | MarketCoverageSummary:
    return LiveMarketReader(session).get_coverage(
        symbol=symbol,
        contract=contract,
        period=period,
        include_paths=include_paths,
        summary=summary,
    )


@router.get("/live/bars", response_model=LiveMarketBarsResponse)
def live_market_bars(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    source_mode: str | None = None,
    limit: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> LiveMarketBarsResponse:
    if period not in SUPPORTED_LIVE_PERIODS:
        raise HTTPException(status_code=422, detail=f"unsupported live market period: {period}")
    return LiveMarketReader(session).get_bars(
        symbol=symbol,
        contract=contract,
        period=period,
        start=_parse_query_datetime(start, end_of_day=False) if start else None,
        end=_parse_query_datetime(end, end_of_day=True) if end else None,
        provider=provider,
        source_mode=source_mode,
        limit=limit,
    )


@router.get("/bars", response_model=MarketBarsResponse)
def market_bars(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    data_role: str | None = None,
    profile_id: str | None = None,
    access_mode: str = Query(default="browser"),
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
    quote_mode: bool = Query(default=False),
    allow_continuous: bool = Query(default=False),
    tail: bool = Query(default=True),
    limit: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> MarketBarsResponse:
    _validate_access_mode(access_mode)
    if not _is_canonical_jm_historical_shape(
        symbol=symbol,
        contract=contract,
        period=period,
    ):
        try:
            return get_market_bars(
                session,
                symbol=symbol,
                contract=contract,
                period=period,
                start=_parse_query_datetime(start, end_of_day=False) if start else None,
                end=_parse_query_datetime(end, end_of_day=True) if end else None,
                provider=provider,
                data_role=data_role,
                profile_id=profile_id,
                access_mode=access_mode,
                expected_market_data_file_id=expected_market_data_file_id,
                expected_lineage_token=expected_lineage_token,
                limit=limit,
                quote_mode=quote_mode,
                allow_continuous=allow_continuous,
                tail=tail,
            )
        except MarketAccessError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
        except QuoteContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        market_data_service = MarketDataService(session)
        result = market_data_service.get_bars(
            DatasetRequest(
                data_context="historical",
                symbol=symbol,
                contract_selector="explicit",
                contract=contract,
                period=period,
                access_mode=access_mode,
                profile_id=profile_id,
                provider=provider,
                data_role=data_role,
                expected_market_data_file_id=expected_market_data_file_id,
                expected_lineage_token=expected_lineage_token,
                quote_mode=quote_mode,
                allow_continuous=allow_continuous,
            ),
            start=_parse_query_datetime(start, end_of_day=False) if start else None,
            end=_parse_query_datetime(end, end_of_day=True) if end else None,
            limit=limit,
            tail=tail,
        )
        return market_data_service.to_market_bars_response(result)
    except ActiveDatasetDomainError as exc:
        error_detail = _market_facade_error_detail(
            exc,
            symbol=symbol,
            contract=contract,
            period=period,
            profile_id=profile_id,
        )
        if error_detail is None:
            raise
        status_code, detail = error_detail
        raise HTTPException(
            status_code=status_code,
            detail=detail,
        ) from exc
    except MarketAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except QuoteContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/indicators", response_model=MarketIndicatorsResponse)
def market_indicators(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    indicator_codes: str = Query(default="ema21"),
    display_start: str | None = None,
    display_end: str | None = None,
    display_bar_count: int = Query(default=10000, ge=1, le=10000),
    provider: str | None = None,
    data_role: str | None = None,
    profile_id: str | None = None,
    access_mode: str = Query(default="browser"),
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
    quote_mode: bool = Query(default=False),
    allow_continuous: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> MarketIndicatorsResponse:
    _validate_access_mode(access_mode)
    try:
        return get_market_indicators(
            session,
            symbol=symbol,
            contract=contract,
            period=period,
            indicator_codes=[indicator_codes],
            display_start=_parse_query_datetime(display_start, end_of_day=False) if display_start else None,
            display_end=_parse_query_datetime(display_end, end_of_day=True) if display_end else None,
            display_bar_count=display_bar_count,
            provider=provider,
            data_role=data_role,
            profile_id=profile_id,
            access_mode=access_mode,
            expected_market_data_file_id=expected_market_data_file_id,
            expected_lineage_token=expected_lineage_token,
            quote_mode=quote_mode,
            allow_continuous=allow_continuous,
        )
    except MarketAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/indicators/macd", response_model=MarketMacdIndicatorResponse)
def market_macd_indicator(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    data_role: str | None = None,
    profile_id: str | None = None,
    access_mode: str = Query(default="browser"),
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
    policy: str = Query(default=WEB_MACD_LEGACY_V1_POLICY),
    quote_mode: bool = Query(default=False),
    allow_continuous: bool = Query(default=False),
    tail: bool = Query(default=True),
    limit: int = Query(default=10000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> MarketMacdIndicatorResponse:
    _validate_access_mode(access_mode)
    if policy != WEB_MACD_LEGACY_V1_POLICY:
        raise HTTPException(status_code=422, detail=f"unsupported MACD policy: {policy}")
    try:
        return get_market_macd_indicator(
            session,
            symbol=symbol,
            contract=contract,
            period=period,
            start=_parse_query_datetime(start, end_of_day=False) if start else None,
            end=_parse_query_datetime(end, end_of_day=True) if end else None,
            provider=provider,
            data_role=data_role,
            profile_id=profile_id,
            access_mode=access_mode,
            expected_market_data_file_id=expected_market_data_file_id,
            expected_lineage_token=expected_lineage_token,
            limit=limit,
            quote_mode=quote_mode,
            allow_continuous=allow_continuous,
            tail=tail,
        )
    except MarketAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except QuoteContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


def _market_facade_error_detail(
    exc: ActiveDatasetDomainError,
    *,
    symbol: str,
    contract: str,
    period: str,
    profile_id: str | None,
) -> tuple[int, dict[str, object]] | None:
    mapping = {
        "DATASET_ASSET_MISSING": (
            "MARKET_PROFILE_FILE_MISSING",
            "market Profile physical file is missing",
            422,
        ),
        "DATASET_ASSET_AMBIGUOUS": (
            "MARKET_PROFILE_IDENTITY_MISMATCH",
            "market Profile asset identity does not match the request",
            422,
        ),
        "DATASET_LINEAGE_CHANGED": (
            "MARKET_LINEAGE_CHANGED",
            "market lineage changed after the bars snapshot",
            409,
        ),
    }
    mapped = mapping.get(exc.code)
    if mapped is None:
        return None
    public_code, message, status_code = mapped
    return status_code, {
        "code": public_code,
        "message": message,
        "context": {
            "profile_id": profile_id,
            "symbol": symbol,
            "contract": contract,
            "period": period,
        },
    }


def _is_canonical_jm_historical_shape(
    *,
    symbol: str,
    contract: str,
    period: str,
) -> bool:
    request = DatasetRequest(
        data_context="historical",
        symbol=symbol,
        contract_selector="explicit",
        contract=contract,
        period=period,
        access_mode="browser",
    )
    try:
        normalized = validate_dataset_request(request)
    except ActiveDatasetDomainError:
        return False
    return (
        normalized.symbol == symbol
        and normalized.contract == contract
        and normalized.period == period
    )


def _validate_access_mode(access_mode: str) -> None:
    if access_mode not in MARKET_ACCESS_MODES:
        raise HTTPException(
            status_code=422,
            detail={"code": "MARKET_ACCESS_MODE_INVALID", "message": "unsupported market access mode", "context": {"access_mode": access_mode}},
        )
