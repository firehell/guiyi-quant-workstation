import type { NewowFrequency, NewowStrategy } from './marketDetail.ts'

export {
  NEWOW_FREQUENCIES as NEWOW_PRODUCT_FREQUENCIES,
  NEWOW_STRATEGIES as NEWOW_PRODUCT_STRATEGIES,
} from './marketDetail.ts'
export type NewowProductStrategy = NewowStrategy
export type NewowProductFrequency = NewowFrequency

export const NEWOW_PRODUCT_SECTIONS = ['chart', 'auxiliary', 'reference', 'explanation', 'comparator'] as const
export type NewowProductSection = (typeof NEWOW_PRODUCT_SECTIONS)[number]
export type NewowAuxiliaryComponent = 'main_force_control' | 'up_down_energy' | 'zhaoyao_mirror' | 'cup_handle'

export interface NewowProductIdentity {
  readonly product: string
  readonly strategy: NewowProductStrategy
  readonly frequency: NewowProductFrequency
  readonly seriesKind: 'actual_dominant'
}

export interface NewowProductWireIdentity {
  readonly product: string
  readonly strategy: NewowProductStrategy
  readonly frequency: NewowProductFrequency
  readonly series_kind: 'actual_dominant'
  readonly profile_id: string
  readonly formula_versions: readonly string[]
}

export type NewowRuntimeStatus = 'ready' | 'warming' | 'unavailable' | 'not_applicable' | 'evidence_required'
export type NewowEvidenceStatus = 'ACTIVE_CODE_VERIFIED' | 'RESEARCH_EVIDENCE_ONLY' | 'EVIDENCE_REQUIRED' | 'OUT_OF_SCOPE'

export interface NewowFeatureStatus {
  readonly status: NewowRuntimeStatus
  readonly evidence_status: NewowEvidenceStatus
  readonly reason_code: string | null
}

export interface NewowProductMeta {
  readonly schema_version: 'newow_product_detail_v1'
  readonly identity: NewowProductWireIdentity
  readonly as_of: string
  readonly read_at: string
  readonly input_content_sha256: string
  readonly data_revision_identity: string | null
  readonly snapshot_token: string | null
  readonly reference_model_version: 'newow_marker_reference_zero_cost_v1'
  readonly futures_adaptation_version: 'newow_futures_segment_interrupt_v1'
}

export interface NewowProductBar {
  readonly bar_end: string
  readonly trading_day: string
  readonly open: string
  readonly high: string
  readonly low: string
  readonly close: string
  readonly volume: number
  readonly open_interest: number | null
  readonly physical_contract: string
  readonly segment_id: string
  readonly source_identity: string
  readonly observation_eligible: boolean
  readonly completed: true
}

export interface NewowProductFrame {
  readonly bar_end: string
  readonly main_state: 'BUILD' | 'HOLD' | 'CLEAR' | 'FLAT' | 'UNAVAILABLE'
  readonly main_values: Readonly<Record<string, string | null>>
  readonly status: NewowFeatureStatus
  readonly action_ids: readonly string[]
  readonly hint_ids: readonly string[]
}

export interface NewowProductAction {
  readonly signal_id: string
  readonly kind: 'BUILD' | 'CLEAR'
  readonly bar_end: string
  readonly trading_day: string
  readonly reference_price: string
  readonly physical_contract: string
  readonly segment_id: string
  readonly related_build_id: string | null
  readonly trade_eligibility: 'ELIGIBLE' | 'WARMUP_ONLY' | 'NO_ELIGIBLE_ENTRY'
  readonly sequence: number
}

export interface NewowProductHint {
  readonly hint_id: string
  readonly kind: string
  readonly bar_end: string
  readonly known_at: string
  readonly anchor_price: string | null
  readonly physical_contract: string
  readonly segment_id: string
  readonly retrospective: false
  readonly quantity_effect: 'none'
  readonly sequence: number | null
}

