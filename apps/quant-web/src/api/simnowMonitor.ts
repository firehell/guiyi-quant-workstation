export type MonitorKind = 'all' | 'signal' | 'risk' | 'order' | 'fill'
export interface MonitorQuery { kind: MonitorKind; product: string; status: string; startDay: string; endDay: string }
export interface MonitorRecord { id: string; kind: Exclude<MonitorKind, 'all'>; at: string; product: string; contract: string; status: string; label: string; signal_id: string | null; order_id: string | null; facts: Record<string, string | null> }
export interface MonitorPage { version: string; snapshot: string | null; items: MonitorRecord[]; next_cursor: string | null; available_count: number; coverage: 'complete' | 'partial' | 'unavailable' }
export interface MonitorDetail { version: string; snapshot: string; selected: MonitorRecord; chain: MonitorRecord[] }
export interface MonitorPosition { id: string; product: string; contract: string; side: string; quantity: number; today: number | null; yesterday: number | null; frozen_long: number; frozen_short: number; position_profit: string | null; status: string; as_of: string }
export interface MonitorIssue { id: string; code: string; label: string; at: string; product: string; contract: string; link: string | null }
export type MonitorMetric = 'equity' | 'available' | 'used_margin' | 'frozen_margin' | 'frozen_fee' | 'margin_limit' | 'occupied_margin' | 'margin_ratio' | 'local_reserved_margin' | 'local_reserved_fee' | 'daily_fee' | 'attributed_fee' | 'net_profit' | 'return_ratio'
export interface MonitorOverview {
  version: string; status: 'available' | 'partial' | 'not_connected' | 'unavailable'; snapshot: string | null; generated_at: string
  account: { key: string; alias: string; environment: string; strategy: string; scope_product: string | null; policy_version: string } | null
  observer: { status: 'running' | 'stopped' | 'error' | 'stale'; stage: string; published_at: string; connection: string; mode?: 'observe' | 'manage' | 'trade' | null; opening_enabled?: boolean; host_status?: string | null } | null
  readback_at: string | null; trading_day: string | null; readback_status: string; position_projection_complete: boolean
  metrics: Record<MonitorMetric, string | null>; positions: MonitorPosition[]; curve: { at: string; equity: string; net_profit: string | null; trading_day: string }[]
  issues: MonitorIssue[]; issue_count: number | null; coverage: string; performance_status: string; source_times: Record<string, string>
}
const version = 'simnow_monitor_v1'
const instant = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v))
const money = (v: unknown) => v === null || typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v) && Number.isFinite(Number(v))
export function validateOverview(value: MonitorOverview): MonitorOverview {
  if (!value || value.version !== version || !['available', 'partial', 'not_connected', 'unavailable'].includes(value.status) || !instant(value.generated_at)
    || !value.metrics || Object.values(value.metrics).some(v => !money(v)) || !Array.isArray(value.positions) || !Array.isArray(value.curve) || !Array.isArray(value.issues)
    || typeof value.position_projection_complete !== 'boolean' || value.curve.some(v => !instant(v.at) || !money(v.equity) || !money(v.net_profit))
    || (['available', 'partial'].includes(value.status) && (!value.account || !value.snapshot || !value.observer || !instant(value.readback_at)))
    || (value.observer?.mode != null && !['observe', 'manage', 'trade'].includes(value.observer.mode))
    || (value.observer?.opening_enabled !== undefined && typeof value.observer.opening_enabled !== 'boolean')
    || (value.observer?.opening_enabled === true && value.observer.mode !== 'trade')) throw Error('MONITOR_RESPONSE_INVALID')
  return value
}
export function validatePage(value: MonitorPage): MonitorPage {
  if (!value || value.version !== version || !Array.isArray(value.items) || !Number.isInteger(value.available_count) || value.available_count < 0
    || new Set(value.items.map(r => r.id)).size !== value.items.length || value.items.some(r => !r.id || !instant(r.at) || !['signal', 'risk', 'order', 'fill'].includes(r.kind))) throw Error('MONITOR_RESPONSE_INVALID')
  return value
}
export function validateDetail(value: MonitorDetail): MonitorDetail {
  if (!value || value.version !== version || !value.selected?.id || !Array.isArray(value.chain) || !value.chain.some(r => r.id === value.selected.id)) throw Error('MONITOR_RESPONSE_INVALID')
  return value
}
export const monitorClient = {
  async overview(signal: AbortSignal) { const { default: request } = await import('./request.ts'); return validateOverview(await request.get<never, MonitorOverview>('/api/simnow/monitor/overview', { signal, readPriority: 0 })) },
  async records(query: MonitorQuery, signal: AbortSignal, cursor?: string) { const { default: request } = await import('./request.ts'); return validatePage(await request.get<never, MonitorPage>('/api/simnow/monitor/records', { signal, params: { kind: query.kind, product: query.product, status: query.status, start_day: query.startDay, end_day: query.endDay, ...(cursor ? { cursor } : {}) } })) },
  async detail(id: string, signal: AbortSignal) { const { default: request } = await import('./request.ts'); return validateDetail(await request.get<never, MonitorDetail>('/api/simnow/monitor/records/' + encodeURIComponent(id), { signal })) },
}
export type MonitorClient = typeof monitorClient
export function monitorQueryKey(q: MonitorQuery) { return JSON.stringify([q.kind, q.product, q.status, q.startDay, q.endDay]) }
