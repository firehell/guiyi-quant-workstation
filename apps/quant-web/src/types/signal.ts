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
  data_role?: 'primary'
  profile_id?: string
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
  profile_id?: string | null
  market_data_file_id?: number | null
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
  product?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
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
  data_role: 'primary' | string
  profile_id?: string | null
  market_data_file_id?: number | null
  profile_lineage?: Record<string, unknown> | null
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

export interface SignalEventRecord {
  id: number
  event_key: string
  event_type: string
  signal_id?: number | null
  task_no?: string | null
  source_mode: string
  strategy_name: string
  strategy_version: string
  watchlist_code?: string | null
  symbol: string
  contract: string
  product?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  dominant_mapping_date?: string | null
  exchange?: string | null
  period: string
  signal_time?: string | null
  bar_start?: string | null
  bar_end?: string | null
  trigger_price?: number | null
  provider?: string | null
  source?: string | null
  direction: string
  signal_status: string
  lifecycle_status: string
  score_bucket: number
  data_role: string
  profile_id?: string | null
  market_data_file_id?: number | null
  quality_status: Record<string, unknown>
  payload: Record<string, unknown>
  created_at?: string | null
}

export interface Stage9WechatPreview {
  allowed: boolean
  blocked_reasons: string[]
  would_send: boolean
  channel: string
  notification_recorded: boolean
  payload_basis: Record<string, unknown>
  wechat_payload?: Record<string, unknown> | null
}

export interface Stage9WechatNotification {
  id: number
  event_id?: number | null
  signal_id?: number | null
  task_no?: string | null
  dedupe_key: string
  event_type: string
  channel: string
  status: string
  payload: Record<string, unknown>
  error_message?: string | null
  attempt_count: number
  max_attempts: number
  last_attempt_at?: string | null
  next_retry_at?: string | null
  last_error_type?: string | null
  response_status_code?: number | null
  created_at?: string | null
  sent_at?: string | null
}

export interface LiveSignalEvaluationItem {
  strategy_code: string
  strategy_version: string
  symbol: string
  contract: string
  continuous_contract?: string | null
  actual_contract?: string | null
  dominant_mapping_date?: string | null
  entry_interval: string
  evaluated_at: string
  bar_time?: string | null
  bar_end?: string | null
  trigger_price?: number | null
  direction: string
  status: string
  daily_direction: string
  entry_reason?: string | null
  no_signal_reason?: string | null
  stop_loss_price?: number | null
  quality: Record<string, unknown>
  warnings: string[]
  reasons: string[]
  source: Record<string, unknown>
}

export interface LiveSignalEvaluationResponse {
  strategy_code: string
  strategy_version: string
  symbol: string
  contract: string
  continuous_contract?: string | null
  actual_contract?: string | null
  dominant_mapping_date?: string | null
  evaluated_at: string
  results: LiveSignalEvaluationItem[]
  quality_summary: Record<string, unknown>
  message?: string | null
}