export interface NewowChartValue {
  readonly chart_from: string
  readonly chart_through: string
  readonly page_identity: string
  readonly bars: readonly NewowProductBar[]
  readonly frames: readonly NewowProductFrame[]
  readonly actions: readonly NewowProductAction[]
  readonly hints: readonly NewowProductHint[]
  readonly diagnostics: readonly string[]
  readonly next_before: string | null
  readonly repainting: false
  readonly formal_signal_eligible: true
  readonly allowed_uses: readonly ['product_chart', 'reference_input']
}

export interface NewowReferenceSummary {
  readonly membership_policy: string
  readonly closed_count: number
  readonly win_count: number
  readonly loss_count: number
  readonly flat_count: number
  readonly win_rate_pct: string | null
  readonly mean_return_pct: string | null
  readonly sum_return_percentage_points: string | null
  readonly open_count: number
  readonly interrupted_count: number
  readonly initial_count: number
}

export interface NewowReferenceTrade {
  readonly reference_trade_id: string
  readonly product: string
  readonly strategy_code: NewowProductStrategy
  readonly frequency: NewowProductFrequency
  readonly physical_contract: string
  readonly segment_id: string
  readonly formula_versions: readonly string[]
  readonly reference_model_version: 'newow_marker_reference_zero_cost_v1'
  readonly futures_adaptation_version: 'newow_futures_segment_interrupt_v1'
  readonly entry_signal_id: string
  readonly entry_sequence: number
  readonly entry_bar_end: string
  readonly entry_trading_day: string
  readonly entry_reference_price: string
  readonly exit_signal_id: string | null
  readonly exit_bar_end: string | null
  readonly exit_trading_day: string | null
  readonly exit_reference_price: string | null
  readonly status: 'OPEN' | 'CLOSED' | 'ROLLOVER_INTERRUPTED'
  readonly holding_bars: number
  readonly reference_return_pct: string | null
  readonly mark_bar_end: string | null
  readonly mark_reference_price: string | null
  readonly mark_change_pct: string | null
  readonly interrupted_at: string | null
  readonly interruption_reason: string | null
  readonly statistics_membership: string | null
  readonly hint_ids: readonly string[]
}

export interface NewowReferenceValue {
  readonly performance_since: string
  readonly performance_through: string
  readonly actual_available_through: string
  readonly reference_cutoff: string
  readonly reference_input_sha256: string
  readonly summary: NewowReferenceSummary
  readonly items: readonly NewowReferenceTrade[]
  readonly next_before: string | null
  readonly executable: false
  readonly auto_order: false
  readonly allowed_uses: readonly ['page_parity_reference', 'research_display']
}

export interface NewowMainForceControlData {
  readonly kongpan: readonly number[]
  readonly status: readonly string[]
  readonly current_status: string
  readonly formula_version: string
}

export interface NewowZhaoyaoMirrorData {
  readonly entry: readonly number[]
  readonly wash: readonly number[]
  readonly distribution: readonly number[]
  readonly markup: readonly number[]
  readonly exit: readonly number[]
  readonly inducement: readonly number[]
  readonly peaks: readonly number[]
  readonly caution: readonly number[]
  readonly repainting: true
  readonly formal_signal_eligible: false
  readonly formula_version: string
}

export interface NewowUpDownEnergyData {
  readonly var4: readonly (number | null)[]
  readonly ma10: readonly number[]
  readonly band_entry: readonly number[]
  readonly rebound_entry: readonly number[]
  readonly oversold_entry: readonly number[]
  readonly var3: readonly number[]
  readonly ma120: readonly number[]
  readonly formula_version: string
}

export interface NewowCupPivotValue {
  readonly kind: string
  readonly price: string
  readonly pivot_at: string
  readonly confirmed_at: string
  readonly pivot_index: number
  readonly confirmed_index: number
  readonly atr_at_pivot: number
}

export interface NewowCupWitness {
  readonly witness_id: string
  readonly candidate_id: string
  readonly left_rim: NewowCupPivotValue
  readonly bottom: NewowCupPivotValue
  readonly right_rim: NewowCupPivotValue
  readonly handle_extreme: NewowCupPivotValue
  readonly pivot_price: string
  readonly confirmed_at: string
  readonly score: number
  readonly score_breakdown: readonly (readonly [string, number])[]
  readonly volume_facts: readonly (readonly [string, number])[]
  readonly right_leg_median_exact: string
  readonly handle_median_exact: string
  readonly handle_baseline_median_exact: string
  readonly profile_identity: string
  readonly formula_version: string
}

