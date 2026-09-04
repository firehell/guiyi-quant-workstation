export type NewowTrendBandState = 'UNAVAILABLE' | 'YELLOW' | 'BLUE'
export type NewowTrendTransition = 'BUILD' | 'CLEAR'
export type NewowTrendMarkerType = NewowTrendTransition
export type NewowEscapeMarkerType = 'NEWOW_ESCAPE_D1' | 'NEWOW_ESCAPE_D2' | 'NEWOW_ESCAPE_D3'
export type NewowCupMarkerType =
  | 'CUP_HANDLE_READY'
  | 'CUP_HANDLE_BREAKOUT'
  | 'CUP_HANDLE_WEAKENED'
  | 'CUP_HANDLE_INVALIDATED'
  | 'CUP_HANDLE_EXPIRED'
export type NewowMarkerType = NewowTrendMarkerType | NewowEscapeMarkerType | NewowCupMarkerType
export type NewowCupDirection = 'BULLISH' | 'BEARISH'
export type NewowCupState = 'FORMING' | 'READY' | 'BREAKOUT' | 'WEAKENED' | 'INVALIDATED' | 'EXPIRED'
export type NewowWarning =
  | 'NEWOW_TREND_WARMUP_INSUFFICIENT'
  | 'NEWOW_D123_WARMUP_INSUFFICIENT'
  | 'NEWOW_CUP_WARMUP_INSUFFICIENT'
  | 'NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT'

export type NewowDisplayPeriod = 'day' | 'week' | 'best_available'
export type NewowPageSignal = 'buy' | 'hold' | 'sell' | 'wait'
export type NewowDiagnosticCupState = NewowCupState | 'NONE'
export type NewowTrendBias = 'bullish' | 'bearish' | 'cautious' | 'warning' | 'neutral'
export type NewowOscillationBias = 'bullish' | 'bearish' | 'neutral'
export type NewowCompositeAction =
  | 'BUILD_OR_ADD'
  | 'HOLD_AND_WAIT'
  | 'REDUCE_AND_WAIT'
  | 'CLEAR'
  | 'CAUTIOUS_HOLD'
  | 'WAIT_FOR_SIGNAL'
export type NewowDirectionToken =
  | 'weekly_bearish_rebound'
  | 'weekly_bearish'
  | 'daily_pullback'
  | 'sixty_minute_pullback'
  | 'multiperiod_bullish'
  | 'insufficient'

export type NewowJsonValue =
  | null
  | string
  | number
  | boolean
  | readonly NewowJsonValue[]
  | { readonly [key: string]: NewowJsonValue }

export interface NewowTrendQueryIdentity {
  readonly symbol: string
  readonly from: string
  readonly through: string
}

export interface NewowMeta {
  readonly strategy_code: 'newow_trend_v1'
  readonly profile_id: 'newow_trend_d1_page_v2'
  readonly frequency: '1d'
  readonly series_kind: 'actual_dominant'
  readonly calculation_identity: string
  readonly data_revision_identity: string | null
  readonly request_identity: string
}

export interface NewowInstrument {
  readonly product: string
  readonly display_name: string | null
  readonly last_visible_physical_contract: string | null
}

export interface NewowBar {
  readonly bar_end: string
  readonly trading_day: string
  readonly open: number
  readonly high: number
  readonly low: number
  readonly close: number
  readonly volume: number
  readonly open_interest: number | null
  readonly physical_contract: string
  readonly segment_id: string
  readonly source_identity: string
}

export interface NewowTrendBandPoint {
  readonly bar_end: string
  readonly b_value: number | null
  readonly c_value: number | null
  readonly state: NewowTrendBandState
  readonly state_before: NewowTrendBandState | null
  readonly transition: NewowTrendTransition | null
}

export interface NewowMarker<T extends NewowMarkerType = NewowMarkerType> {
  readonly marker_id: string
  readonly marker_type: T
  readonly bar_end: string
  readonly price: number
  readonly label: string
  readonly color_token: string
  readonly priority: number
  readonly related_marker_ids: readonly string[]
  readonly trigger_facts: Readonly<Record<string, NewowJsonValue>>
  readonly formula_version: string
}

export interface NewowCupPivot {
  readonly pivot_at: string
  readonly confirmed_at: string
  readonly price: number
}

