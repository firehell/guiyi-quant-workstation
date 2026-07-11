import type { MainIndicatorId } from '@/types/market'

export type { MainIndicatorId }

export interface MainIndicatorOption {
  id: MainIndicatorId
  label: string
  color: string
  defaultEnabled: boolean
  observationOnly?: boolean
}

export const MAIN_INDICATOR_STORAGE_KEY = 'guiyi_kline_main_indicators_v1'

export const MAIN_INDICATOR_OPTIONS: MainIndicatorOption[] = [
  { id: 'ema10', label: 'EMA10', color: '#facc15', defaultEnabled: false },
  { id: 'ema21', label: 'EMA21', color: '#38bdf8', defaultEnabled: true },
  { id: 'ema60', label: 'EMA60', color: '#c084fc', defaultEnabled: false },
  { id: 'huo_tian_da_you', label: '火天大有', color: '#fb923c', defaultEnabled: false, observationOnly: true },
]

export const DEFAULT_MAIN_INDICATORS = MAIN_INDICATOR_OPTIONS
  .filter((option) => option.defaultEnabled)
  .map((option) => option.id)

const allowedIds = new Set<MainIndicatorId>(MAIN_INDICATOR_OPTIONS.map((option) => option.id))

export function sanitizeMainIndicators(value: unknown): MainIndicatorId[] {
  if (!Array.isArray(value)) return [...DEFAULT_MAIN_INDICATORS]
  const selected: MainIndicatorId[] = []
  value.forEach((item) => {
    if (typeof item !== 'string') return
    const id = item as MainIndicatorId
    if (!allowedIds.has(id) || selected.includes(id)) return
    selected.push(id)
  })
  return selected
}

export function loadMainIndicators(): MainIndicatorId[] {
  if (typeof localStorage === 'undefined') return [...DEFAULT_MAIN_INDICATORS]
  try {
    const raw = localStorage.getItem(MAIN_INDICATOR_STORAGE_KEY)
    if (!raw) return [...DEFAULT_MAIN_INDICATORS]
    return sanitizeMainIndicators(JSON.parse(raw))
  } catch {
    return [...DEFAULT_MAIN_INDICATORS]
  }
}

export function saveMainIndicators(value: MainIndicatorId[]) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(MAIN_INDICATOR_STORAGE_KEY, JSON.stringify(sanitizeMainIndicators(value)))
}

export function mainIndicatorLabel(id: MainIndicatorId): string {
  return MAIN_INDICATOR_OPTIONS.find((option) => option.id === id)?.label || id
}