export type NewowAuxiliaryData = NewowMainForceControlData | NewowZhaoyaoMirrorData | NewowUpDownEnergyData | readonly NewowCupWitness[]

export interface NewowAuxiliarySegment {
  readonly physical_contract: string
  readonly segment_id: string
  readonly bar_ends: readonly string[]
  readonly status: NewowFeatureStatus
  readonly data: NewowAuxiliaryData | null
}

export interface NewowAuxiliaryValue {
  readonly component: NewowAuxiliaryComponent
  readonly formula_version: string
  readonly segments: readonly NewowAuxiliarySegment[]
  readonly repainting: boolean
  readonly formal_signal_eligible: boolean
  readonly page_parity: boolean
  readonly source_category: 'guiyi_product_auxiliary_adapter'
  readonly allowed_uses: readonly string[]
}

export interface NewowContextSlot {
  readonly frequency: NewowProductFrequency
  readonly as_of: string
  readonly availability: NewowFeatureStatus
  readonly confirmation_status: NewowFeatureStatus
  readonly identity: NewowProductWireIdentity | null
  readonly bar_end: string | null
  readonly source_identity: string | null
  readonly physical_contract: string | null
  readonly segment_id: string | null
  readonly formula_versions: readonly string[]
  readonly main_state: NewowProductFrame['main_state'] | null
}

export interface NewowContextSnapshot {
  readonly as_of: string
  readonly weekly: NewowContextSlot
  readonly daily: NewowContextSlot
  readonly hourly: NewowContextSlot
  readonly missing_frequencies: readonly NewowProductFrequency[]
  readonly recompute_mode: string
  readonly historical_database_knowledge_reconstructed: false
}

export interface NewowSourceBars {
  readonly usage: string
  readonly fact_names: readonly string[]
  readonly frequency: NewowProductFrequency
  readonly physical_contract: string | null
  readonly segment_id: string | null
  readonly source_identities: readonly string[]
  readonly count: number
  readonly first_bar_end: string | null
  readonly last_bar_end: string | null
  readonly first_trading_day: string | null
  readonly last_trading_day: string | null
  readonly as_of: string
  readonly in_sample: boolean
  readonly repainting: boolean
  readonly repaint_status: NewowFeatureStatus
  readonly input_status: NewowFeatureStatus
}

export interface NewowCompositeInputFact {
  readonly role: string
  readonly value: string
  readonly frequency: NewowProductFrequency
  readonly bar_end: string
  readonly physical_contract: string
  readonly segment_id: string
}

export interface NewowCompositeDecision {
  readonly source_key: string
  readonly selected_key: string
  readonly label: string
  readonly position_range: string
  readonly fallback_used: boolean
  readonly warning_branches_unreachable: boolean
  readonly position_is_target: boolean
  readonly position_is_hand_count: boolean
  readonly formula_version: string
}

export interface NewowCompositeDirection { readonly token: string; readonly certainty_points: number; readonly formula_version: string }
export interface NewowCertaintyBreakdown {
  readonly trend: number
  readonly oscillation: number
  readonly alignment: number
  readonly direction: number
  readonly uncapped_total: number
  readonly total: number
  readonly cap: number | null
  readonly is_probability: false
  readonly is_win_rate: false
  readonly formula_version: string
}
export interface NewowCompositeVolatility {
  readonly value_pct: string
  readonly level: string
  readonly true_range_count: number
  readonly method: string
  readonly is_wilder_atr: false
  readonly formula_version: string
}
export interface NewowFirstAction {
  readonly rule_token: string
  readonly level: string
  readonly page_title: string
  readonly page_detail: string
  readonly token_owner: string
  readonly token_is_page_native: false
  readonly page_formula_version: string
}
export interface NewowWeekDayMatrix { readonly key: string; readonly name: string; readonly risk: string; readonly position: string; readonly formula_version: string }
export type NewowSubfeatureValue = string | NewowCompositeDecision | NewowCompositeDirection | NewowCertaintyBreakdown | NewowCompositeVolatility | NewowFirstAction | NewowWeekDayMatrix | null
export interface NewowSubfeature { readonly name: string; readonly status: NewowFeatureStatus; readonly value: NewowSubfeatureValue }

