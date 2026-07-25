export interface HtdyObservationAlertRecord {
  id: number
  alert_key: string
  alert_policy: string
  indicator_code: string
  indicator_version: string
  strategy_name: string
  strategy_version: string
  symbol: string
  continuous_contract: string
  actual_contract: string
  dominant_mapping_date: string
  period: '15m'
  bar_end: string
  trigger_price: number
  direction: 'long' | 'short' | 'conflict'
  source_mode: 'live_confirmed_repainting_observation'
  provider: string
  data_role: string
  quality_status: string
  profile_id: string
  market_data_file_id: number
  live_bar_id: number
  live_bar_revision: number
  confirmed_at: string
  future_looking: true
  repainting_risk: 'known'
  alert_status: string
  notification_status: string
  payload: Record<string, unknown>
  created_at: string
}

export interface HtdyObservationAlertList {
  total: number
  items: HtdyObservationAlertRecord[]
}
