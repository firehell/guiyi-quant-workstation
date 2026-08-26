from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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


class SubingStrategyHistoricalRequestOut(BaseModel):
    series_kind: str
    symbol: str
    frequency: str
    since: date
    through: date


class SubingStrategyPolicyOut(BaseModel):
    strategy_id: str
    formula_version: str
    research_only: bool
    series_kind: str
    decision_frequency: str
    lifecycle_policy_id: str
    allowed_confirmation_sources: list[str]


class SubingStrategySegmentSummaryOut(BaseModel):
    contract: str
    start_trading_day: date
    end_trading_day: date
    loaded_through: date
    bar_count_5m: int
    bar_count_15m: int
    initial_position: str
    final_position: str
    terminal_bar_end: datetime | None
    pending_action: bool


class SubingStrategyBoundPivotOut(BaseModel):
    pivot_id: str
    kind: str
    source_timeframe: str
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date


class SubingStrategyActionOut(BaseModel):
    action_id: str
    episode_id: str
    strategy_id: str
    formula_version: str
    kind: str
    symbol: str
    contract: str
    trading_day: date
    segment_start_trading_day: date
    opportunity_id: str
    decision_at: datetime
    effective_bar_end: datetime
    reference_price: Decimal
    fill_basis: str
    confirmation_source: str | None
    reason_codes: list[str]
    direction_context_source_day: date | None
    direction_context_target_day: date | None
    bound_reference_pivot: SubingStrategyBoundPivotOut | None


class SubingStrategyEpisodeOut(BaseModel):
    episode_id: str
    direction: str
    entry_action: SubingStrategyActionOut
    exit_action: SubingStrategyActionOut | None
    state: str
    holding_bar_count: int
    reference_change_percent: Decimal | None
    current_reference_change_percent: Decimal | None
    latest_reference_price: Decimal | None
    exit_reason_codes: list[str]
    structure_exit_available: bool


class SubingStrategyContextUnavailableOut(BaseModel):
    symbol: str
    target_trading_day: date
    source_trading_day: date | None
    direction: str
    reason_codes: list[str]
    daily_bar_end: datetime | None
    hourly_bar_end: datetime | None
    physical_contract: str | None


class SubingStrategyHistoricalResponse(BaseModel):
    request: SubingStrategyHistoricalRequestOut
    policy: SubingStrategyPolicyOut
    resolved_cutoff: datetime
    segment_summaries: list[SubingStrategySegmentSummaryOut]
    actions: list[SubingStrategyActionOut]
    episodes: list[SubingStrategyEpisodeOut]
    context_unavailable: list[SubingStrategyContextUnavailableOut]
    cache_state: Literal["hit", "miss", "mixed", "unavailable"]


class NStructureBandRequestOut(BaseModel):
    series_kind: str
    symbol: str
    frequency: str
    since: date
    through: date


class NStructureBandPolicyOut(BaseModel):
    policy_id: str
    formula_version: str
    source_timeframe: str
    research_only: bool


class NStructureBandOut(BaseModel):
    band_id: str
    contract: str
    segment_start_trading_day: date
    completion_trading_day: date
    direction: str
    role: str
    n1_at: datetime
    completed_at: datetime
    completion_level: Decimal
    lower: Decimal
    upper: Decimal
    first_reentered_at: datetime | None
    invalidated_at: datetime | None
    expanded_until: datetime


class NStructureBandResponse(BaseModel):
    request: NStructureBandRequestOut
    policy: NStructureBandPolicyOut
    bands: list[NStructureBandOut]


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