export interface NewowCupHandle {
  readonly candidate_id: string
  readonly direction: NewowCupDirection
  readonly state: NewowCupState
  readonly left_rim: NewowCupPivot
  readonly bottom: NewowCupPivot
  readonly right_rim: NewowCupPivot
  readonly handle_start_at: string
  readonly handle_extreme: NewowCupPivot | null
  readonly pivot_price: number | null
  readonly pivot_frozen_at: string | null
  readonly confirmed_at: string
  readonly first_seen_at: string
  readonly state_changed_at: string
  readonly score: number
  readonly score_breakdown: Readonly<Record<string, number>>
  readonly hard_failures: readonly string[]
  readonly diagnostics: readonly string[]
  readonly volume_facts: Readonly<Record<string, number>>
  readonly formula_version: 'newow_cup_handle_v1'
}

export interface NewowRolloverSeam {
  readonly trading_day: string
  readonly previous_contract: string
  readonly next_contract: string
  readonly previous_bar_end: string
  readonly next_bar_end: string
  readonly previous_segment_id: string
  readonly next_segment_id: string
}

export interface NewowLegend {
  readonly BUILD: 'trend build'
  readonly CLEAR: 'trend clear'
  readonly D1: 'escape D1'
  readonly D2: 'escape D2'
  readonly D3: 'escape D3'
}

export interface NewowFormulaDescriptions {
  readonly trend_band: 'newow_trend_band_page_v2'
  readonly escape: 'newow_escape_d123_page_v2'
  readonly cup_handle: 'newow_cup_handle_v1'
  readonly oscillation: 'newow_oscillation_hhv_llv10_page_v1'
  readonly main_force: 'newow_main_force_control_page_v1'
  readonly main_rise: 'newow_main_rise_ma35_ma45_page_v1'
  readonly price_channel: 'newow_target_absorb_hhv_llv10_page_v1'
  readonly display_selection: 'newow_target_absorb_display_selection_page_v2'
  readonly page_window_comparison: 'newow_hhv_llv_window_optimizer_page_v1'
  readonly causal_window_identity: 'newow_hhv_llv_window_optimizer_causal_v1'
  readonly composite_page: 'newow_composite_decision_page_v3_2_82'
  readonly composite_cleanroom: 'newow_composite_decision_cleanroom_v1'
  readonly first_action: 'newow_first_action_principle_page_v3_2_63'
  readonly diagnostic_facts: 'newow_diagnostic_facts_cleanroom_v1'
  readonly diagnostic_rules: 'newow_diagnostic_rules_cleanroom_v1'
}

export interface NewowPriceChannelPoint {
  readonly bar_end: string
  readonly target: number | null
  readonly absorb: number | null
  readonly window: 10
  readonly available: boolean
  readonly formula_version: 'newow_target_absorb_hhv_llv10_page_v1'
}

export interface NewowFrequencyPriceChannel {
  readonly frequency: '1d' | '1w' | '60m'
  readonly points: readonly NewowPriceChannelPoint[]
  readonly owner_segment_ids: readonly string[]
  readonly formula_version: 'newow_target_absorb_hhv_llv10_page_v1'
}

export interface NewowDisplayPriceSelection {
  readonly target: number | null
  readonly absorb: number | null
  readonly raw_target: number | null
  readonly raw_absorb: number | null
  readonly target_period: NewowDisplayPeriod | null
  readonly absorb_period: NewowDisplayPeriod | null
  readonly target_branch_token: string
  readonly absorb_branch_token: string
  readonly formula_version: 'newow_target_absorb_display_selection_page_v2'
}

export interface NewowPriceChannel {
  readonly daily: NewowFrequencyPriceChannel
  readonly weekly: NewowFrequencyPriceChannel
  readonly sixty_minute: NewowFrequencyPriceChannel
  readonly display: NewowDisplayPriceSelection
}

export interface NewowPageWindowComparison {
  readonly window: 10 | 20 | 24 | 30 | 52
  readonly cumulative_return_pct: number
  readonly max_drawdown_pct: number
  readonly trade_count: number
  readonly win_rate_pct: number
  readonly score: number
  readonly terminal_position_was_open: boolean
  readonly force_closed_at_end: true
  readonly execution_timing: 'same_bar_close'
  readonly trustworthy_for_research: false
  readonly formula_version: 'newow_hhv_llv_window_optimizer_page_v1'
}

