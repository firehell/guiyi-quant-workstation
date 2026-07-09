import type { RuntimeHealth, RuntimeStatus } from '@/types/runtime'

export type RuntimeTagType = 'default' | 'success' | 'warning' | 'error' | 'info'

export function runtimeStatusType(status: RuntimeStatus | null | undefined): RuntimeTagType {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'ok') return 'success'
  if (normalized === 'degraded') return 'warning'
  if (normalized === 'failed') return 'error'
  if (normalized === 'unknown') return 'default'
  return 'default'
}

export function formatLatencyMs(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  const decimals = value < 10 ? 2 : 1
  return `${value.toFixed(decimals)} ms`
}

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

export function formatCountMap(counts: Record<string, number> | null | undefined): string {
  if (!counts || Object.keys(counts).length === 0) return '-'
  return Object.entries(counts)
    .sort(([first], [second]) => first.localeCompare(second))
    .map(([key, value]) => `${key}: ${value}`)
    .join(', ')
}

export function readonlyFlagSummary(payload: Pick<RuntimeHealth, 'readonly' | 'would_start_services' | 'would_enqueue_jobs' | 'would_send_notifications'>) {
  return [
    { label: 'readonly', value: payload.readonly, expected: true },
    { label: 'would_start_services', value: payload.would_start_services, expected: false },
    { label: 'would_enqueue_jobs', value: payload.would_enqueue_jobs, expected: false },
    { label: 'would_send_notifications', value: payload.would_send_notifications, expected: false },
  ]
}
