import type { MonitorOverview } from '../api/simnowMonitor.ts'
export function monitorTime(value: string | null | undefined) {
  if (!value || !Number.isFinite(Date.parse(value))) return '—'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value))
}
export function monitorMoney(value: string | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: Number(value) !== 0 && Math.abs(Number(value)) < .01 ? 8 : 2 })
}
export function monitorPercent(value: string | null | undefined) { return value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(1)}%` }
export function observerLabel(data: MonitorOverview | null) {
  if (!data?.account) return '尚未接入监控'
  return ({ running: '受控运行中', stopped: '本次运行已结束', stale: '运行状态待确认', error: '本次运行异常' } as const)[data.observer?.status ?? 'stale']
}
export const monitorReason: Record<string, string> = { APPROVED: '资金与保证金检查通过', MARGIN_CAP: '预计保证金占用超过70%上限，本次信号跳过', AVAILABLE_FUNDS: '可用资金不足，本次信号跳过', MINIMUM_OPEN_VOLUME: '合约不支持固定一手开仓', TARGET_UPDATED: '已更新目标方向', HOLD: '没有新信号，保持仓位', FROZEN_BAR_IGNORED: '同一Bar已冻结，未重复执行', SIGNAL_CONFLICT: '同一Bar出现双向信号，不开仓或反手', PRE_ACTIVATION_OR_RECOVERY_IGNORED: '启用前或恢复期间的旧信号不补开', OBSERVATION_GAP: '自然输入不连续，暂停新开仓', OWNER_MISMATCH: '主力合约不匹配，暂停新开仓', SIGNAL_BLOCKED: '该品种输入或账户状态待核' }
export function curveGeometry(points: MonitorOverview['curve'], field: 'equity' | 'net_profit') {
  const usable = points.filter(p => p[field] !== null && Number.isFinite(Number(p[field])))
  if (!usable.length) return { segments: [] as string[], dots: [] as { x: number; y: number; at: string; value: string }[], min: null as string | null, max: null as string | null }
  const values = usable.map(p => Number(p[field])), low = Math.min(...values), high = Math.max(...values)
  const pad = Math.max((high - low) * .15, Math.abs(high) * .0001, .01), min = low - pad, max = high + pad
  const start = Date.parse(points[0]!.at), end = Date.parse(points.at(-1)!.at), duration = Math.max(1, end - start)
  const segments: string[] = [], dots: { x: number; y: number; at: string; value: string }[] = []
  let current = '', day: string | null = null
  for (const point of points) {
    const value = point[field]
    if (value === null || !Number.isFinite(Number(value))) { if (current) segments.push(current); current = ''; day = null; continue }
    if (field === 'net_profit' && day !== null && day !== point.trading_day) { if (current) segments.push(current); current = '' }
    const x = points.length === 1 ? 500 : 70 + (Date.parse(point.at) - start) / duration * 900
    const y = 165 - (Number(value) - min) / (max - min) * 140
    current += `${current ? ' L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`
    dots.push({ x, y, at: point.at, value }); day = point.trading_day
  }
  if (current) segments.push(current)
  return { segments, dots, min: String(min), max: String(max) }
}
