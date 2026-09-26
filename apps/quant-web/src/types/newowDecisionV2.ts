export interface DecisionPriceSource {
  raw: string
  frequency: '1d' | '1w' | '1M'
  bar_end: string
  physical_contract: string
  segment_id: string
  calculation_segment_id: string
  source_identity: string
  source_category: string
  display_value?: string
  branch?: string
}
export interface CrossPeriodPrices {
  formula_version: string
  as_of: string
  period: string
  source_family: string
  daily_signal: string | null
  weekly_signal: string | null
  current_price: DecisionPriceSource
  previous_close: DecisionPriceSource | null
  guard_status: string
  shared: { target: DecisionPriceSource | null; absorb: DecisionPriceSource | null }
  status_card: { target: DecisionPriceSource | null; absorb: DecisionPriceSource | null }
  monthly_target_available: boolean
  source_note: string
}
export interface Cdv2 {
  formula_version: string
  as_of: string
  total: number
  action: string
  action_code: string
  resonance: string
  mismatch: string | null
  mismatch_age: number
  trend_bias: string
  oscillation_bias: string
  trend_state: Record<string, string>
  oscillation_state: Record<string, string>
  scores: Record<string, number>
  deductions: Record<string, number>
  cert_extra: number
  certainty_cap: number
  resonance_cap: number
  reference_exposure_cap: number
  reference_exposure_range: string
  volatility_pct: string | null
  extra_sources: Record<string, string>
  missing_roles: string[]
  facts: { role: string; state: string | null; age: number; frequency: string; bar_end: string | null; physical_contract: string | null; segment_id: string | null; source_category: string; status: string; reason: string | null }[]
}
export interface NewowDecisionV2 { cdv2: Cdv2; prices: CrossPeriodPrices | null }
