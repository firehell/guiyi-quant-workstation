"""Safe read-only wire contract for Newow actual-dominant D1 detail."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewowMetaOut(_Out):
    strategy_code: str
    profile_id: str
    frequency: str
    series_kind: str
    calculation_identity: str
    data_revision_identity: str | None
    request_identity: str


class NewowInstrumentOut(_Out):
    product: str
    display_name: str | None
    last_visible_physical_contract: str | None


class NewowBarOut(_Out):
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int | None
    physical_contract: str
    segment_id: str
    source_identity: str


class NewowTrendBandOut(_Out):
    bar_end: datetime
    b_value: float | None
    c_value: float | None
    state: str
    state_before: str | None
    transition: str | None


class NewowMarkerOut(_Out):
    marker_id: str
    marker_type: str
    bar_end: datetime
    price: Decimal
    label: str
    color_token: str
    priority: int
    related_marker_ids: tuple[str, ...]
    trigger_facts: dict[str, object]
    formula_version: str


class NewowCupPivotOut(_Out):
    pivot_at: datetime
    confirmed_at: datetime
    price: Decimal


class NewowCupHandleOut(_Out):
    candidate_id: str
    direction: str
    state: str
    left_rim: NewowCupPivotOut
    bottom: NewowCupPivotOut
    right_rim: NewowCupPivotOut
    handle_start_at: datetime
    handle_extreme: NewowCupPivotOut | None
    pivot_price: Decimal | None
    pivot_frozen_at: datetime | None
    confirmed_at: datetime
    first_seen_at: datetime
    state_changed_at: datetime
    score: float
    score_breakdown: dict[str, float]
    hard_failures: list[str]
    diagnostics: list[str]
    volume_facts: dict[str, float]
    formula_version: str


class NewowRolloverSeamOut(_Out):
    trading_day: date
    previous_contract: str
    next_contract: str
    previous_bar_end: datetime
    next_bar_end: datetime
    previous_segment_id: str
    next_segment_id: str


class NewowTrendDetailResponse(_Out):
    meta: NewowMetaOut
    instrument: NewowInstrumentOut
    bars: list[NewowBarOut]
    bar_policy: Literal["completed_only"]
    trend_band: list[NewowTrendBandOut]
    trend_markers: list[NewowMarkerOut]
    escape_markers: list[NewowMarkerOut]
    cup_markers: list[NewowMarkerOut]
    cup_handles: list[NewowCupHandleOut]
    rollover_seams: list[NewowRolloverSeamOut]
    legend: dict[str, str]
    formula_descriptions: dict[str, str]
    warnings: list[str]
