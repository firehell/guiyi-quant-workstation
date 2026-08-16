"""Strict HTTP contracts for the Execution Review application domain."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


DatabaseDecimal = Annotated[
    Decimal,
    Field(
        gt=Decimal("0"),
        allow_inf_nan=False,
        max_digits=24,
        decimal_places=8,
    ),
]
PositiveQuantity = Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]
PositiveDatabaseId = Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotExecutedRequest(StrictRequest):
    primary_reason: str
    secondary_reasons: list[str] = []
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    note: str | None = None


class ExecutedRequest(StrictRequest):
    executed_at: datetime
    price: DatabaseDecimal
    quantity: PositiveQuantity
    execution_reason_tags: list[str]
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    planned_stop_price: DatabaseDecimal | None = None
    stop_basis: str | None = None
    note: str | None = None


class ExecutionCreateRequest(StrictRequest):
    execution_type: Literal["ADD", "REDUCE", "CLOSE"]
    executed_at: datetime
    price: DatabaseDecimal
    quantity: PositiveQuantity
    note: str | None = None


class ExecutionUpdateRequest(StrictRequest):
    executed_at: datetime
    price: DatabaseDecimal
    note: str | None = None


class TimelineExecutionRequest(StrictRequest):
    execution_id: PositiveDatabaseId | None = None
    execution_type: Literal["OPEN", "ADD", "REDUCE", "CLOSE"]
    executed_at: datetime
    price: DatabaseDecimal
    quantity: PositiveQuantity
    note: str | None = None


class TimelineReplaceRequest(StrictRequest):
    items: list[TimelineExecutionRequest]


class DecisionUpdateRequest(StrictRequest):
    first_viewed_at: datetime | None
    decided_at: datetime
    primary_not_execute_reason: str | None
    secondary_not_execute_reasons: list[str]
    note: str | None
    execution_reason_tags: list[str]
    planned_stop_price: DatabaseDecimal | None
    stop_basis: str | None


class DispositionCorrectionRequest(StrictRequest):
    target_disposition: Literal["EXECUTED", "NOT_EXECUTED"]
    primary_reason: str | None = None
    secondary_reasons: list[str] = []
    execution_reason_tags: list[str] = []
    executed_at: datetime | None = None
    price: DatabaseDecimal | None = None
    quantity: PositiveQuantity | None = None
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    planned_stop_price: DatabaseDecimal | None = None
    stop_basis: str | None = None
    note: str | None = None


class ReviewRequest(StrictRequest):
    signal_execution_adherence: str
    entry_tags: list[str]
    holding_tags: list[str]
    exit_tags: list[str]
    market_context_tags: list[str]
    psychology_tags: list[str]
    summary: str | None = None


class DecisionOut(BaseModel):
    id: int
    alert_event_id: int
    disposition: str
    first_viewed_at: datetime | None
    decided_at: datetime
    primary_not_execute_reason: str | None
    secondary_not_execute_reasons: list[str]
    note: str | None
    execution_reason_tags: list[str]
    planned_stop_price: Decimal | None
    stop_basis: str | None


class EpisodeOut(BaseModel):
    id: int
    origin_decision_id: int
    symbol: str
    contract: str
    direction: str
    opened_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    roll_reference_exit_price: Decimal | None
    roll_reference_bar_end: datetime | None
    contract_multiplier_snapshot: Decimal | None
    multiplier_policy_id: str | None


class ExecutionOut(BaseModel):
    id: int
    episode_id: int
    trigger_decision_id: int | None
    sequence_no: int
    execution_type: str
    executed_at: datetime
    price: Decimal
    quantity: int
    note: str | None


class ReviewOut(BaseModel):
    id: int
    episode_id: int
    signal_execution_adherence: str
    entry_tags: list[str]
    holding_tags: list[str]
    exit_tags: list[str]
    market_context_tags: list[str]
    psychology_tags: list[str]
    summary: str | None
    submitted_at: datetime
    updated_at: datetime


class PositionOut(BaseModel):
    remaining_quantity: int
    average_cost: Decimal | None
    realized_points: Decimal
    estimated_gross_pnl: Decimal | None


class ExecutedResponse(BaseModel):
    decision: DecisionOut
    episode: EpisodeOut
    execution: ExecutionOut
    position: PositionOut


class ExecutionResponse(BaseModel):
    episode: EpisodeOut
    execution: ExecutionOut
    position: PositionOut


class TimelineResponse(BaseModel):
    episode: EpisodeOut
    executions: list[ExecutionOut]
    position: PositionOut


class DispositionCorrectionResponse(BaseModel):
    decision: DecisionOut
    episode: EpisodeOut | None
    execution: ExecutionOut | None
    position: PositionOut | None


class ReviewItemOut(BaseModel):
    item_kind: str
    state: str
    event_id: int
    decision_id: int | None
    episode_id: int | None
    symbol: str
    contract: str
    direction: str
    trading_day: date


class ReviewItemsResponse(BaseModel):
    items: list[ReviewItemOut]


class EventStateOut(BaseModel):
    event_id: int
    state: str
    decision_id: int | None
    episode_id: int | None


class EventStatesResponse(BaseModel):
    items: list[EventStateOut]


class EventContextOut(BaseModel):
    id: int
    rule_code: str
    symbol: str
    contract: str
    trading_day: date
    frequency: str
    bar_end: datetime
    result_codes: list[str]
    lower_tf_confirmation: bool
    detected_at: datetime
    notification_attempted_at: datetime | None


class EpisodeDetailResponse(BaseModel):
    episode: EpisodeOut
    origin_event: EventContextOut
    decisions: list[DecisionOut]
    executions: list[ExecutionOut]
    review: ReviewOut | None
    position: PositionOut


class OpportunityStatsOut(BaseModel):
    eligible_events: int
    processed_events: int
    pending_events: int
    executed_decisions: int
    not_executed_decisions: int
    decision_completion_rate: Decimal | None
    execution_rate: Decimal | None
    primary_reason_counts: dict[str, int]


class EpisodeStateStatsOut(BaseModel):
    open_episodes: int
    pending_review_episodes: int
    done_episodes: int


class ReviewIssueStatsOut(BaseModel):
    entry: dict[str, int]
    holding: dict[str, int]
    exit_risk: dict[str, int]
    psychology: dict[str, int]


class ExecutionReviewStatsResponse(BaseModel):
    opportunities: OpportunityStatsOut
    episode_states: EpisodeStateStatsOut
    review_issue_top: ReviewIssueStatsOut
