import type { NewowAuxiliaryComponent } from '../types/newowProduct.ts'
export interface NewowUiPreferences {
  auxiliary?: NewowAuxiliaryComponent
  scrollTop?: number
  chart?: { axis: string; range: { from: number; to: number } | null; detail: boolean; actions: boolean; structure: boolean; hints: boolean }
}
export const NEWOW_DISPLAY_KEY = 'guiyi.newow.display.v1'
export const NEWOW_VISIT_KEY = 'guiyi.newow.visit.v1'
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
const entries = new Map<string, NewowUiPreferences>()
const auxiliaries = new Set(['zhaoyao_mirror', 'up_down_energy', 'main_force_control', 'trend_reversal', 'cup_handle', 'macd'])
function storage(kind: 'localStorage' | 'sessionStorage'): StorageLike | null {
  try { return typeof window === 'undefined' ? null : window[kind] } catch { return null }
}
function records(target: StorageLike | null, key: string): Record<string, NewowUiPreferences> {
  try { const raw: unknown = JSON.parse(target?.getItem(key) ?? '{}'); return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, NewowUiPreferences> : {} } catch { return {} }
}
function normalize(value: NewowUiPreferences): NewowUiPreferences {
  const next: NewowUiPreferences = {}
  if (auxiliaries.has(value.auxiliary ?? '')) next.auxiliary = value.auxiliary
  if (typeof value.scrollTop === 'number' && Number.isFinite(value.scrollTop) && value.scrollTop >= 0) next.scrollTop = value.scrollTop
  const chart = value.chart
  if (chart && ['detail', 'actions', 'structure', 'hints'].every(key => typeof chart[key as keyof typeof chart] === 'boolean') && typeof chart.axis === 'string') {
    const range = chart.range
    next.chart = { ...chart, range: range && Number.isFinite(range.from) && Number.isFinite(range.to) && range.from <= range.to ? range : null }
  }
  return next
}
export function readNewowUiPreferences(key: string): NewowUiPreferences {
  return normalize({ ...records(storage('localStorage'), NEWOW_DISPLAY_KEY)[key], ...records(storage('sessionStorage'), NEWOW_VISIT_KEY)[key], ...entries.get(key) })
}
function write(target: StorageLike | null, key: string, identity: string, value: NewowUiPreferences) {
  try { const saved = records(target, key); delete saved[identity]; saved[identity] = value; const recent = Object.fromEntries(Object.entries(saved).slice(-16)); target?.setItem(key, JSON.stringify(recent)) } catch { /* optional storage */ }
}
export function rememberNewowUiPreferences(key: string, patch: NewowUiPreferences): void {
  const value = normalize({ ...readNewowUiPreferences(key), ...patch })
  entries.delete(key); entries.set(key, value)
  while (entries.size > 16) entries.delete(entries.keys().next().value!)
  // Migrate the existing per-identity in-memory preferences on their next update.
  const { scrollTop, chart, auxiliary } = value
  write(storage('localStorage'), NEWOW_DISPLAY_KEY, key, { auxiliary, ...(chart ? { chart: { ...chart, range: null } } : {}) })
  write(storage('sessionStorage'), NEWOW_VISIT_KEY, key, { scrollTop, ...(chart ? { chart } : {}) })
}
export function resetNewowUiPreferences(): void {
  entries.clear()
  try { storage('localStorage')?.removeItem(NEWOW_DISPLAY_KEY); storage('sessionStorage')?.removeItem(NEWOW_VISIT_KEY) } catch { /* optional storage */ }
}
