import request from './request'
import { newowSessionResources } from '../utils/newowSessionResources.ts'
import type { NewSubingEquityCurve, NewSubingMetadata, NewSubingPage, NewSubingProfiles, NewSubingRunDetail } from '@/types/newSubingResearch'

const prefix = '/research/new-subing'
export function getNewSubingProfiles() {
  return request.get<never, NewSubingProfiles>(`${prefix}/profiles`)
}
export function getNewSubingRuns() {
  return request.get<never, { runs: NewSubingMetadata[] }>(`${prefix}/runs`)
}
export function getNewSubingRun(runId: string) {
  return request.get<never, NewSubingRunDetail>(`${prefix}/runs/${encodeURIComponent(runId)}`)
}
export function getNewSubingPage(runId: string, kind: 'decisions' | 'trades' | 'equity', cursor?: string | null) {
  return request.get<never, NewSubingPage>(`${prefix}/runs/${encodeURIComponent(runId)}/${kind}`, { params: { limit: 50, ...(cursor ? { cursor } : {}) } })
}

export function getNewSubingEquityCurve(runId: string, sha256: string) {
  return newowSessionResources.load(`research-equity:${runId}:${sha256}`, signal => request.get<never, NewSubingEquityCurve>(`${prefix}/runs/${encodeURIComponent(runId)}/equity-curve`, { signal, params: { sha256, max_points: 2000 } }), () => `${runId}:${sha256}`)
}
