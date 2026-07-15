from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    status: str
    priority: int
    remark: str | None = None


class ExchangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    country: str
    timezone: str
    is_active: bool


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    exchange_code: str
    sector: str | None = None
    category: str | None = None
    is_active: bool


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_code: str
    instrument_symbol: str
    exchange_code: str
    name: str | None = None
    contract_month: str | None = None
    listed_date: date | None = None
    expired_date: date | None = None
    status: str
    raw_symbol: str | None = None
    provider: str | None = None


class DataDownloadTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_no: str
    provider: str
    data_type: str
    instrument_symbol: str | None = None
    contract_code: str | None = None
    period: str | None = None
    start_time: datetime
    end_time: datetime
    status: str
    progress: Decimal
    error_message: str | None = None
    result: dict[str, Any]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DataQualityReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    data_type: str
    instrument_symbol: str | None = None
    contract_code: str | None = None
    period: str | None = None
    start_time: datetime
    end_time: datetime
    status: str
    missing_bars: int
    duplicated_bars: int
    abnormal_price_count: int
    abnormal_volume_count: int
    details: dict[str, Any]
    created_at: datetime


class CoverageOut(BaseModel):
    id: int
    provider: str
    data_type: str
    instrument_symbol: str | None = None
    contract_code: str | None = None
    period: str | None = None
    start_time: datetime
    end_time: datetime
    row_count: int | None = None
    file_path: str
    quality_status: str
    data_version: str | None = None
    data_role: str = "candidate"
    updated_at: datetime | None = None
    active_profile_ids: list[str] = []
    binding_status: str | None = None


class DataProfileOut(BaseModel):
    profile_id: str
    label: str
    description: str
    contract_roles: list[str]
    periods: list[str]
    quality_policy: str
    provider: str
    is_active: bool
    config_path: str | None = None


class ProfileActiveBindingOut(BaseModel):
    profile_id: str
    instrument_symbol: str
    contract_code: str
    contract_role: str
    period: str
    data_version: str
    market_data_file_id: int | None = None
    binding_status: str
    activated_at: datetime
    superseded_at: datetime | None = None
    updated_at: datetime | None = None


class SymbolOut(BaseModel):
    symbol: str
    name: str
    exchange: str
    productType: str = "futures"
    multiplier: int | None = None
    marginRatio: float | None = None
    tickSize: float | None = None
    tradingHours: str | None = None
