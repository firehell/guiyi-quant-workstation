"""Typed wire models for the sectioned Newow product endpoint."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    sequence: int


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
    sequence: int | None


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
    formula_versions: list[str]
    frequency: str | None
    bar_end: datetime | None
    physical_contract: str | None
    segment_id: str | None
    as_of: datetime
    dependency_sha256: str | None
    status: str
    reason_code: str | None


class MainForceControlDataOut(_Out):
    kongpan: list[float]
    status: list[str]
    current_status: str
    formula_version: str


class ZhaoyaoMirrorDataOut(_Out):
    entry: list[float]
    wash: list[float]
    distribution: list[float]
    markup: list[float]
    exit: list[float]
    inducement: list[float]
    peaks: list[int]
    caution: list[int]
    repainting: Literal[True]
    formal_signal_eligible: Literal[False]
    formula_version: str


class UpDownEnergyDataOut(_Out):
    var4: list[float | None]
    ma10: list[float]
    band_entry: list[int]
    rebound_entry: list[int]
    oversold_entry: list[int]
    var3: list[float]
    ma120: list[float]
    formula_version: str


class CupPivotValueOut(_Out):
    kind: str
    price: str
    pivot_at: datetime
    confirmed_at: datetime
    pivot_index: int
    confirmed_index: int
    atr_at_pivot: float


class CupWitnessOut(_Out):
    witness_id: str
    candidate_id: str
    left_rim: CupPivotValueOut
    bottom: CupPivotValueOut
    right_rim: CupPivotValueOut
    handle_extreme: CupPivotValueOut
    pivot_price: str
    confirmed_at: datetime
    score: float
    score_breakdown: list[tuple[str, float]]
    volume_facts: list[tuple[str, float]]
    right_leg_median_exact: str
    handle_median_exact: str
    handle_baseline_median_exact: str
    profile_identity: str
    formula_version: str


AuxiliaryDataOut = (
    MainForceControlDataOut
    | ZhaoyaoMirrorDataOut
    | UpDownEnergyDataOut
    | list[CupWitnessOut]
)


class AuxiliarySegmentOut(_Out):
    physical_contract: str
    segment_id: str
    bar_ends: list[datetime]
    status: ProductFeatureStatusOut
    data: AuxiliaryDataOut | None


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


class ContextSlotOut(_Out):
    frequency: Literal["1w", "1d", "60m"]
    as_of: datetime
    availability: ProductFeatureStatusOut
    confirmation_status: ProductFeatureStatusOut
    identity: ProductIdentityOut | None
    bar_end: datetime | None
    source_identity: str | None
    physical_contract: str | None
    segment_id: str | None
    formula_versions: list[str]
    main_state: str | None


class ContextSnapshotOut(_Out):
    as_of: datetime
    weekly: ContextSlotOut
    daily: ContextSlotOut
    hourly: ContextSlotOut
    missing_frequencies: list[str]
    recompute_mode: str
    historical_database_knowledge_reconstructed: Literal[False]


class SourceBarsOut(_Out):
    usage: str
    fact_names: list[str]
    frequency: str
    physical_contract: str | None
    segment_id: str | None
    source_identities: list[str]
    count: int
    first_bar_end: datetime | None
    last_bar_end: datetime | None
    first_trading_day: date | None
    last_trading_day: date | None
    as_of: datetime
    in_sample: bool
    repainting: bool
    repaint_status: ProductFeatureStatusOut
    input_status: ProductFeatureStatusOut


class CompositeInputFactOut(_Out):
    role: str
    value: str
    frequency: str
    bar_end: datetime
    physical_contract: str
    segment_id: str


class CompositeDecisionOut(_Out):
    source_key: str
    selected_key: str
    label: str
    position_range: str
    fallback_used: bool
    warning_branches_unreachable: bool
    position_is_target: bool
    position_is_hand_count: bool
    formula_version: str


class CompositeDirectionOut(_Out):
    token: str
    certainty_points: int
    formula_version: str


class CertaintyBreakdownOut(_Out):
    trend: int
    oscillation: int
    alignment: int
    direction: int
    uncapped_total: int
    total: int
    cap: int | None
    is_probability: Literal[False]
    is_win_rate: Literal[False]
    formula_version: str


class CompositeVolatilityOut(_Out):
    value_pct: str
    level: str
    true_range_count: int
    method: str
    is_wilder_atr: Literal[False]
    formula_version: str


class FirstActionOut(_Out):
    rule_token: str
    level: str
    page_title: str
    page_detail: str
    token_owner: str
    token_is_page_native: Literal[False]
    page_formula_version: str


class WeekDayMatrixOut(_Out):
    key: str
    name: str
    risk: str
    position: str
    formula_version: str


class SubfeatureOut(_Out):
    name: str
    status: ProductFeatureStatusOut
    value: (
        str
        | CompositeDecisionOut
        | CompositeDirectionOut
        | CertaintyBreakdownOut
        | CompositeVolatilityOut
        | FirstActionOut
        | WeekDayMatrixOut
        | None
    )


class CompositeValueOut(_Out):
    decision: CompositeDecisionOut
    direction: CompositeDirectionOut
    certainty: CertaintyBreakdownOut
    volatility: CompositeVolatilityOut | None
    first_action: FirstActionOut
    week_day_matrix: WeekDayMatrixOut
    subfeatures: list[SubfeatureOut]
    input_facts: list[CompositeInputFactOut]
    warning_branches_unreachable: bool
    diagnostic_tokens: None
    ai_copy: None
    six_combo_ranking: None
    evidence_manifest_sha256: str
    page_source_sha256: str
    reachability_sha256: str
    ai_template_evidence_sha256: str
    frozen_results_sha256: str


class CompositeResultOut(_Out):
    status: str
    evidence_status: str
    reason_code: str | None
    as_of: datetime
    formula_versions: list[str]
    source_bars: list[SourceBarsOut]
    value: CompositeValueOut | None


class PageFactOut(_Out):
    value: str | bool
    frequency: str
    bar_end: datetime
    physical_contract: str
    segment_id: str


class TargetDisplayPriceOut(_Out):
    raw_value: str
    display_value: str
    branch: str
    source_frequency: str
    bar_end: datetime
    physical_contract: str
    segment_id: str


class TargetSubfeatureOut(_Out):
    name: str
    status: ProductFeatureStatusOut
    value: str | None


class TargetAbsorbValueOut(_Out):
    target: TargetDisplayPriceOut
    absorb: TargetDisplayPriceOut
    previous_close: None
    display_surface: str
    subfeatures: list[TargetSubfeatureOut]
    evidence_manifest_sha256: str
    inherited_frozen_results_sha256: str


class TargetAbsorbResultOut(_Out):
    status: str
    evidence_status: str
    reason_code: str | None
    as_of: datetime
    display_surface: str | None
    formula_versions: list[str]
    source_bars: list[PageFactOut]
    decision_facts: list[PageFactOut]
    value: TargetAbsorbValueOut | None


class ExplanationValueOut(_Out):
    context: ContextSnapshotOut
    composite: CompositeResultOut
    target_absorb: TargetAbsorbResultOut
    sources: list[SourceFactOut]
    page_parity: Literal[False]
    allowed_uses: list[str]


class ComparatorTradeOut(_Out):
    entry_bar_end: datetime
    entry_price: str
    exit_bar_end: datetime
    exit_price: str
    return_pct: str
    won: bool
    synthetic_terminal: bool


class ComparatorDisplayOut(_Out):
    cumulative_return_pct: str
    max_drawdown_pct: str
    win_rate_pct: str


class WindowComparisonOut(_Out):
    window: int
    cumulative_return_pct: str
    max_drawdown_pct: str
    trade_count: int
    win_count: int
    loss_count: int
    win_rate_pct: str
    force_closed_at_end: bool
    score: str
    page_display: ComparatorDisplayOut
    trades: list[ComparatorTradeOut]


class ComparatorSourceBarsOut(_Out):
    count: int
    first_trading_day: date | None
    last_trading_day: date | None
    first_bar_end: datetime | None
    last_bar_end: datetime | None
    source_identities: list[str]
    snapshot_kind: str
    fact_identity_fields: list[str]


class ComparatorSegmentOut(_Out):
    physical_contract: str
    segment_id: str
    frequency: str
    authoritative_start_trading_day: date
    authoritative_end_trading_day: date
    source_bars: ComparatorSourceBarsOut
    as_of: datetime
    in_sample: bool
    repainting: bool
    repaint_status: ProductFeatureStatusOut
    input_snapshot_status: ProductFeatureStatusOut
    status: ProductFeatureStatusOut
    results: list[WindowComparisonOut]
    ranked_windows: list[int]


class ComparatorProductValueOut(_Out):
    segments: list[ComparatorSegmentOut]
    default_segment_id: str | None
    candidate_windows: list[int]
    page_formula_version: str
    futures_adapter_version: str
    page_source_kernel_page_parity: Literal[True]
    futures_adapter_page_parity: Literal[False]
    in_sample: Literal[True]
    executable: Literal[False]
    input_mode: str
    subfeatures: list[SubfeatureOut]


class ComparatorResultOut(_Out):
    identity: ProductIdentityOut
    status: str
    evidence_status: str
    reason_code: str | None
    as_of: datetime
    formula_versions: list[str]
    source_bars: list[ComparatorSourceBarsOut]
    value: ComparatorProductValueOut | None


class ComparatorValueOut(_Out):
    result: ComparatorResultOut | None
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
