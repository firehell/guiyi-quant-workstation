import { CHART_PROFILES, DISPLAY_CATALOG, MAX_AUXILIARY_PANES, readChartPreferences, type ChartPreferences, type ChartProfileId, type LayerStatus } from '@guiyi/quant-chart'
import type { NewowProductSectionResponse, NewowResourceLifecycle } from '../types/newowProduct.ts'

export const NEWOW_AUXILIARY_COMPONENTS = ['zhaoyao_mirror', 'up_down_energy', 'main_force_control', 'trend_reversal'] as const
type SpecializedComponent = typeof NEWOW_AUXILIARY_COMPONENTS[number]
export type NewowAuxiliaryPaneComponent = SpecializedComponent | 'macd'
export const newowPaneId = (component: NewowAuxiliaryPaneComponent) => component === 'macd' ? component : `newow.${component}` as const
export const NEWOW_AUXILIARY_OPTIONS = NEWOW_AUXILIARY_COMPONENTS.map(id => ({ id, label: DISPLAY_CATALOG[newowPaneId(id)]!.label }))
export const NEWOW_EXTRA_AUXILIARY_OPTIONS = [...NEWOW_AUXILIARY_OPTIONS, { id: 'macd' as const, label: DISPLAY_CATALOG.macd!.label }]
export const MAX_ADDITIONAL_NEWOW_PANES = MAX_AUXILIARY_PANES - 1

export interface NewowAdditionalPane {
  component: NewowAuxiliaryPaneComponent
  height?: number
  response: NewowProductSectionResponse<'auxiliary'> | null
  lifecycle: NewowResourceLifecycle
  error: string | null
}

const STORAGE_KEY = 'guiyi.newow.extra-panes'
const known = new Set<string>(NEWOW_EXTRA_AUXILIARY_OPTIONS.map(item => newowPaneId(item.id)))
function store(): Record<string, unknown> {
  try {
    const raw: unknown = JSON.parse(globalThis.localStorage?.getItem(STORAGE_KEY) ?? '{}')
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
  } catch { return {} }
}
export function defaultNewowPane(profile: ChartProfileId): SpecializedComponent {
  const selection = CHART_PROFILES[profile].auxiliaryDefault
  return NEWOW_AUXILIARY_COMPONENTS.find(component => newowPaneId(component) === selection) ?? 'zhaoyao_mirror'
}
export function readNewowAdditionalPanes(profile: ChartProfileId, fallback?: ChartPreferences): ChartPreferences {
  const defaults = readChartPreferences(null, profile)
  try {
    const value = readChartPreferences(store()[profile] ?? fallback, profile)
    return { ...value, layers: value.layers.filter(layer => known.has(layer.id)).slice(0, MAX_ADDITIONAL_NEWOW_PANES) }
  } catch { return defaults }
}
export function saveNewowAdditionalPanes(profile: ChartProfileId, preferences: ChartPreferences): void {
  try { globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify({ ...store(), [profile]: preferences })) }
  catch { /* Browser storage is optional. */ }
}

/** An accepted resource can contain historical data while its current contract segment remains unavailable. */
export function newowAuxiliaryLayerStatus(
  lifecycle: NewowResourceLifecycle,
  hasResponse: boolean,
  aligned: boolean,
  currentStatus: NewowResourceLifecycle | null,
  hasPoints: boolean,
  error: string | null,
): LayerStatus {
  if (lifecycle === 'input_conflict' || error === 'CHART_AUXILIARY_SOURCE_INVALID') return 'invalid_source'
  if (lifecycle === 'loading') return 'loading'
  if (hasResponse && !aligned) return 'invalid_source'
  if (lifecycle === 'stale' || lifecycle === 'unavailable' || lifecycle === 'busy') return 'compute_error'
  if (currentStatus === 'warming' || (currentStatus === null && lifecycle === 'warming')) return 'warming'
  if (currentStatus === 'ready' && hasPoints) return 'ready'
  if (currentStatus === 'unavailable' || (error && !hasResponse && lifecycle !== 'not_applicable' && lifecycle !== 'evidence_required')) return 'compute_error'
  return 'missing_input'
}
