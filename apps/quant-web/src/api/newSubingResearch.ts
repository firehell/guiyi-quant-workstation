import request from './request'
import { newowSessionResources } from '../utils/newowSessionResources.ts'
import type { NewSubingEquityCurve, NewSubingMetadata, NewSubingPage, NewSubingProfiles, NewSubingRunDetail } from '@/types/newSubingResearch'

const prefix = '/research/new-subing'
export function getNewSubingProfiles(signal?: AbortSignal) {
  return request.get<never, NewSubingProfiles>(`${prefix}/profiles`, { signal })
}
export function getNewSubingRuns(signal?: AbortSignal) {
  return request.get<never, { runs: NewSubingMetadata[] }>(`${prefix}/runs`, { signal })
}
export function getNewSubingRun(runId: string, signal?: AbortSignal) {
  return request.get<never, NewSubingRunDetail>(`${prefix}/runs/${encodeURIComponent(runId)}`, { signal })
}
type PageOptions = { signal?: AbortSignal; sha256?: string }
function resultKey(runId: string, sha256: string) {
  return `research-v1:${request.defaults.baseURL}:${runId}:${sha256}`
}
function verified<T extends { run_id: string; sha256: string }>(value: T, runId: string, sha256: string): T {
  if (value.run_id !== runId || value.sha256 !== sha256) throw new Error('研究结果身份不一致')
  return value
}
export function getNewSubingPage(runId: string, kind: 'decisions' | 'trades' | 'equity', cursor?: string | null, options: PageOptions = {}) {
  const fetch = (signal?: AbortSignal) => request.get<never, NewSubingPage>(`${prefix}/runs/${encodeURIComponent(runId)}/${kind}`, { signal, params: { limit: 50, ...(cursor ? { cursor } : {}) } })
  // The first selected page is a fresh proof. Reuse only pages pinned to its verified frozen hash.
  if (!options.sha256) return fetch(options.signal)
  const sha = options.sha256
  return newowSessionResources.load(`${resultKey(runId, sha)}:${kind}:${cursor ?? ''}`,
    async signal => verified(await fetch(signal), runId, sha), value => `${value.run_id}:${value.sha256}`, options.signal)
}

export function getNewSubingEquityCurve(runId: string, sha256: string, signal?: AbortSignal) {
  return newowSessionResources.load(`${resultKey(runId, sha256)}:curve`, async transport => verified(await request.get<never, NewSubingEquityCurve>(`${prefix}/runs/${encodeURIComponent(runId)}/equity-curve`, { signal: transport, params: { sha256, max_points: 2000 } }), runId, sha256), value => `${value.run_id}:${value.sha256}`, signal)
}
