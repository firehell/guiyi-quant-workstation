import type { RuntimeHealth, RuntimeStatus } from '@/types/runtime'

/** Naive UI Tag 组件的类型映射 */
export type RuntimeTagType = 'default' | 'success' | 'warning' | 'error' | 'info'

/**
 * 将运行时健康状态映射为 Tag 展示类型。
 */
export function runtimeStatusType(status: RuntimeStatus | null | undefined): RuntimeTagType {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'ok') return 'success'
  if (normalized === 'degraded') return 'warning'
  if (normalized === 'failed') return 'error'
  if (normalized === 'unknown') return 'default'
  return 'default'
}

/**
 * 格式化延迟毫秒数；小于 10ms 保留两位小数。
 */
export function formatLatencyMs(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  const decimals = value < 10 ? 2 : 1
  return `${value.toFixed(decimals)} ms`
}

/**
 * 格式化滞后秒数为可读时长（秒 / 分秒 / 时分）。
 */
export function formatLagSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  if (value < 60) return `${Math.max(0, Math.round(value))}s`
  if (value < 3600) {
    const minutes = Math.floor(value / 60)
    const seconds = Math.round(value % 60)
    return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`
  }
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`
}

/**
 * 格式化 ISO 日期时间为 zh-CN 本地化字符串。
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * 将计数字典格式化为「key: value」逗号分隔字符串。
 */
export function formatCountMap(counts: Record<string, number> | null | undefined): string {
  if (!counts || Object.keys(counts).length === 0) return '-'
  return Object.entries(counts)
    .sort(([first], [second]) => first.localeCompare(second))
    .map(([key, value]) => `${key}: ${value}`)
    .join(', ')
}

/**
 * 生成只读模式标志摘要，用于展示 runtime 是否处于安全只读状态。
 */
export function readonlyFlagSummary(payload: Pick<RuntimeHealth, 'readonly' | 'would_start_services' | 'would_enqueue_jobs' | 'would_send_notifications'>) {
  return [
    { label: 'readonly', value: payload.readonly, expected: true },
    { label: 'would_start_services', value: payload.would_start_services, expected: false },
    { label: 'would_enqueue_jobs', value: payload.would_enqueue_jobs, expected: false },
    { label: 'would_send_notifications', value: payload.would_send_notifications, expected: false },
  ]
}

function latestTimestamp(values: Array<string | null | undefined>): string | null {
  return values.filter((value): value is string => Boolean(value)).sort().at(-1) || null
}

/**
 * 将 Runtime 恢复相关事实压缩成只读摘要；不建议或触发自动恢复动作。
 */
export function buildRuntimeRecoverySummary(
  payload: Pick<RuntimeHealth, 'status' | 'components'>,
) {
  const components = payload.components
  const afterMarket = components.after_market_scheduler
  const scheduler = afterMarket?.scheduler_heartbeat
  const checkpoints = [
    ...(components.live_checkpoints.recent_ingest || []),
    ...(components.live_checkpoints.recent_aggregation || []),
  ]
  const watermark = latestTimestamp(checkpoints.map((row) => row.last_bar_at))
  const lastSuccess = latestTimestamp([
    components.live_checkpoints.latest_success_at,
    components.archive?.latest_finished_at,
  ])
  const latestCheckpointError = components.live_checkpoints.latest_error
  const error =
    afterMarket?.last_error_type ||
    afterMarket?.error_type ||
    (typeof latestCheckpointError?.error_type === 'string'
      ? latestCheckpointError.error_type
      : null) ||
    components.rq.error_type ||
    components.db.error_type ||
    components.redis.error_type ||
    'none'

  return {
    heartbeat: scheduler?.heartbeat_at || null,
    heartbeatAge: formatLagSeconds(scheduler?.heartbeat_age_seconds),
    watermark: watermark || 'unavailable',
    lastSuccess: lastSuccess || 'unavailable',
    error,
    nextRetry: afterMarket?.next_retry_at || components.notification_retry.next_retry_at || null,
    recovery: afterMarket?.next_retry_at
      ? '已安排有限重试；本页仅观察，不触发恢复。'
      : payload.status === 'ok'
        ? '当前无需恢复操作；继续只读观察。'
        : '未声明自动恢复；请按既有运维流程核对错误与 checkpoint。',
  }
}
