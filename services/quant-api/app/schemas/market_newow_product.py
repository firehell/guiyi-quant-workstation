"""Typed wire models for the sectioned Newow product endpoint."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductFeatureStatusOut(_Out):
    status: Literal[
        "ready", "warming", "unavailable", "not_applicable", "evidence_required"
    ]
    evidence_status: Literal[
        "ACTIVE_CODE_VERIFIED",
        "RESEARCH_EVIDENCE_ONLY",
        "EVIDENCE_REQUIRED",
        "OUT_OF_SCOPE",
    ]
    reason_code: str | None


class ProductIdentityOut(_Out):
    product: str
    strategy: Literal["trend", "oscillation", "main_rise"]
    frequency: Literal["1w", "1d", "60m"]
    series_kind: Literal["actual_dominant"]
    profile_id: str
    formula_versions: list[str]


class ProductMetaOut(_Out):
    schema_version: Literal["newow_product_detail_v1"]
    identity: ProductIdentityOut
    as_of: datetime
    read_at: datetime
    input_content_sha256: str
    data_revision_identity: str | None
    snapshot_token: str | None
    reference_model_version: str
    futures_adaptation_version: str


class ProductBarOut(_Out):
    bar_end: datetime
    trading_day: date
    open: str
    high: str
    low: str
    close: str
    volume: int
    open_interest: int | None
    physical_contract: str
    segment_id: str
    source_identity: str
    observation_eligible: bool
    completed: Literal[True]


class ProductActionOut(_Out):
    signal_id: str
    kind: Literal["BUILD", "CLEAR"]
    bar_end: datetime
    trading_day: date
    reference_price: str
    physical_contract: str
    segment_id: str
    related_build_id: str | None
    trade_eligibility: str


class ProductHintOut(_Out):
    hint_id: str
    kind: str
    bar_end: datetime
    known_at: datetime
    anchor_price: str | None
    physical_contract: str
    segment_id: str
    retrospective: Literal[False]
    quantity_effect: Literal["none"]


class ProductFrameOut(_Out):
    bar_end: datetime
    main_state: str
    main_values: dict[str, str | None]
    status: ProductFeatureStatusOut
    action_ids: list[str]
    hint_ids: list[str]


class ChartValueOut(_Out):
    bars: list[ProductBarOut]
    frames: list[ProductFrameOut]
    actions: list[ProductActionOut]
    hints: list[ProductHintOut]
    diagnostics: list[str]
    next_before: str | None
    repainting: bool
    formal_signal_eligible: bool
    allowed_uses: list[str]


class ReferenceTradeOut(_Out):
    reference_trade_id: str
    product: str
    strategy_code: str
    frequency: str
    physical_contract: str
    segment_id: str
    formula_versions: list[str]
    reference_model_version: str
    futures_adaptation_version: str
    entry_signal_id: str
    entry_bar_end: datetime
    entry_trading_day: date
    entry_reference_price: str
    exit_signal_id: str | None
    exit_bar_end: datetime | None
    exit_trading_day: date | None
    exit_reference_price: str | None
    status: str
    holding_bars: int
    reference_return_pct: str | None
    mark_bar_end: datetime | None
    mark_reference_price: str | None
    mark_change_pct: str | None
    interrupted_at: datetime | None
    interruption_reason: str | None
    statistics_membership: str | None
    hint_ids: list[str]


class ReferenceSummaryOut(_Out):
    membership_policy: str
    closed_count: int
    win_count: int
    loss_count: int
    flat_count: int
    win_rate_pct: str | None
    mean_return_pct: str | None
    sum_return_percentage_points: str | None
    open_count: int
    interrupted_count: int
    initial_count: int


class ReferenceValueOut(_Out):
    performance_since: date
    performance_through: date
    actual_available_through: date
    reference_cutoff: datetime
    reference_input_sha256: str
    summary: ReferenceSummaryOut
    items: list[ReferenceTradeOut]
    next_before: str | None
    executable: Literal[False]
    auto_order: Literal[False]
    allowed_uses: list[str]


class SourceFactOut(_Out):
    role: str
    source_category: str
    adapter_version: str
    frequency: str | None
    bar_end: datetime | None
    physical_contract: str | None
    segment_id: str | None
    as_of: datetime
    dependency_sha256: str | None
    status: str
    reason_code: str | None


class AuxiliarySegmentOut(_Out):
    physical_contract: str
    segment_id: str
    bar_ends: list[datetime]
    status: ProductFeatureStatusOut
    data: JsonValue | None


class AuxiliaryValueOut(_Out):
    component: Literal[
        "main_force_control", "up_down_energy", "zhaoyao_mirror", "cup_handle"
    ]
    formula_version: str
    segments: list[AuxiliarySegmentOut]
    repainting: bool
    formal_signal_eligible: bool
    page_parity: bool
    source_category: str
    allowed_uses: list[str]


class ExplanationValueOut(_Out):
    context: JsonValue
    composite: JsonValue
    target_absorb: JsonValue
    sources: list[SourceFactOut]
    page_parity: Literal[False]
    allowed_uses: list[str]


class ComparatorValueOut(_Out):
    result: JsonValue | None
    executable: Literal[False]
    page_parity: Literal[False]
    synthetic_terminal_is_reference_exit: Literal[False]
    allowed_uses: list[str]


class ChartDeliveryOut(_Out):
    delivery: Literal["delivered", "not_requested"]
    status: ProductFeatureStatusOut | None
    value: ChartValueOut | None


class AuxiliaryDeliveryOut(_Out):
    delivery: Literal["delivered", "not_requested"]
    status: ProductFeatureStatusOut | None
    value: AuxiliaryValueOut | None


class ReferenceDeliveryOut(_Out):
    delivery: Literal["delivered", "not_requested"]
    status: ProductFeatureStatusOut | None
    value: ReferenceValueOut | None


class ExplanationDeliveryOut(_Out):
    delivery: Literal["delivered", "not_requested"]
    status: ProductFeatureStatusOut | None
    value: ExplanationValueOut | None


class ComparatorDeliveryOut(_Out):
    delivery: Literal["delivered", "not_requested"]
    status: ProductFeatureStatusOut | None
    value: ComparatorValueOut | None


class NewowProductResponse(_Out):
    meta: ProductMetaOut
    section: Literal["chart", "auxiliary", "reference", "explanation", "comparator"]
    chart: ChartDeliveryOut
    auxiliary: AuxiliaryDeliveryOut
    reference: ReferenceDeliveryOut
    explanation: ExplanationDeliveryOut
    comparator: ComparatorDeliveryOut
