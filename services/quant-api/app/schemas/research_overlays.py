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


class JdjStrategyHistoricalRequestOut(BaseModel):
    series_kind: str
    symbol: str
    frequency: str
    since: date
    through: date


class JdjStrategyHistoricalActionOut(BaseModel):
    event_id: str
    episode_id: str | None
    kind: str
    source_event_ids: list[str]
    primary_setup: str | None
    supporting_setups: list[str]
    direction: str | None
    contract: str
    trading_day: date
    segment_start_trading_day: date
    decision_at: datetime
    effective_bar_end: datetime | None
    reference_price: Decimal | None
    quantity: int
    position_quantity_after: int
    stop_price: Decimal | None
    target_price: Decimal | None
    reward_risk: Decimal | None
    reason: str
    fill_basis: str | None


class JdjStrategyHistoricalResponse(BaseModel):
    request: JdjStrategyHistoricalRequestOut
    reference_execution: bool
    actions: list[JdjStrategyHistoricalActionOut]
