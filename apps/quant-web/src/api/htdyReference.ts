import request from './request'
import type { HtdyHistoricalResponse } from '@/types/htdyReference'
export function getHtdyReference(symbol: string, params: { frequency: string; since?: string; through?: string; as_of?: string; before?: string; limit?: number }, signal?: AbortSignal) {
  return request.get<never, HtdyHistoricalResponse>(`/market/${encodeURIComponent(symbol)}/htdy/reference`, { params, signal })
}
