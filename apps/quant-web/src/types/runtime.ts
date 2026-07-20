export type RuntimeStatus = 'ok' | 'degraded' | 'failed' | 'unknown' | string

export interface RuntimeComponentHealth {
  status: RuntimeStatus
  latency_ms?: number | null
  error_type?: string | null
  error_message?: string | null
}

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

export interface RuntimeRqWorkerHealth {
  name: string
  state?: string | null
  queues: string[]
}

export interface RuntimeRqHealth {
  status: RuntimeStatus
  queues: RuntimeRqQueueHealth[]
  worker_count: number
  workers: RuntimeRqWorkerHealth[]
  error_type?: string | null
  error_message?: string | null
}

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

export interface RuntimeLiveCheckpointsHealth {
  status: RuntimeStatus
  enabled?: boolean
  freshness_seconds?: number
  stale?: boolean
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

export interface RuntimeSchedulerHealth {
  status: RuntimeStatus
  enabled?: boolean
  heartbeat_at?: string | null
  heartbeat_age_seconds?: number | null
  last_cycle_status?: string | null
  error_type?: string | null
  error_message?: string | null
}

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

export interface RuntimeHealthComponents {
  db: RuntimeComponentHealth
  redis: RuntimeComponentHealth
  rq: RuntimeRqHealth
  live_checkpoints: RuntimeLiveCheckpointsHealth
  notification_retry: RuntimeNotificationRetryHealth
  scheduler?: RuntimeSchedulerHealth
  archive?: RuntimeArchiveHealth
}

export interface RuntimeHealth {
  status: RuntimeStatus
  generated_at: string
  readonly: boolean
  would_start_services: boolean
  would_enqueue_jobs: boolean
  would_send_notifications: boolean
  components: RuntimeHealthComponents
}
