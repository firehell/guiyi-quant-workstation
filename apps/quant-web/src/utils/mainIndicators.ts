import type { BarData, MainIndicatorDefinition, MainIndicatorId, MainIndicatorSeries, MainIndicatorValue } from '@/types/market'

export type { MainIndicatorId }

export interface MainIndicatorOption {
  id: MainIndicatorId
  label: string
  color: string
  lineWidth?: 1 | 2
  defaultEnabled: boolean
  observationOnly?: boolean
}

export interface MainChartPreferences {
  version: 1
  visibleMainIndicators: MainIndicatorId[]
  period?: string
  realtimeFollow?: boolean
}

interface StorageLike {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
}

interface BuildMainIndicatorRequestOptions {
  symbol?: string | null
  contract?: string | null
  period?: string | null
  bars: BarData[]
  visibleIds: MainIndicatorId[]
  provider?: string | null
  dataRole?: string | null
  profileId?: string | null
  quoteMode?: boolean
  allowContinuous?: boolean
}

type MainIndicatorRequestParams = {
  symbol: string
  contract: string
  period: string
  indicator_codes: string
  display_start: string
  display_end: string
  display_bar_count: number
  provider?: string
  data_role?: string
  profile_id?: string
  quote_mode?: boolean
  allow_continuous?: boolean
}

export const MAIN_CHART_PREFERENCES_KEY = 'guiyi_kline_main_chart_preferences_v1'
export const MAIN_INDICATOR_STORAGE_KEY = 'guiyi_kline_main_indicators_v1'

const BACKEND_INDICATOR_CODES: Record<MainIndicatorId, string | null> = {
  ema_10: 'ema10',
  ema_21: 'ema21',
  ema_60: 'ema60',
  htdy: null,
}

export const MAIN_INDICATOR_DEFINITIONS: MainIndicatorDefinition[] = [
  {
    id: 'ema_10',
    name: 'ema10',
    displayName: 'EMA10',
    pane: 'main',
    renderer: 'line',
    defaultVisible: false,
    color: '#facc15',
    parameters: { period: 10 },
    lookbackBars: 10,
    alertCapable: true,
    available: true,
  },
  {
    id: 'ema_21',
    name: 'ema21',
    displayName: 'EMA21',
    pane: 'main',
    renderer: 'line',
    defaultVisible: true,
    color: '#38bdf8',
    parameters: { period: 21 },
    lookbackBars: 21,
    alertCapable: true,
    available: true,
  },
  {
    id: 'ema_60',
    name: 'ema60',
    displayName: 'EMA60',
    pane: 'main',
    renderer: 'line',
    defaultVisible: false,
    color: '#c084fc',
    parameters: { period: 60 },
    lookbackBars: 60,
    alertCapable: true,
    available: true,
  },
  {
    id: 'htdy',
    name: 'huo_tian_da_you',
    displayName: '火天大有',
    pane: 'main',
    renderer: 'mixed',
    defaultVisible: false,
    color: '#fb923c',
    parameters: {},
    lookbackBars: 89,
    alertCapable: false,
    available: false,
    unavailableReason: '观察指标待统一 API',
  },
]

export const DEFAULT_VISIBLE_MAIN_INDICATORS: MainIndicatorId[] = MAIN_INDICATOR_DEFINITIONS
  .filter((definition) => definition.defaultVisible && definition.available)
  .map((definition) => definition.id)

export const TREND_EMA_INDICATORS: MainIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']

export const MAIN_INDICATOR_OPTIONS: MainIndicatorOption[] = MAIN_INDICATOR_DEFINITIONS.map((definition) => ({
  id: definition.id,
  label: definition.displayName,
  color: definition.color,
  lineWidth: definition.id === 'ema_21' ? 2 : 1,
  defaultEnabled: DEFAULT_VISIBLE_MAIN_INDICATORS.includes(definition.id),
  observationOnly: !definition.available,
}))

export const DEFAULT_MAIN_INDICATORS = DEFAULT_VISIBLE_MAIN_INDICATORS

const availableIds = new Set<MainIndicatorId>(MAIN_INDICATOR_DEFINITIONS.filter((definition) => definition.available).map((definition) => definition.id))
const definitionById = new Map(MAIN_INDICATOR_DEFINITIONS.map((definition) => [definition.id, definition]))
const idByBackendCode = new Map(
  Object.entries(BACKEND_INDICATOR_CODES)
    .filter((entry): entry is [MainIndicatorId, string] => typeof entry[1] === 'string')
    .map(([id, code]) => [code, id]),
)

const legacyIds: Record<string, MainIndicatorId> = {
  ema10: 'ema_10',
  ema21: 'ema_21',
  ema60: 'ema_60',
  huo_tian_da_you: 'htdy',
}

function storageOrNull(storage?: StorageLike): StorageLike | null {
  if (storage) return storage
  return typeof localStorage === 'undefined' ? null : localStorage
}

function normalizeMainIndicatorId(value: unknown): MainIndicatorId | null {
  if (typeof value !== 'string') return null
  if (value in legacyIds) return legacyIds[value]
  return definitionById.has(value as MainIndicatorId) ? value as MainIndicatorId : null
}

