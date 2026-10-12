import request from './request'
import type { NewSubingMetadata, NewSubingPage, NewSubingProfiles, NewSubingRunDetail } from '@/types/newSubingResearch'

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
