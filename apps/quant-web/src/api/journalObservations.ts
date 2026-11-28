import request from './request'
import type { MarketFrequency } from '@/types/market'
import type { Period } from './tradeJournal'

export interface ObservationPane {
  id: string
  frequency: MarketFrequency
  series_kind: 'contract' | 'actual_dominant'
  physical_contract: string
  window: { from: string; to: string }
  source: Record<string, unknown>
  indicators: {
    id: string
    version: string | null
    cutoff: string | null
    parameters: Record<string, unknown>
    source: Record<string, unknown>
  }[]
  drawings: Record<string, unknown>[]
  ranges: Record<string, unknown>
}

export interface ObservationSnapshot {
  schema_version: 1
  captured_at: string
  product: string
  physical_contract: string
  panes: ObservationPane[]
  active_pane: string
  layout: string
}

export interface ObservationInput {
  note: string
  trading_day: string
  snapshot: ObservationSnapshot
}

export interface ObservationRow {
  id: string
  trading_day: string
  note: string
  product: string
  physical_contract: string
  frequency: MarketFrequency
  captured_at: string
  recorded_at: string
}

const root = '/trade-journal/observations'
const observationPath = (id: string) => root + '/' + encodeURIComponent(id)

export async function saveObservation(id: string, input: ObservationInput, png: Blob) {
  if (png.type !== 'image/png' || !png.size || png.size > 6 * 1024 * 1024) throw new Error('原图须为 6 MiB 以内的 PNG 文件')
  const image = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1]!)
    reader.onerror = () => reject(new Error('无法读取图表原图'))
    reader.readAsDataURL(png)
  })
  return request.put<unknown, {id: string}>(observationPath(id), { ...input, image }, {
    headers: { 'Idempotency-Key': id },
  })
}

export const listObservations = (anchor: string, period: Period, offset: number, signal: AbortSignal) =>
  request.get<unknown, { items: ObservationRow[]; next_offset: number | null }>(root, { params: { anchor, period, offset }, signal })

export const readObservation = (id: string, signal: AbortSignal) =>
  request.get<unknown, { observation: ObservationInput & { id: string; recorded_at: string } }>(observationPath(id), { signal })

export const readObservationImage = (id: string, signal: AbortSignal) =>
  request.get<unknown, Blob>(observationPath(id) + '/image', { signal, responseType: 'blob' })

export type ObservationLinkKind = 'case' | 'plan'
export type ObservationTarget = { target_id: string; version: number | null; title: string; trading_day: string; scope: string | null }
export type ObservationLink = ObservationTarget & { kind: ObservationLinkKind; plan: import('./tradeJournal').PlanFields | null }
type Page<T> = { items: T[]; next_offset: number | null }
export const observationTargets = (id: string, kind: ObservationLinkKind, q: string, offset: number, signal: AbortSignal) =>
  request.get<unknown, Page<ObservationTarget>>(observationPath(id) + '/link-candidates', { params: { kind, q, offset }, signal })
export const observationLinks = (id: string, offset: number, signal: AbortSignal) =>
  request.get<unknown, Page<ObservationLink>>(observationPath(id) + '/links', { params: { offset }, signal })
export const linkObservation = (id: string, kind: ObservationLinkKind, target: ObservationTarget, key: string) =>
  request.put(observationPath(id) + '/links', { kind, target_id: target.target_id, version: target.version }, { headers: { 'Idempotency-Key': key } })
export const targetObservations = (kind: ObservationLinkKind, target_id: string, version: number | undefined, offset: number, signal: AbortSignal) =>
  request.get<unknown, Page<{id: string; trading_day: string; contract: string; note: string}>>('/trade-journal/observation-links',
    { params: { kind, target_id, version, offset }, signal })
