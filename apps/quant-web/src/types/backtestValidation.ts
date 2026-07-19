export interface BacktestValidationFold {
  fold_id: string
  status?: string | null
  audit_status?: string | null
  trade_count?: number | null
  total_return_pct?: number | null
  metrics?: Record<string, unknown>
  numeric_reasons?: string[]
  structural_reasons?: string[]
  overlay_scenario_count?: number
  cost_sensitivity?: Record<string, unknown>
  diagnostics?: Record<string, unknown>
  fold_hash?: string | null
}

export interface BacktestValidationContext {
  schema_version: 'backtest_validation_context_x506b_v1'
  report_id: number
  candidate_status: string
  review_skip_status: string
  candidate: Record<string, unknown>
  oos: {
    window_id?: string | null
    gate?: string | null
    metrics?: Record<string, unknown>
    row_counts?: Record<string, unknown>
    hard_reject?: {
      triggered?: boolean
      numeric_reasons?: string[]
      structural_reasons?: string[]
    }
  }
  rolling_oos: {
    mode?: string | null
    proposal_label?: string | null
    x504_hard_reject_preserved?: boolean
    folds?: BacktestValidationFold[]
  }
  hard_reject_reason: string
  binding_identity: Record<string, unknown>
  policy?: Record<string, unknown>
  evidence_hashes: Record<string, unknown>
  source_policy?: Record<string, unknown>
  context_hash: string
}
