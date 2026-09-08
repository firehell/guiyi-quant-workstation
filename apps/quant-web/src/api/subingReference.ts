import request from './request'
import type { SubingReferenceQuery } from '@/types/subingReference'
export function getSubingReference(symbol: string, params: SubingReferenceQuery = {}) {
  return request.get<never, unknown>(`/api/v1/market/${encodeURIComponent(symbol)}/subing/reference`, { params })
}
