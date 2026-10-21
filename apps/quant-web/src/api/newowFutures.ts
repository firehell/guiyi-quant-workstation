import request from './request'
import type { FuturesSnapshot, FuturesPage, FuturesPart } from '../types/newowFutures.ts'
import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import { futuresVariant } from '../utils/newowFutures.ts'
const prefix = '/research/newow-futures'
/** Read frozen packets only. This API never launches research or computes strategy state. */
export function getFuturesSnapshot(identity: MarketDetailIdentity, signal?: AbortSignal) {
  return request.get<never, FuturesSnapshot>(`${prefix}/snapshot`, { signal, params: {
    product: identity.symbol, strategy: futuresVariant(identity), frequency: identity.frequency, scenario: 'baseline',
  } })
}
export function getFuturesPart(runId: string, sha256: string, part: FuturesPart, offset: number, signal?: AbortSignal) {
  return request.get<never, FuturesPage>(`${prefix}/runs/${encodeURIComponent(runId)}/${part}`, { signal, params: { sha256, offset, limit: 50 } })
}
export function getFuturesCurve(runId: string, sha256: string, kind: import('../types/newowFutures.ts').FuturesCurveKind, signal?: AbortSignal) {
  return request.get<never, import('../types/newowFutures.ts').FuturesCurve>(`${prefix}/runs/${encodeURIComponent(runId)}/equity-curve`, {signal,params:{sha256,kind,max_points:2000}})
}
