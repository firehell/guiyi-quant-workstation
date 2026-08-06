/** 运行时组件/任务状态 */
export type RuntimeStatus = 'ok' | 'degraded' | 'failed' | 'unknown' | string

/** 单组件健康快照（DB、Redis 等） */
export interface RuntimeComponentHealth {
  status: RuntimeStatus
  latency_ms?: number | null
  error_type?: string | null
  error_message?: string | null
}

/** RQ 队列健康状态 */
export interface RuntimeRqQueueHealth {
  name: string
  status: RuntimeStatus
  queued_count: number
  started_count: number
  failed_count: number
  deferred_count: number
  scheduled_count: number
  error_type?: string | null
}

/** RQ Worker 健康状态 */
export interface RuntimeRqWorkerHealth {
  name: string
  state?: string | null
  queues: string[]
}

/** RQ 任务队列整体健康 */
export interface RuntimeRqHealth {
  status: RuntimeStatus
  queues: RuntimeRqQueueHealth[]
  worker_count: number
  workers: RuntimeRqWorkerHealth[]
  error_type?: string | null
  error_message?: string | null
}

/** Live 数据 checkpoint 单行记录 */
export interface RuntimeCheckpointRow {
  id: number
  provider: string
  instrument_symbol: string
  contract_code: string
  period: string
  source_mode: string
  status: RuntimeStatus
  lag_seconds?: number | null
  consecutive_error_count: number
  last_success_at?: string | null
  last_run_at?: string | null
  last_bar_at?: string | null
  last_error_type?: string | null
  updated_at?: string | null
}

/** Live checkpoint 采集与聚合健康 */
export interface RuntimeLiveCheckpointsHealth {
  status: RuntimeStatus
  enabled?: boolean
  freshness_seconds?: number
  stale?: boolean
  polling_expected?: boolean
  market_phase?: string
  ingest_count: number
  aggregation_count: number
  status_counts: Record<string, number>
  latest_success_at?: string | null
  latest_error?: Record<string, unknown> | null
  recent_ingest: RuntimeCheckpointRow[]
  recent_aggregation: RuntimeCheckpointRow[]
  error_type?: string | null
  error_message?: string | null
}

/** 通知重试队列健康（企业微信等） */
export interface RuntimeNotificationRetryHealth {
  status: RuntimeStatus
  enabled?: boolean
  channel: string
  total_count: number
  retry_pending_count: number
  due_retry_count: number
  failed_count: number
  sent_count: number
  skipped_count: number
  pending_count: number
  next_retry_at?: string | null
  last_sent_at?: string | null
  last_failed_at?: string | null
  last_error_type_counts: Record<string, number>
  error_type?: string | null
  error_message?: string | null
}

/** Live 数据归档任务健康 */
export interface RuntimeArchiveHealth {
  status: RuntimeStatus
  enabled?: boolean
  latest_task_no?: string | null
  latest_task_status?: string | null
  latest_contract?: string | null
  latest_finished_at?: string | null
  latest_error_type?: string | null
  error_type?: string | null
  error_message?: string | null
}

/** 盘后增量归档调度器心跳详情 */
export interface RuntimeAfterMarketSchedulerHeartbeat {
  status?: string | null
  health_status?: RuntimeStatus | null
  heartbeat_at?: string | null
  heartbeat_age_seconds?: number | null
  error_type?: string | null
  lock_status?: string | null
}

/** 独立盘后增量归档调度器健康 */
export interface RuntimeAfterMarketSchedulerHealth {
  status: RuntimeStatus
  enabled: boolean
  last_successful_trading_day?: string | null
  latest_completed_trading_day?: string | null
  latest_eligible_trading_day?: string | null
  archive_lag_trading_days?: number | null
  current_task?: string | null
  last_error_type?: string | null
  last_error_at?: string | null
  retry_count: number
  scheduler_heartbeat?: RuntimeAfterMarketSchedulerHeartbeat | null
  active_binding_end?: string | null
  active_binding_ends: Array<Record<string, unknown>>
  next_retry_at?: string | null
  authorization_hash?: string | null
  lock_status?: string | null
  error_type?: string | null
  error_message?: string | null
}

/** 运行时各子组件健康集合 */
export interface RuntimeHealthComponents {
  db: RuntimeComponentHealth
  redis: RuntimeComponentHealth
  rq: RuntimeRqHealth
  live_checkpoints: RuntimeLiveCheckpointsHealth
  notification_retry: RuntimeNotificationRetryHealth
  archive?: RuntimeArchiveHealth
  after_market_scheduler?: RuntimeAfterMarketSchedulerHealth
}

/** 工作站运行时健康总览（只读观测，不触发启动） */
export interface RuntimeHealth {
  status: RuntimeStatus
  generated_at: string
  readonly: boolean
  would_start_services: boolean
  would_enqueue_jobs: boolean
  would_send_notifications: boolean
  components: RuntimeHealthComponents
}
