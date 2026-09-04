"""Safe read-only wire contract for Newow actual-dominant D1 detail."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

NewowProfileId = Literal["newow_trend_d1_page_v2"]
NewowFrequency = Literal["1d"]
NewowSeriesKind = Literal["actual_dominant"]
NewowTrendStateBefore = Literal["YELLOW", "BLUE"]
NewowMarkerFormula = Literal[
    "newow_trend_band_page_v2",
    "newow_escape_d123_page_v2",
    "newow_cup_handle_v1",
]
NewowCupState = Literal[
    "FORMING", "READY", "BREAKOUT", "WEAKENED", "INVALIDATED", "EXPIRED"
]
NewowCupFormula = Literal["newow_cup_handle_v1"]
NewowDiagnosticFactsFormula = Literal[
    "newow_diagnostic_facts_cleanroom_v1",
    "newow_target_absorb_display_selection_page_v2",
    "newow_trend_band_page_v2",
    "newow_oscillation_hhv_llv10_page_v1",
    "newow_main_force_control_page_v1",
    "newow_main_rise_ma35_ma45_page_v1",
    "newow_cup_handle_v1",
]
NewowDiagnosticTokenFormula = Literal[
    "newow_diagnostic_rules_cleanroom_v1",
    "newow_diagnostic_facts_cleanroom_v1",
    "newow_target_absorb_display_selection_page_v2",
    "newow_trend_band_page_v2",
    "newow_oscillation_hhv_llv10_page_v1",
    "newow_main_force_control_page_v1",
    "newow_main_rise_ma35_ma45_page_v1",
    "newow_cup_handle_v1",
    "newow_ai_week_day_16_matrix_page_v1",
]
NewowRepaintingFormula = Literal["newow_zhaoyao_mirror_repainting_page_v1"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewowMetaOut(_Out):
    strategy_code: Literal["newow_trend_v1"]
    profile_id: NewowProfileId
    frequency: NewowFrequency
    series_kind: NewowSeriesKind
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
    state: Literal["UNAVAILABLE", "YELLOW", "BLUE"]
    state_before: NewowTrendStateBefore | None
    transition: Literal["BUILD", "CLEAR"] | None


class NewowMarkerOut(_Out):
    marker_id: str
    marker_type: Literal[
        "BUILD",
        "CLEAR",
        "NEWOW_ESCAPE_D1",
        "NEWOW_ESCAPE_D2",
        "NEWOW_ESCAPE_D3",
        "CUP_HANDLE_READY",
        "CUP_HANDLE_BREAKOUT",
        "CUP_HANDLE_WEAKENED",
        "CUP_HANDLE_INVALIDATED",
        "CUP_HANDLE_EXPIRED",
    ]
    bar_end: datetime
    price: Decimal
    label: str
    color_token: str
    priority: int
    related_marker_ids: tuple[str, ...]
    trigger_facts: dict[str, object]
    formula_version: NewowMarkerFormula


class NewowCupPivotOut(_Out):
    pivot_at: datetime
    confirmed_at: datetime
    price: Decimal


class NewowCupHandleOut(_Out):
    candidate_id: str
    direction: Literal["BULLISH", "BEARISH"]
    state: NewowCupState
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
    formula_version: NewowCupFormula


class NewowRolloverSeamOut(_Out):
    trading_day: date
    previous_contract: str
    next_contract: str
    previous_bar_end: datetime
    next_bar_end: datetime
    previous_segment_id: str
    next_segment_id: str


class NewowPriceChannelPointOut(_Out):
    bar_end: datetime
    target: Decimal | None
    absorb: Decimal | None
    window: int
    available: bool
    formula_version: Literal["newow_target_absorb_hhv_llv10_page_v1"]


class NewowFrequencyPriceChannelOut(_Out):
    frequency: Literal["1d", "1w", "60m"]
    points: list[NewowPriceChannelPointOut]
    owner_segment_ids: list[str]
    formula_version: Literal["newow_target_absorb_hhv_llv10_page_v1"]


class NewowDisplayPriceOut(_Out):
    target: Decimal | None
    absorb: Decimal | None
    raw_target: Decimal | None
    raw_absorb: Decimal | None
    target_period: Literal["day", "week", "best_available"] | None
    absorb_period: Literal["day", "week", "best_available"] | None
    target_branch_token: str
    absorb_branch_token: str
    formula_version: Literal["newow_target_absorb_display_selection_page_v2"]


class NewowPriceChannelOut(_Out):
    daily: NewowFrequencyPriceChannelOut
    weekly: NewowFrequencyPriceChannelOut
    sixty_minute: NewowFrequencyPriceChannelOut
    display: NewowDisplayPriceOut


class NewowPageWindowOut(_Out):
    window: Literal[10, 20, 24, 30, 52]
    cumulative_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    win_rate_pct: Decimal
    score: Decimal
    terminal_position_was_open: bool
    force_closed_at_end: Literal[True]
    execution_timing: Literal["same_bar_close"]
    trustworthy_for_research: Literal[False]
    formula_version: Literal["newow_hhv_llv_window_optimizer_page_v1"]


class NewowPositionRangeOut(_Out):
    minimum: Decimal | None
    maximum: Decimal | None


class NewowCertaintyOut(_Out):
    trend: int
    oscillation: int
    alignment: int
    direction: int
    total: int


class NewowVolatilityOut(_Out):
    value_pct: Decimal
    level: Literal["low", "mid", "high"]
    sample_size: int


class NewowCompositePageOut(_Out):
    trend_bias: Literal["bullish", "bearish", "cautious", "warning", "neutral"]
    oscillation_bias: Literal["bullish", "bearish", "neutral"]
    direction_token: Literal[
        "weekly_bearish_rebound",
        "weekly_bearish",
        "daily_pullback",
        "sixty_minute_pullback",
        "multiperiod_bullish",
        "insufficient",
    ]
    decision_key: Literal[
        "bullish-bullish",
        "bullish-bearish",
        "bullish-neutral",
        "bearish-bullish",
        "bearish-bearish",
        "bearish-neutral",
        "cautious-bullish",
        "cautious-bearish",
        "cautious-neutral",
        "warning-bullish",
        "warning-bearish",
        "warning-neutral",
        "neutral-neutral",
    ]
    action_token: Literal[
        "BUILD_OR_ADD",
        "HOLD_AND_WAIT",
        "REDUCE_AND_WAIT",
        "CLEAR",
        "CAUTIOUS_HOLD",
        "WAIT_FOR_SIGNAL",
    ]
    position_range: NewowPositionRangeOut
    certainty: NewowCertaintyOut
    volatility: NewowVolatilityOut
    risk_tokens: list[str]
    unreachable_decision_keys: list[str]
    formula_version: Literal["newow_composite_decision_page_v3_2_82"]


class NewowCompositeCleanroomOut(_Out):
    trend_bias: Literal["bullish", "bearish", "cautious", "warning", "neutral"]
    oscillation_bias: Literal["bullish", "bearish", "neutral"]
    direction_token: Literal[
        "weekly_bearish_rebound",
        "weekly_bearish",
        "daily_pullback",
        "sixty_minute_pullback",
        "multiperiod_bullish",
        "insufficient",
    ]
    decision_key: Literal[
        "bullish-bullish",
        "bullish-bearish",
        "bullish-neutral",
        "bearish-bullish",
        "bearish-bearish",
        "bearish-neutral",
        "cautious-bullish",
        "cautious-bearish",
        "cautious-neutral",
        "warning-bullish",
        "warning-bearish",
        "warning-neutral",
        "neutral-neutral",
    ]
    action_token: Literal[
        "BUILD_OR_ADD",
        "HOLD_AND_WAIT",
        "REDUCE_AND_WAIT",
        "CLEAR",
        "CAUTIOUS_HOLD",
        "WAIT_FOR_SIGNAL",
    ]
    position_range: NewowPositionRangeOut
    certainty: NewowCertaintyOut
    volatility: NewowVolatilityOut
    risk_tokens: list[str]
    page_difference_reason: str | None
    formula_version: Literal["newow_composite_decision_cleanroom_v1"]


class NewowFirstActionOut(_Out):
    level: Literal["violate", "warn", "ok"]
    rule_token: str
    fact_tokens: list[str]
    formula_version: Literal["newow_first_action_principle_page_v3_2_63"]


class NewowDiagnosticFactsOut(_Out):
    as_of: datetime
    target_price: Decimal | None
    absorb_price: Decimal | None
    target_distance_pct: Decimal | None
    absorb_distance_pct: Decimal | None
    ema20: Decimal | None
    close_vs_ema20: Literal["above", "below", "equal", "unavailable"]
    trend_state: Literal["YELLOW", "BLUE", "UNAVAILABLE"]
    trend_duration_bars: int
    oscillation_holding: bool | None
    main_force_status: Literal[
        "无庄控盘", "开始控盘", "有庄控盘", "高度控盘", "主力出货", "高控+出货"
    ] | None
    main_rise_active: bool | None
    cup_state: Literal[
        "NONE", "FORMING", "READY", "BREAKOUT", "WEAKENED", "INVALIDATED", "EXPIRED"
    ] | None
    weekly_signal: Literal["buy", "hold", "sell", "wait"] | None
    daily_signal: Literal["buy", "hold", "sell", "wait"] | None
    repainting_inputs_excluded: list[NewowRepaintingFormula]
    formula_versions: list[NewowDiagnosticFactsFormula]


class NewowDiagnosticTokenOut(_Out):
    code: str
    severity: Literal["info", "warning", "risk"]
    fact_keys: list[str]
    formula_identities: list[NewowDiagnosticTokenFormula]


class NewowSemanticLabelsOut(_Out):
    page_parity: Literal[True]
    cleanroom_separated: Literal[True]
    observation_only: Literal[True]
    causal_research_result: Literal[False]
    repainting_input_used: Literal[False]


class NewowFormulaDescriptionsOut(_Out):
    trend_band: Literal["newow_trend_band_page_v2"]
    escape: Literal["newow_escape_d123_page_v2"]
    cup_handle: Literal["newow_cup_handle_v1"]
    oscillation: Literal["newow_oscillation_hhv_llv10_page_v1"]
    main_force: Literal["newow_main_force_control_page_v1"]
    main_rise: Literal["newow_main_rise_ma35_ma45_page_v1"]
    price_channel: Literal["newow_target_absorb_hhv_llv10_page_v1"]
    display_selection: Literal["newow_target_absorb_display_selection_page_v2"]
    page_window_comparison: Literal["newow_hhv_llv_window_optimizer_page_v1"]
    causal_window_identity: Literal["newow_hhv_llv_window_optimizer_causal_v1"]
    composite_page: Literal["newow_composite_decision_page_v3_2_82"]
    composite_cleanroom: Literal["newow_composite_decision_cleanroom_v1"]
    first_action: Literal["newow_first_action_principle_page_v3_2_63"]
    diagnostic_facts: Literal["newow_diagnostic_facts_cleanroom_v1"]
    diagnostic_rules: Literal["newow_diagnostic_rules_cleanroom_v1"]


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
    price_channel: NewowPriceChannelOut
    page_window_comparison: list[NewowPageWindowOut]
    composite_page: NewowCompositePageOut | None
    composite_cleanroom: NewowCompositeCleanroomOut | None
    first_action_principle: NewowFirstActionOut
    diagnostic_facts: NewowDiagnosticFactsOut
    diagnostic_tokens: list[NewowDiagnosticTokenOut]
    semantic_labels: NewowSemanticLabelsOut
    legend: dict[str, str]
    formula_descriptions: NewowFormulaDescriptionsOut
    warnings: list[str]
