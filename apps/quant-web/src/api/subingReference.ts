import request from './request'
import type { SubingReferenceQuery } from '@/types/subingReference'
export function getSubingReference(symbol: string, params: SubingReferenceQuery = {}, signal?: AbortSignal) {
  return request.get<never, unknown>(`/market/${encodeURIComponent(symbol)}/subing/reference`, { params, signal })
}
