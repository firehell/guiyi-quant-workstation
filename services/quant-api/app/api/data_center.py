from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import data_center as repo
from app.schemas.data_center import (
    ContractOut,
    CoverageOut,
    DataDownloadTaskOut,
    DataProfileOut,
    DataQualityReportOut,
    DataSourceOut,
    ExchangeOut,
    InstrumentOut,
    ProfileActiveBindingOut,
    SymbolOut,
)
from app.services.data_profile_registry import DataProfileRegistry
from app.services.market_data_reader import MarketDataReader

router = APIRouter(prefix="/api/v1/data", tags=["data-center"])
compat_router = APIRouter(tags=["compat"])


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


@router.get("/download-tasks", response_model=list[DataDownloadTaskOut])
def get_download_tasks(session: Session = Depends(get_db)) -> list:
    return repo.list_download_tasks(session)


@router.get("/quality-reports", response_model=list[DataQualityReportOut])
def get_quality_reports(session: Session = Depends(get_db)) -> list:
    return repo.list_quality_reports(session)


@router.get("/coverage", response_model=list[CoverageOut])
def get_coverage(session: Session = Depends(get_db)) -> list:
    registry = DataProfileRegistry(session)
    bindings_by_file_id = registry.active_bindings_by_file_id()
    rows = []
    for market_file in repo.list_coverage(session):
        bindings = bindings_by_file_id.get(market_file.id, [])
        rows.append(
            CoverageOut(
                id=market_file.id,
                provider=market_file.provider,
                data_type=market_file.data_type,
                instrument_symbol=market_file.instrument_symbol,
                contract_code=market_file.contract_code,
                period=market_file.period,
                start_time=market_file.start_time,
                end_time=market_file.end_time,
                row_count=market_file.row_count,
                file_path=market_file.file_path,
                quality_status=market_file.quality_status,
                data_version=market_file.data_version,
                data_role=market_file.data_role,
                updated_at=market_file.updated_at,
                active_profile_ids=sorted({binding.profile_id for binding in bindings}),
                binding_status=bindings[0].binding_status if bindings else None,
            )
        )
    return rows


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
    registry = DataProfileRegistry(session)
    if registry.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail=f"profile not found: {profile_id}")
    return [
        ProfileActiveBindingOut(
            profile_id=binding.profile_id,
            instrument_symbol=binding.instrument_symbol,
            contract_code=binding.contract_code,
            contract_role=binding.contract_role,
            period=binding.period,
            data_version=binding.data_version,
            market_data_file_id=binding.market_data_file_id,
            binding_status=binding.binding_status,
            activated_at=binding.activated_at,
            superseded_at=binding.superseded_at,
            updated_at=binding.updated_at,
        )
        for binding in registry.list_active_bindings(profile_id)
    ]


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
    start_time = _parse_query_datetime(start, end_of_day=False) if start else datetime.min
    end_time = _parse_query_datetime(end, end_of_day=True) if end else datetime.max
    return MarketDataReader(session).load_bars(
        symbol=symbol,
        contract=contract,
        period=period,
        start=start_time,
        end=end_time,
        provider=provider,
        limit=limit,
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
