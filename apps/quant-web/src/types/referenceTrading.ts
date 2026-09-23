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

export interface ReferenceIdentity {
  strategy: string
  product: string
  frequency: string
  mode?: ReferenceMode
}