export interface NewowCompositeValue {
  readonly decision: NewowCompositeDecision
  readonly direction: NewowCompositeDirection
  readonly certainty: NewowCertaintyBreakdown
  readonly volatility: NewowCompositeVolatility | null
  readonly first_action: NewowFirstAction
  readonly week_day_matrix: NewowWeekDayMatrix
  readonly subfeatures: readonly NewowSubfeature[]
  readonly input_facts: readonly NewowCompositeInputFact[]
  readonly warning_branches_unreachable: boolean
  readonly diagnostic_tokens: null
  readonly ai_copy: null
  readonly six_combo_ranking: null
  readonly evidence_manifest_sha256: string
  readonly page_source_sha256: string
  readonly reachability_sha256: string
  readonly ai_template_evidence_sha256: string
  readonly frozen_results_sha256: string
}

export interface NewowCompositeResult {
  readonly status: NewowRuntimeStatus
  readonly evidence_status: NewowEvidenceStatus
  readonly reason_code: string | null
  readonly as_of: string
  readonly formula_versions: readonly string[]
  readonly source_bars: readonly NewowSourceBars[]
  readonly value: NewowCompositeValue | null
}

export interface NewowPageFact { readonly value: string | boolean; readonly frequency: NewowProductFrequency; readonly bar_end: string; readonly physical_contract: string; readonly segment_id: string }
export interface NewowTargetDisplayPrice { readonly raw_value: string; readonly display_value: string; readonly branch: string; readonly source_frequency: NewowProductFrequency; readonly bar_end: string; readonly physical_contract: string; readonly segment_id: string }
export interface NewowTargetSubfeature { readonly name: string; readonly status: NewowFeatureStatus; readonly value: string | null }
export interface NewowTargetAbsorbValue {
  readonly target: NewowTargetDisplayPrice
  readonly absorb: NewowTargetDisplayPrice
  readonly previous_close: null
  readonly display_surface: string
  readonly subfeatures: readonly NewowTargetSubfeature[]
  readonly evidence_manifest_sha256: string
  readonly inherited_frozen_results_sha256: string
}
export interface NewowTargetAbsorbResult {
  readonly status: NewowRuntimeStatus
  readonly evidence_status: NewowEvidenceStatus
  readonly reason_code: string | null
  readonly as_of: string
  readonly display_surface: string | null
  readonly formula_versions: readonly string[]
  readonly source_bars: readonly NewowPageFact[]
  readonly decision_facts: readonly NewowPageFact[]
  readonly value: NewowTargetAbsorbValue | null
}

export interface NewowSourceFact {
  readonly role: string
  readonly source_category: string
  readonly adapter_version: string
  readonly formula_versions: readonly string[]
  readonly frequency: NewowProductFrequency | null
  readonly bar_end: string | null
  readonly physical_contract: string | null
  readonly segment_id: string | null
  readonly as_of: string
  readonly dependency_sha256: string | null
  readonly status: 'ready' | 'unavailable' | 'evidence_required'
  readonly reason_code: string | null
}

export interface NewowExplanationValue {
  readonly context: NewowContextSnapshot
  readonly composite: NewowCompositeResult
  readonly target_absorb: NewowTargetAbsorbResult
  readonly sources: readonly NewowSourceFact[]
  readonly page_parity: false
  readonly allowed_uses: readonly ['research_explanation', 'product_display']
}

