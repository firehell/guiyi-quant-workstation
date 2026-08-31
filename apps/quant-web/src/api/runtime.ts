import request from './request'

export interface RuntimeComponentHealth {
  status: string
  latency_ms: number | null
  error_type: string | null
  error_message: string | null
}

export interface RuntimeLiveMarketHealth {
  status: string
  configured_enabled: boolean
  operational_count: number
  subscribed_count: number
  last_heartbeat_at: string | null
  last_bar_at: string | null
  phase_counts: Record<string, number>
  error_type: string | null
  error_message: string | null
}

export interface RuntimeAfterMarketFailureNotification {
  attempted_at: string
  state: 'provider_accepted' | 'failed'
  error_type: string | null
}

export interface RuntimeAfterMarketRun {
  trading_day: string
  status: string
  attempts: number
  started_at: string
  finished_at: string
  products: string[]
  error_code: string | null
  failure_notification: RuntimeAfterMarketFailureNotification | null
}

export interface RuntimeAfterMarketCurrentRun {
  scheduled_date: string
  started_at: string
  products: string[]
}

export interface RuntimeAfterMarketHealth {
  status: string
  configured_enabled: boolean
  run_state: string
  expected_trading_day: string | null
  current_run: RuntimeAfterMarketCurrentRun | null
  last_run: RuntimeAfterMarketRun | null
  last_successful_trading_day: string | null
  last_failure: Record<string, string> | null
  error_type: string | null
  error_message: string | null
}

export interface RuntimeAlertNotificationHealth {
  transport: string
  configured: boolean
  audience_count: number
  would_send: boolean
}

export interface RuntimeAlertHealth {
  status: string
  configured_enabled: boolean
  notification: RuntimeAlertNotificationHealth
  last_heartbeat_at: string | null
  enabled_rule_count: number
  scope_product_count: number
  processing_state: string
  notification_state: string
  last_processed_bar_at: string | null
  last_processing_success_at: string | null
  last_processing_failure_at: string | null
  processing_error_type: string | null
  last_event_at: string | null
  last_transport_attempt_at: string | null
  last_provider_accepted_at: string | null
  last_notification_failure_at: string | null
  notification_error_type: string | null
  consecutive_notification_failures: number
  strategy_state: 'warming' | 'ready' | 'degraded'
  strategy_started_at: string | null
  strategy_ready_at: string | null
  strategy_product_count: number
  strategy_ready_product_count: number
  strategy_unavailable_product_count: number
  strategy_unavailable_symbols: string[]
  strategy_unavailable_reason_codes: Record<string, string>
  last_strategy_action_at: string | null
  last_strategy_restore_at: string | null
  error_type: string | null
}

export interface RuntimeHealthResponse {
  status: string
  generated_at: string
  readonly: boolean
  would_start_services: boolean
  would_enqueue_jobs: boolean
  would_send_notifications: boolean
  components: {
    db: RuntimeComponentHealth
    redis: RuntimeComponentHealth
    live_market: RuntimeLiveMarketHealth
    after_market: RuntimeAfterMarketHealth
    alert: RuntimeAlertHealth
  }
}

export function getRuntimeHealth() {
  return request.get<never, RuntimeHealthResponse>('/api/runtime/health')
}
