from datetime import date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import data_center as repo
from app.schemas.data_center import (
    ContractOut,
    CoverageOut,
    CoveragePageOut,
    DataCenterSummaryOut,
    DataDownloadTaskOut,
    DataDownloadTaskPageOut,
    DataProfileOut,
    DataQualityReportOut,
    DataQualityReportPageOut,
    DataSourceOut,
    ExchangeOut,
    InstrumentOut,
    ProfileActiveBindingOut,
    SymbolOut,
)
from app.services.data_profile_registry import DataProfileRegistry

router = APIRouter(prefix="/api/v1/data", tags=["data-center"])
compat_router = APIRouter(tags=["compat"])


def _coverage_row(market_file, bindings_by_file_id: dict, *, include_paths: bool) -> CoverageOut:
    bindings = bindings_by_file_id.get(market_file.id, [])
    return CoverageOut(
        id=market_file.id,
        provider=market_file.provider,
        data_type=market_file.data_type,
        instrument_symbol=market_file.instrument_symbol,
        contract_code=market_file.contract_code,
        period=market_file.period,
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        row_count=market_file.row_count,
        file_path=market_file.file_path if include_paths else None,
        quality_status=market_file.quality_status,
        data_version=market_file.data_version,
        data_role=market_file.data_role,
        updated_at=market_file.updated_at,
        active_profile_ids=sorted({binding.profile_id for binding in bindings}),
        binding_status=bindings[0].binding_status if bindings else None,
    )


@router.get("/summary", response_model=DataCenterSummaryOut)
def get_summary(session: Session = Depends(get_db)) -> DataCenterSummaryOut:
    registry = DataProfileRegistry(session)
    return DataCenterSummaryOut(
        source_count=len(repo.list_sources(session)),
        exchange_count=len(repo.list_exchanges(session)),
        instrument_count=len(repo.list_instruments(session)),
        contract_count=len(repo.list_contracts(session)),
        coverage_count=repo.count_coverage(session),
        task_count=repo.count_download_tasks(session),
        quality_count=repo.count_quality_reports(session),
        active_profile_count=len([p for p in registry.list_profiles() if p.is_active]),
    )


@router.get("/sources", response_model=list[DataSourceOut])
def get_sources(session: Session = Depends(get_db)) -> list:
    return repo.list_sources(session)


@router.get("/exchanges", response_model=list[ExchangeOut])
def get_exchanges(session: Session = Depends(get_db)) -> list:
    return repo.list_exchanges(session)


@router.get("/instruments", response_model=list[InstrumentOut])
def get_instruments(session: Session = Depends(get_db)) -> list:
    return repo.list_instruments(session)


@router.get("/contracts", response_model=list[ContractOut])
def get_contracts(session: Session = Depends(get_db)) -> list:
    return repo.list_contracts(session)


@router.get("/download-tasks", response_model=list[DataDownloadTaskOut] | DataDownloadTaskPageOut)
def get_download_tasks(
    session: Session = Depends(get_db),
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    symbol: str | None = Query(None),
    contract: str | None = Query(None),
    period: str | None = Query(None),
    provider: str | None = Query(None),
    status: str | None = Query(None),
) -> list | DataDownloadTaskPageOut:
    if not paged:
        return repo.list_download_tasks(session)
    filters = {
        "symbol": symbol,
        "contract": contract,
        "period": period,
        "provider": provider,
        "status": status,
    }
    items = repo.list_download_tasks_page(
        session,
        limit=limit,
        offset=offset,
        symbol=symbol,
        contract=contract,
        period=period,
        provider=provider,
        status=status,
    )
    return DataDownloadTaskPageOut(
        items=items,
        total=repo.count_download_tasks(
            session, symbol=symbol, contract=contract, period=period, provider=provider, status=status
        ),
        limit=limit,
        offset=offset,
        filters={k: v for k, v in filters.items() if v},
    )