export interface NewowPositionRange {
  readonly minimum: number | null
  readonly maximum: number | null
}

export interface NewowCertainty {
  readonly trend: number
  readonly oscillation: number
  readonly alignment: number
  readonly direction: number
  readonly total: number
}

export interface NewowVolatility {
  readonly value_pct: number
  readonly level: 'low' | 'mid' | 'high'
  readonly sample_size: number
}

export interface NewowCompositeDecision {
  readonly trend_bias: NewowTrendBias
  readonly oscillation_bias: NewowOscillationBias
  readonly direction_token: NewowDirectionToken
  readonly decision_key: string
  readonly action_token: NewowCompositeAction
  readonly position_range: NewowPositionRange
  readonly certainty: NewowCertainty
  readonly volatility: NewowVolatility
  readonly risk_tokens: readonly string[]
  readonly formula_version: 'newow_composite_decision_page_v3_2_82'
  readonly unreachable_decision_keys: readonly string[]
}

export interface NewowCleanroomCompositeDecision extends Omit<NewowCompositeDecision, 'formula_version' | 'unreachable_decision_keys'> {
  readonly page_difference_reason: string | null
  readonly formula_version: 'newow_composite_decision_cleanroom_v1'
}

export interface NewowFirstActionPrinciple {
  readonly level: 'violate' | 'warn' | 'ok'
  readonly rule_token: string
  readonly fact_tokens: readonly string[]
  readonly formula_version: 'newow_first_action_principle_page_v3_2_63'
}

export interface NewowDiagnosticFacts {
  readonly as_of: string
  readonly target_price: number | null
  readonly absorb_price: number | null
  readonly target_distance_pct: number | null
  readonly absorb_distance_pct: number | null
  readonly ema20: number | null
  readonly close_vs_ema20: 'above' | 'below' | 'equal' | 'unavailable'
  readonly trend_state: NewowTrendBandState
  readonly trend_duration_bars: number
  readonly oscillation_holding: boolean | null
  readonly main_force_status: string | null
  readonly main_rise_active: boolean | null
  readonly cup_state: NewowDiagnosticCupState | null
  readonly weekly_signal: NewowPageSignal | null
  readonly daily_signal: NewowPageSignal | null
  readonly repainting_inputs_excluded: readonly string[]
  readonly formula_versions: readonly string[]
}

export interface NewowDiagnosticToken {
  readonly code: string
  readonly severity: 'info' | 'warning' | 'risk'
  readonly fact_keys: readonly string[]
  readonly formula_identities: readonly string[]
}

export interface NewowSemanticLabels {
  readonly page_parity: true
  readonly cleanroom_separated: true
  readonly observation_only: true
  readonly causal_research_result: false
  readonly repainting_input_used: false
}

export interface NewowTrendDetailResponse {
  readonly meta: NewowMeta
  readonly instrument: NewowInstrument
  readonly bars: readonly NewowBar[]
  readonly bar_policy: 'completed_only'
  readonly trend_band: readonly NewowTrendBandPoint[]
  readonly trend_markers: readonly NewowMarker<NewowTrendMarkerType>[]
  readonly escape_markers: readonly NewowMarker<NewowEscapeMarkerType>[]
  readonly cup_markers: readonly NewowMarker<NewowCupMarkerType>[]
  readonly cup_handles: readonly NewowCupHandle[]
  readonly rollover_seams: readonly NewowRolloverSeam[]
  readonly price_channel: NewowPriceChannel
  readonly page_window_comparison: readonly NewowPageWindowComparison[]
  readonly composite_page: NewowCompositeDecision | null
  readonly composite_cleanroom: NewowCleanroomCompositeDecision | null
  readonly first_action_principle: NewowFirstActionPrinciple
  readonly diagnostic_facts: NewowDiagnosticFacts
  readonly diagnostic_tokens: readonly NewowDiagnosticToken[]
  readonly semantic_labels: NewowSemanticLabels
  readonly legend: NewowLegend
  readonly formula_descriptions: NewowFormulaDescriptions
  readonly warnings: readonly NewowWarning[]
}
