import type { AlertEvent, AlertRuleCode } from '../types/market.ts'
import type { NewowMessage } from './newowMessages.ts'
export interface UnifiedMessageQuery { startDay: string; endDay: string; symbol: string; source: 'all' | 'alert' | 'newow'; ruleCode: AlertRuleCode | null; strategy: string; frequency: string; search: string }
export function messageQueryIdentity(query: UnifiedMessageQuery): string {
  return JSON.stringify([query.startDay, query.endDay, query.symbol, query.source, query.ruleCode, query.strategy, query.frequency, query.search])
}
export type UnifiedMessage = { source: 'alert'; id: string; bar_end: string; symbol: string; event: AlertEvent } | { source: 'newow'; id: string; bar_end: string; symbol: string; event: NewowMessage }
export interface UnifiedMessagePage { dataset_hash?: string; items: UnifiedMessage[]; next_cursor: string | null; available_count: number; coverage: 'complete' | 'partial'; snapshot: { cutoff: string; alert_max_id: number | null }; sources: Record<string, { status: 'ready' | 'unavailable'; truncated: boolean; limit: number; window_days?: number; scanned_count?: number; scan_batches?: number; excluded_streams?: number; scope?: string }> }
export async function getMarketMessages(query: UnifiedMessageQuery, signal: AbortSignal, cursor?: string): Promise<UnifiedMessagePage> {
  const { default: request } = await import('./request.ts')
  return request.get<never, UnifiedMessagePage>('/api/market/messages', { signal, params: { start_day: query.startDay, end_day: query.endDay, source: query.source, ...(query.symbol ? { symbol: query.symbol } : {}), ...(query.ruleCode ? { rule_code: query.ruleCode } : {}), ...(query.strategy ? { strategy: query.strategy } : {}), ...(query.frequency ? { frequency: query.frequency } : {}), ...(query.search.trim() ? { search: query.search.trim() } : {}), ...(cursor ? { cursor } : {}) } })
}
