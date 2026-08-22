from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class SubingHistoricalSignalRequestOut(BaseModel):
    series_kind: str
    symbol: str
    frequency: str
    since: date
    through: date


class SubingHistoricalSignalEventOut(BaseModel):
    event_id: str
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    direction: str
    trigger_timeframe: str
    lower_tf_confirmation: bool


class SubingHistoricalSignalResponse(BaseModel):
    request: SubingHistoricalSignalRequestOut
    events: list[SubingHistoricalSignalEventOut]


class NStructureHistoricalRequestOut(BaseModel):
    series_kind: str
    symbol: str
    frequency: str
    since: date
    through: date


class NStructureHistoricalEventOut(BaseModel):
    event_id: str
    observed_at: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    direction: str


class NStructureHistoricalResponse(BaseModel):
    request: NStructureHistoricalRequestOut
    events: list[NStructureHistoricalEventOut]


class JdjHistoricalRequestOut(BaseModel):
    series_kind: str
    symbol: str
    frequency: str
    since: date
    through: date


class JdjHistoricalEventOut(BaseModel):
    event_id: str
    candidate_id: str
    source_event_kind: str
    observed_at: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    direction: str
    trigger_level: Decimal


class JdjHistoricalResponse(BaseModel):
    request: JdjHistoricalRequestOut
    events: list[JdjHistoricalEventOut]