export function normalizeVisibleMainIndicators(value: unknown): MainIndicatorId[] {
  if (!Array.isArray(value)) return [...DEFAULT_VISIBLE_MAIN_INDICATORS]
  const selected: MainIndicatorId[] = []
  value.forEach((item) => {
    const id = normalizeMainIndicatorId(item)
    if (!id || !availableIds.has(id) || selected.includes(id)) return
    selected.push(id)
  })
  return selected
}

export function sanitizeMainIndicators(value: unknown): MainIndicatorId[] {
  return normalizeVisibleMainIndicators(value)
}

export function loadMainIndicators(): MainIndicatorId[] {
  if (typeof localStorage === 'undefined') return [...DEFAULT_VISIBLE_MAIN_INDICATORS]
  try {
    const raw = localStorage.getItem(MAIN_INDICATOR_STORAGE_KEY)
    if (!raw) return [...DEFAULT_VISIBLE_MAIN_INDICATORS]
    return sanitizeMainIndicators(JSON.parse(raw))
  } catch {
    return [...DEFAULT_VISIBLE_MAIN_INDICATORS]
  }
}

export function saveMainIndicators(value: MainIndicatorId[]) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(MAIN_INDICATOR_STORAGE_KEY, JSON.stringify(sanitizeMainIndicators(value)))
}

export function mainIndicatorLabel(id: MainIndicatorId): string {
  return MAIN_INDICATOR_OPTIONS.find((option) => option.id === id)?.label || id
}

export function loadMainChartPreferences(storage?: StorageLike): MainChartPreferences {
  const target = storageOrNull(storage)
  if (!target) {
    return { version: 1, visibleMainIndicators: [...DEFAULT_VISIBLE_MAIN_INDICATORS] }
  }
  try {
    const raw = target.getItem(MAIN_CHART_PREFERENCES_KEY)
    if (!raw) return { version: 1, visibleMainIndicators: [...DEFAULT_VISIBLE_MAIN_INDICATORS] }
    const parsed = JSON.parse(raw) as Partial<MainChartPreferences>
    return {
      version: 1,
      visibleMainIndicators: normalizeVisibleMainIndicators(parsed.visibleMainIndicators),
      period: typeof parsed.period === 'string' ? parsed.period : undefined,
      realtimeFollow: Boolean(parsed.realtimeFollow),
    }
  } catch {
    return { version: 1, visibleMainIndicators: [...DEFAULT_VISIBLE_MAIN_INDICATORS] }
  }
}

export function saveMainChartPreferences(preferences: MainChartPreferences, storage?: StorageLike) {
  const target = storageOrNull(storage)
  if (!target) return
  target.setItem(
    MAIN_CHART_PREFERENCES_KEY,
    JSON.stringify({
      version: 1,
      visibleMainIndicators: normalizeVisibleMainIndicators(preferences.visibleMainIndicators),
      period: preferences.period,
      realtimeFollow: Boolean(preferences.realtimeFollow),
    }),
  )
}

export function activeIndicatorCodes(ids: MainIndicatorId[]): string[] {
  return ids
    .map((id) => BACKEND_INDICATOR_CODES[id])
    .filter((code): code is string => typeof code === 'string')
}

export function buildMainIndicatorRequestParams(options: BuildMainIndicatorRequestOptions): MainIndicatorRequestParams | null {
  const codes = activeIndicatorCodes(normalizeVisibleMainIndicators(options.visibleIds))
  if (!options.symbol || !options.contract || !options.period || !options.bars.length || !codes.length) return null
  const firstBar = options.bars[0]
  const lastBar = options.bars.at(-1)
  if (!firstBar || !lastBar) return null

  const params: MainIndicatorRequestParams = {
    symbol: options.symbol,
    contract: options.contract,
    period: options.period,
    indicator_codes: codes.join(','),
    display_start: firstBar.time,
    display_end: lastBar.time,
    display_bar_count: options.bars.length,
  }
  if (options.provider) params.provider = options.provider
  if (options.dataRole) params.data_role = options.dataRole
  if (options.profileId) params.profile_id = options.profileId
  if (options.quoteMode !== undefined) params.quote_mode = options.quoteMode
  if (options.allowContinuous !== undefined) params.allow_continuous = options.allowContinuous
  return params
}

export function normalizeMainIndicatorSeries(series: MainIndicatorSeries[]): MainIndicatorSeries[] {
  return series.flatMap((item) => {
    const id = normalizeMainIndicatorId(item.id) || idByBackendCode.get(item.indicator_code)
    if (!id || !availableIds.has(id)) return []
    const expectedCode = BACKEND_INDICATOR_CODES[id]
    if (expectedCode && item.indicator_code !== expectedCode) return []
    return [{ ...item, id }]
  })
}

export function latestMainIndicatorValues(series: MainIndicatorSeries[], visibleIds: MainIndicatorId[]): MainIndicatorValue[] {
  const byId = new Map(normalizeMainIndicatorSeries(series).map((item) => [item.id, item]))
  return normalizeVisibleMainIndicators(visibleIds).map((id) => {
    const definition = definitionById.get(id)!
    const item = byId.get(id)
    const latest = item?.points.at(-1)
    return {
      id,
      displayName: definition.displayName,
      color: definition.color,
      value: latest?.value ?? null,
      ready: latest?.ready ?? false,
      valid: latest?.valid ?? false,
      reason: latest?.reason ?? (item ? null : 'indicator_not_loaded'),
    }
  })
}
