import type { ReferencePoint } from '../types/referenceTrading.ts'
export interface NewowMessage {
  id: string; stream_id: string; revision_id: string; symbol: string
  strategy: 'trend' | 'oscillation' | 'main_rise' | 'dual_fusion'
  frequency: '1w' | '1d' | '60m'; contract: string | null
  bar_end: string; trading_day: string; observed_at: string; point: ReferencePoint
  page_parity: true; executable: false
}
export interface NewowMessagePage { items: NewowMessage[]; truncated: boolean }
export async function getNewowMessages(params: { since: string; through: string; product?: string; strategy?: string; frequency?: string }, signal: AbortSignal): Promise<NewowMessagePage> {
  const { default: request } = await import('./request.ts')
  return request.get<never, NewowMessagePage>('/reference-trading/newow/messages', { params, signal })
}
export const newowMessageStrategies = [
  { value: 'trend', label: '趋势策略' }, { value: 'oscillation', label: '震荡策略' },
  { value: 'main_rise', label: '主升浪策略' }, { value: 'dual_fusion', label: '双策略' },
] as const
export function newowMessageChartQuery(event: NewowMessage) {
  return { view: 'newow', symbol: event.symbol, strategy: event.strategy === 'dual_fusion' ? 'trend' : event.strategy,
    series_kind: 'actual_dominant', frequency: event.frequency, ...(event.strategy === 'dual_fusion' ? { newow_mode: 'dual' } : {}) }
}
