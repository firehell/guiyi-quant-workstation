export interface DecisionPriceSource {
  raw: string
  frequency: '1d' | '1w' | '60m' | '1M'
  bar_end: string
  physical_contract: string
  segment_id: string
  calculation_segment_id: string
  source_identity: string
  source_category: string
  display_value?: string
  support_cap_applied?: boolean
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
  adapter_version?: string
  care_input?: {status:string;value:boolean|null;window_size:number;bar_end:string|null;physical_contract:string|null;calculation_segment_id:string|null;contribution:number;formula_version:string|null}
  period_conflict?: {version: string; hit: boolean; code: 'XP1'|null; week_state: string; day_state: string}
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
  volatility_level?: 'low' | 'mid' | 'high' | null
  extra_sources: Record<string, string>
  missing_roles: string[]
  facts: { role: string; state: string | null; age: number; frequency: string; bar_end: string | null; physical_contract: string | null; segment_id: string | null; source_category: string; status: string; reason: string | null }[]
  presentation?: {
    version: string
    scope: 'daily_weekly' | 'daily_weekly_hourly'
    advice: string
    first_action: { rule_token: string; level: 'ok' | 'warn' | 'violate' | 'unknown'; title: string; detail: string; source_formula_version: string | null }
  }
}
export interface NewowDecisionV2 { cdv2: Cdv2; prices: CrossPeriodPrices | null; daily_weekly_path?: DailyWeeklyPath }

export interface DailyWeeklyPathPeriod {
  frequency: '1d' | '1w' | '60m'
  state: string | null
  status: 'ready' | 'partial' | 'unavailable'
  cost: (DecisionPriceSource & { entry_marker_id: string }) | null
  current: DecisionPriceSource | null
  target: DecisionPriceSource | null
  reason: string | null
  formula_versions?: string[]
}
export interface DailyWeeklyPath {
  history?: HistoricalPath
  version: string
  as_of: string
  page_parity: true
  executable: false
  source_note: string
  periods: DailyWeeklyPathPeriod[]
}

export interface HistoricalPath {
  version: 'newow_historical_path_v3402_v1'
  status: 'ready' | 'unavailable'
  reason: string | null
  axis_dates?: string[]
  buys: Array<{date:string;price:string}>
  sells: Array<{date:string;price:string}>
  background: Array<{start:string;end:string;state:'hold'|'flat'}>
  holding: boolean
  current: string | null
  target: string | null
  cost: string | null
  eta: null | {status:'ready'|'unavailable';reason:string|null;base?:number;remain?:number;elapsed?:number;ratio?:number;samples?:number;overdue?:boolean;date?:string;date_limited?:boolean;unit?:string;from_price?:string;to_price?:string}
  source?: {physical_contract:string;segment_id:string;calculation_segment_id:string;bar_end:string;as_of:string;strategy:string;price_source:string;background_status:string}
  page_parity:true
  executable:false
}
