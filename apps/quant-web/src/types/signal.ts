/** 交易信号 */
export interface SignalRecord {
  signalId: string
  strategyId: string
  strategyName: string
  symbol: string
  direction: 'long' | 'short' | 'close'
  price: number
  volume: number
  signalTime: string
  reason: string
  confidence: number
}

export interface SignalScanRequest {
  watchlist_code: string
  periods: string[]
  symbols?: string[]
  provider?: string
  data_role?: 'primary' | 'validation' | 'legacy_reference'
  research_only?: boolean
  account_equity: number
  risk_per_trade_pct: number
  max_margin_usage_pct: number
  min_score_bucket: number
  allow_warning_quality: boolean
  strategy_params?: Record<string, unknown>
}

export interface SignalScanTask {
  id: number
  task_no: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'partial_failed'
  progress: number
  watchlist_code: string
  periods: string[]
  total_items: number
  completed_items: number
  failed_items: number
  skipped_items: number
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  result_payload: Record<string, unknown>
}

export type SignalLifecycleStatus = 'new' | 'viewed' | 'ignored' | 'watching' | 'expired'

export interface StrategySignalRecord {
  id: number
  task_no?: string | null
  strategy_id: string
  strategy_version_id: string
  strategy_name: string
  strategy_version: string
  strategy_code?: string
  watchlist_code?: string | null
  symbol: string
  contract: string
  exchange?: string | null
  interval: string
  period: string
  signal_time: string
  status: SignalLifecycleStatus
  strategy_status: string
  direction: 'long' | 'short' | 'neutral'
  signal_type: string
  price: number
  signal_price?: number
  entry_interval?: string
  daily_direction?: string | null
  entry_reason?: string | null
  no_signal_reason?: string | null
  max_hold_bars?: number | null
  strength_score: number
  signal_level: number
  score_bucket: 0 | 51 | 60 | 70 | 80
  bucket_label: string
  reason: string
  current_price: number
  target_price?: number | null
  stop_loss_price?: number | null
  risk_reward_ratio?: number | null
  open_volume: number
  margin_required: number
  risk_amount: number
  account_equity: number
  reasons: string[]
  data_role: 'primary' | 'validation' | 'legacy_reference' | string
  research_only: boolean
  features: Record<string, unknown>
  quality_status: Record<string, unknown>
  research_contract: boolean
  spec_source?: string | null
  alert_status: 'unread' | 'acknowledged' | string
  created_at?: string | null
  updated_at?: string | null
}

export interface SignalWsEvent {
  type: 'snapshot' | 'signal_created' | 'signal_changed' | 'scan_started' | 'scan_completed' | 'scan_failed'
  data: StrategySignalRecord | StrategySignalRecord[] | SignalScanTask | Record<string, unknown>
}
