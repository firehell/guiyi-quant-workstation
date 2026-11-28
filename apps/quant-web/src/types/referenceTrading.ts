import type { NewowAuxiliaryComponent, NewowProductIdentity, NewowProductSectionResponse } from './newowProduct.ts'

export type ReferenceMode = 'historical_replay' | 'forward_observation'

export interface ReferenceStreamInfo {
  stream_id: string
  strategy_code: string
  product: string
  frequency: string
  recording_mode: ReferenceMode
  formula_versions: string[]
  profile_id: string
  reference_model_version: string
  futures_adaptation_version: string
  active_revision_id: string | null
  latest_seq: number
  health: string
  readable: boolean
  enabled?: boolean
  activation_generation?: number
  recording_start?: string | null
}

export interface ReferenceWindow {
  since: string
  through: string
  cutoff?: string | null
}

export interface ReferenceTradeView {
  reference_trade_id: string
  status: string
  entry_bar_end: string
  entry_trading_day: string
  entry_reference_price: string
  exit_bar_end: string | null
  exit_reference_price: string | null
  reference_return: string | null
  [field: string]: unknown
}

export interface ReferencePage<Item> {
  items: Item[]
  snapshot: string
  next_cursor: string | null
  revision_id: string
  seq: number
  window: { since: string; through: string }
  cutoff: string | null
  status: string
  coverage?: { first_computed_through: string | null; computed_through: string | null; observation_boundary_at?: string | null; complete_window_proven: boolean }
}

export interface ReferenceSummary {
  snapshot: string
  closed_count: number
  open_count: number
  interrupted_count: number
  initial_count: number
  win_count: number
  loss_count: number
  flat_count: number
  win_rate_pct: string | null
  mean_return_pct: string | null
  sum_return_percentage_points: string | null
  statistics_policy: string
}

export interface ReferencePoint {
  kind: string
  trading_day: string
  formula_versions: string[]
  value: Record<string, unknown>
}

export interface MarketAfterCloseReference extends ReferenceWindow {
  receipt?: string
  cutoff: string
  stream_id: string
  revision_id: string
  seq: number
  computed_at: string
}

export interface MarketAfterCloseFrame {
  product: string
  strategy: string
  frequency: string
  trading_day: string
  bar_end: string
  physical_contract: string
  calculation_segment_id: string
  source_bar_sha256: string
  formula_versions: string[]
  main_state: string
  main_values: Record<string, string | null>
  availability?: { status?: string; reason_code?: string }
  actions: { kind: string; signal_id?: string; source_signal_id?: string; trade_eligibility?: string }[]
  hints: { kind?: string; hint_id?: string }[]
}

export interface MarketAfterClosePresentation {
  snapshot: string
  frames: MarketAfterCloseFrame[]
  main_status: 'saved' | 'not_materialized'
  auxiliary_status: 'not_materialized'
  explanation_status: 'not_materialized'
  comparator_status: 'not_materialized'
}

export type MarketAfterCloseSectionQuery = {
  identity: NewowProductIdentity
  asOf: string
} & (
  | { section: 'auxiliary'; component: NewowAuxiliaryComponent }
  | { section: 'comparator' }
)

export type MarketAfterCloseSection =
  | { status: 'pending' | 'unavailable'; receipt: string | null; chart: null; result: null }
  | {
      status: 'ready'
      receipt: string
      reference?: Pick<MarketAfterCloseReference, 'stream_id' | 'revision_id' | 'seq'>
      chart: NewowProductSectionResponse<'chart'>
      result: NewowProductSectionResponse<'auxiliary' | 'comparator'>
    }

export interface ReferenceIdentity {
  strategy: string
  product: string
  frequency: string
  mode?: ReferenceMode
}

export type NewowRecordingStrategy = 'trend' | 'oscillation' | 'main_rise' | 'dual_fusion'
export type NewowRecordingFrequency = '1w' | '1d' | '60m' | '5m' | '15m' | '30m'
export interface NewowRecordedState {
  version?: 'newow_bar_state_v1'
  main_state?: string
  availability?: { status: string; evidence_status?: string; reason_code?: string | null } | string
  bar_end?: string
  observed_at?: string
  physical_contract?: string
  main_values?: Record<string, unknown>
  [field: string]: unknown
}
export interface NewowRecordingItem {
  product: string
  strategy: NewowRecordingStrategy
  frequency: NewowRecordingFrequency
  stream_id: string | null
  enabled: boolean
  status: string
  computed_through: string | null
  historical_computed_through?: string | null
  observed_through?: string | null
  last_observed_at?: string | null
  latest_observed_trading_day?: string | null
  latest_state_source?: 'historical_seed' | 'observed' | null
  latest_reconciliation_status?: 'pending' | 'matched' | 'source_revised' | 'mismatch' | 'not_applicable' | null
  source_revision_count?: number
  source_revisions?: Array<{ capture_id: string; bar_end: string; policy_version: string; differences: Record<string, { observed: string; canonical: string }>; impact_status: string }>
  canonical_history?: { stream_id: string; status: string; revision_id: string | null; computed_through: string | null; expected_through: string | null; recording_mode: 'historical_replay'; source: 'canonical' } | null
  expected_through?: string | null
  expected_source?: 'canonical_completed' | 'completed_live'
  endpoint_status?: 'READY' | 'UNKNOWN'
  endpoint_reason?: string | null
  latest_state: NewowRecordedState | null
  recording_start?: string | null
  pending_capture_count?: number
  [field: string]: unknown
}
export interface NewowRecordingMatrix {
  version: 'newow_recording_matrix_v1' | 'newow_recording_matrix_v2' | 'newow_recording_matrix_v3' | 'newow_recording_matrix_v4'
  recording_mode: 'forward_observation'
  expected_count: number
  configured_count: number
  enabled_count: number
  observed_count: number
  seeded_count?: number
  items: NewowRecordingItem[]
}

export interface ForwardReferencePanel {
  version: 'forward_reference_panel_v1'
  page: ReferencePage<ReferenceTradeView> & { stream: ReferenceStreamInfo }
  summary: ReferenceSummary
  curve: { value: string; date: string; bar_end: string; reference_trade_id: string; segment: string }[]
  total_curve_points: number
  drawdown_percentage_points: string | null
}
