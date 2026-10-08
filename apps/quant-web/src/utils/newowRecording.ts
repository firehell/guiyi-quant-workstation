import type { NewowRecordedState, ReferencePoint, ReferenceWindow } from '../types/referenceTrading.ts'

const states: Record<string, string> = { BUILD: '建仓', HOLD: '持有', REDUCE: '减仓', CLEAR: '清仓', FLAT: '空仓', UNAVAILABLE: '状态不可用' }
export function recordingStatusLabel(status: string): string {
  return ({ not_configured: '未配置', disabled: '未启用', waiting_first_bar: '等待首根已完成 K 线', awaiting_first_bar: '等待首根已完成 K 线',
    waiting: '等待首根已完成 K 线', warming: '预热中', blocked: '记录阻断', ready: '正常记录', observed: '已有记录', stale_invalid: '记录阻断', unavailable: '不可用',
    observation_interrupted: '观察中断', pending: '等待处理' } as Record<string, string>)[status.toLowerCase()] ?? `待核对（${status}）`
}
export function recordingStateLabel(state: NewowRecordedState | null): string {
  if (!state) return '尚无已记录状态'
  const availability = typeof state.availability === 'string' ? state.availability : state.availability?.status
  if (!availability) return '状态可用性未记录'
  if (availability !== 'ready') return recordingStatusLabel(availability)
  if (!state.main_state) return '状态字段缺失'
  return states[state.main_state] ?? `未知状态（${state.main_state}）`
}
export function recordingPointLabel(point: ReferencePoint): string {
  if (point.value.version === 'newow_bar_state_v1') return recordingStateLabel(point.value as NewowRecordedState)
  const kind = String(point.value.kind ?? point.value.action ?? point.value.direction ?? point.kind)
  return states[kind] ?? ({ OPEN_LONG: '建仓', CLOSE_LONG: '清仓', J: 'J 风险提示', D1: 'D1 逃顶提示', D2: 'D2 逃顶提示', D3: 'D3 逃顶提示', D4: 'D4 低位修复提示', D5: 'D5 低位修复提示', D6: 'D6 低位修复提示', hint: '过程提示', signal: '策略信号' } as Record<string, string>)[kind] ?? kind
}
export function newowRecordingWindow(now: Date = new Date()): ReferenceWindow {
  const through = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  const start = new Date(`${through}T00:00:00Z`)
  start.setUTCDate(start.getUTCDate() - 90)
  return { since: start.toISOString().slice(0, 10), through }
}

export function newowRecordingIdentity(product: string, strategy: string, frequency: string,
  mode: import('../types/referenceTrading.ts').ReferenceMode): import('../types/referenceTrading.ts').ReferenceIdentity {
  return { product: product.toLowerCase(), strategy: strategy === 'dual_fusion' ? 'newow_dual_fusion' : `newow-${strategy.replaceAll('_', '-')}`, frequency, mode }
}

export function recordingItemStatus(item: { status: string; stream_id: string | null; enabled: boolean; latest_state: NewowRecordedState | null; latest_state_source?: string | null; observed_through?: string | null }): string {
  if (!item.stream_id) return '未配置'
  if (!item.enabled) return '未启用'
  if (item.status.toLowerCase() === 'ready' && (!item.latest_state || item.latest_state_source === 'historical_seed') && !item.observed_through) return '等待首根已完成 K 线'
  return recordingStatusLabel(item.status)
}

export function recordingReconciliationLabel(status: unknown): string {
  return ({ matched: '已匹配 Canonical', mismatch: '来源冲突', pending: '等待 Canonical 核对', not_applicable: '无需 Live 核对' } as Record<string, string>)[String(status)] ?? '待核对'
}