@router.get("/quality-reports", response_model=list[DataQualityReportOut] | DataQualityReportPageOut)
def get_quality_reports(
    session: Session = Depends(get_db),
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    symbol: str | None = Query(None),
    contract: str | None = Query(None),
    period: str | None = Query(None),
    quality: str | None = Query(None),
    provider: str | None = Query(None),
) -> list | DataQualityReportPageOut:
    if not paged:
        return repo.list_quality_reports(session)
    filters = {
        "symbol": symbol,
        "contract": contract,
        "period": period,
        "quality": quality,
        "provider": provider,
    }
    items = repo.list_quality_reports_page(
        session,
        limit=limit,
        offset=offset,
        symbol=symbol,
        contract=contract,
        period=period,
        quality=quality,
        provider=provider,
    )
    return DataQualityReportPageOut(
        items=items,
        total=repo.count_quality_reports(
            session, symbol=symbol, contract=contract, period=period, quality=quality, provider=provider
        ),
        limit=limit,
        offset=offset,
        filters={k: v for k, v in filters.items() if v},
    )


@router.get("/coverage", response_model=list[CoverageOut] | CoveragePageOut)
def get_coverage(
    session: Session = Depends(get_db),
    paged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    symbol: str | None = Query(None),
    contract: str | None = Query(None),
    period: str | None = Query(None),
    quality: str | None = Query(None),
    provider: str | None = Query(None),
    binding_status: Literal["active", "unbound"] | None = Query(None),
    include_paths: bool = Query(False),
) -> list[CoverageOut] | CoveragePageOut:
    registry = DataProfileRegistry(session)

    if not paged:
        bindings_by_file_id = registry.active_bindings_by_file_id()

        def matches_binding(market_file) -> bool:
            if not binding_status:
                return True
            bindings = bindings_by_file_id.get(market_file.id, [])
            if binding_status == "unbound":
                return not bindings
            return any(b.binding_status == binding_status for b in bindings)

        return [
            _coverage_row(market_file, bindings_by_file_id, include_paths=include_paths)
            for market_file in repo.list_coverage(session)
            if matches_binding(market_file)
        ]

    filters = {
        "symbol": symbol,
        "contract": contract,
        "period": period,
        "quality": quality,
        "provider": provider,
        "binding_status": binding_status,
    }
    total = repo.count_coverage(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        quality=quality,
        provider=provider,
        binding_status=binding_status,
    )
    page_files = repo.list_coverage_page(
        session,
        limit=limit,
        offset=offset,
        symbol=symbol,
        contract=contract,
        period=period,
        quality=quality,
        provider=provider,
        binding_status=binding_status,
    )
    bindings_by_file_id = registry.active_bindings_by_file_id([market_file.id for market_file in page_files])

    return CoveragePageOut(
        items=[
            _coverage_row(market_file, bindings_by_file_id, include_paths=include_paths)
            for market_file in page_files
        ],
        total=total,
        limit=limit,
        offset=offset,
        filters={k: v for k, v in filters.items() if v},
    )


@router.get("/profiles", response_model=list[DataProfileOut])
def get_profiles(session: Session = Depends(get_db)) -> list:
    registry = DataProfileRegistry(session)
    return [
        DataProfileOut(
            profile_id=profile.profile_id,
            label=profile.label,
            description=profile.description,
            contract_roles=list(profile.contract_roles or []),
            periods=list(profile.periods or []),
            quality_policy=profile.quality_policy,
            provider=profile.provider,
            is_active=profile.is_active,
            config_path=profile.config_path,
        )
        for profile in registry.list_profiles()
    ]


@router.get("/profiles/{profile_id}/active-versions", response_model=list[ProfileActiveBindingOut])
def get_profile_active_versions(profile_id: str, session: Session = Depends(get_db)) -> list:
    del profile_id, session
    raise HTTPException(status_code=410, detail={"code": "PROFILE_ACTIVE_SELECTOR_RETIRED"})


@compat_router.get("/api/symbols", response_model=list[SymbolOut])
def get_symbols(session: Session = Depends(get_db)) -> list[SymbolOut]:
    contracts = repo.list_contracts(session)
    return [
        SymbolOut(
            symbol=contract.contract_code,
            name=contract.name or contract.contract_code,
            exchange=contract.exchange_code,
        )
        for contract in contracts
    ]


@compat_router.get("/api/klines")
def get_klines(
    symbol: str = Query(...),
    contract: str = Query(...),
    period: str = Query(...),
    start: str | None = None,
    end: str | None = None,
    provider: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> list[dict]:
    del symbol, contract, period, start, end, provider, limit, session
    raise HTTPException(status_code=410, detail={"code": "LEGACY_KLINE_ROUTE_RETIRED"})


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
