export interface NewSubingMetadata {
  run_id: string
  product: 'AL' | 'RB' | 'TA'
  scenario: string
  status: string
  strategy_code: string
  initial_cash?: string
  account_model_version?: string
  formula_version: string
  profile_id: string
  risk_profile_version: string
  execution_profile_version: string
  code_revision: string
  requested_since: string
  requested_through: string
  input_snapshot_hash: string | null
  execution_facts_hash: string | null
  source: 'historical_replay'
  auto_order: false
  case_parity: string
  oos_status: string
}
export interface NewSubingProfile {
  strategy_code: string
  formula_version?: string
  account_model_version?: string | null
  profile_id: string
  product: string
  initial_cash: string
  validation_status: string
  rules: Record<string, unknown>
}
export interface NewSubingProfiles {
  strategy_code: string
  profiles: NewSubingProfile[]
  case_parity: string
  oos_status: string
  auto_order: false
}
export interface NewSubingRunDetail {
  metadata: NewSubingMetadata
  summary: Record<string, unknown> & { status: string }
  diagnostics: Record<string, unknown>
}
export interface NewSubingPage {
  items: Array<Record<string, unknown>>
  next_cursor: string | null
  run_id: string
  sha256: string
}

export interface NewSubingEquityCurve {
  run_id: string
  sha256: string
  items: Array<Record<string, unknown>>
  total: number
  sampled: boolean
  sampling_version: string
  since: string
  through: string
  status: string
}