export interface NewowComparatorTrade { readonly entry_bar_end: string; readonly entry_price: string; readonly exit_bar_end: string; readonly exit_price: string; readonly return_pct: string; readonly won: boolean; readonly synthetic_terminal: boolean }
export interface NewowComparatorDisplay { readonly cumulative_return_pct: string; readonly max_drawdown_pct: string; readonly win_rate_pct: string }
export interface NewowWindowComparison {
  readonly window: number
  readonly cumulative_return_pct: string
  readonly max_drawdown_pct: string
  readonly trade_count: number
  readonly win_count: number
  readonly loss_count: number
  readonly win_rate_pct: string
  readonly force_closed_at_end: boolean
  readonly score: string
  readonly page_display: NewowComparatorDisplay
  readonly trades: readonly NewowComparatorTrade[]
}
export interface NewowComparatorSourceBars {
  readonly count: number
  readonly first_trading_day: string | null
  readonly last_trading_day: string | null
  readonly first_bar_end: string | null
  readonly last_bar_end: string | null
  readonly source_identities: readonly string[]
  readonly snapshot_kind: string
  readonly fact_identity_fields: readonly string[]
}
export interface NewowComparatorSegment {
  readonly physical_contract: string
  readonly segment_id: string
  readonly frequency: NewowProductFrequency
  readonly authoritative_start_trading_day: string
  readonly authoritative_end_trading_day: string
  readonly source_bars: NewowComparatorSourceBars
  readonly as_of: string
  readonly in_sample: boolean
  readonly repainting: boolean
  readonly repaint_status: NewowFeatureStatus
  readonly input_snapshot_status: NewowFeatureStatus
  readonly status: NewowFeatureStatus
  readonly results: readonly NewowWindowComparison[]
  readonly ranked_windows: readonly number[]
}
export interface NewowComparatorProductValue {
  readonly segments: readonly NewowComparatorSegment[]
  readonly default_segment_id: string | null
  readonly candidate_windows: readonly number[]
  readonly page_formula_version: string
  readonly futures_adapter_version: string
  readonly page_source_kernel_page_parity: true
  readonly futures_adapter_page_parity: false
  readonly in_sample: true
  readonly executable: false
  readonly input_mode: string
  readonly subfeatures: readonly NewowSubfeature[]
}
export interface NewowComparatorResult {
  readonly identity: NewowProductWireIdentity
  readonly status: NewowRuntimeStatus
  readonly evidence_status: NewowEvidenceStatus
  readonly reason_code: string | null
  readonly as_of: string
  readonly formula_versions: readonly string[]
  readonly source_bars: readonly NewowComparatorSourceBars[]
  readonly value: NewowComparatorProductValue | null
}
export interface NewowComparatorValue {
  readonly result: NewowComparatorResult | null
  readonly executable: false
  readonly page_parity: false
  readonly synthetic_terminal_is_reference_exit: false
  readonly allowed_uses: readonly ['in_sample_comparison']
}

export interface NewowProductSectionValueMap {
  chart: NewowChartValue
  auxiliary: NewowAuxiliaryValue
  reference: NewowReferenceValue
  explanation: NewowExplanationValue
  comparator: NewowComparatorValue
}

export type NewowProductSectionResponse<S extends NewowProductSection = NewowProductSection> = {
  readonly [K in S]: {
    readonly meta: NewowProductMeta
    readonly section: K
    readonly status: NewowFeatureStatus
    readonly value: NewowProductSectionValueMap[K] | null
  }
}[S]

interface NewowRequestCommon {
  readonly identity: NewowProductIdentity
  readonly asOf: string
  readonly snapshotToken?: string
}

export type NewowProductRequest =
  | (NewowRequestCommon & { readonly section: 'chart'; readonly from?: string; readonly through?: string; readonly chartLimit?: number; readonly chartBefore?: string })
  | (NewowRequestCommon & { readonly section: 'auxiliary'; readonly component: NewowAuxiliaryComponent; readonly from?: string; readonly through?: string })
  | (NewowRequestCommon & { readonly section: 'reference'; readonly performanceSince?: string; readonly performanceThrough?: string; readonly historyLimit?: number; readonly historyBefore?: string })
  | (NewowRequestCommon & { readonly section: 'explanation' })
  | (NewowRequestCommon & { readonly section: 'comparator' })

export type NewowResourceLifecycle =
  | 'not_requested'
  | 'loading'
  | 'ready'
  | 'warming'
  | 'evidence_required'
  | 'unavailable'
  | 'not_applicable'
  | 'stale'
  | 'input_conflict'
  | 'busy'
  | 'cancelled'

export type NewowProductDisplayState = NewowResourceLifecycle | 'no_action' | 'empty_closed'
