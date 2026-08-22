from datetime import date, datetime

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
