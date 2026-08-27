from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


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
    bar_count_1m: int
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
    effective_open_at: datetime | None
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


class SubingStrategyPendingSummaryOut(BaseModel):
    kind: Literal["open_long", "open_short", "close_long", "close_short"]
    decision_at: datetime
    opportunity_id: str
    reason_codes: list[str]


class SubingStrategyCurrentContextOut(BaseModel):
    symbol: str
    target_trading_day: date
    source_trading_day: date | None
    direction: Literal["long_only", "short_only", "no_new_entry", "unavailable"]
    reason_codes: list[str]
    daily_bar_end: datetime | None
    hourly_bar_end: datetime | None
    physical_contract: str | None


class SubingStrategyCurrentResponse(BaseModel):
    strategy_id: Literal["subing_strategy_v1"]
    formula_version: Literal["subing_strategy_15m_v1"]
    series_kind: Literal["actual_dominant"]
    symbol: str
    frequency: Literal["15m"]
    contract: str
    segment_start_trading_day: date
    source_mode: Literal["canonical", "canonical_live"]
    cutoff: datetime
    position_state: Literal["flat", "long", "short"]
    pending_action: SubingStrategyPendingSummaryOut | None
    current_episode: SubingStrategyEpisodeOut | None
    latest_completed_episode: SubingStrategyEpisodeOut | None
    direction_context: SubingStrategyCurrentContextOut
