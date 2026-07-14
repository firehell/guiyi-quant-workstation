import type { BarData, MainIndicatorDefinition, MainIndicatorId, MainIndicatorSeries, MainIndicatorValue } from '@/types/market'

export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v1'
export const MAIN_CHART_PREFERENCES_VERSION = 1

export interface MainChartPreferences {
  version: 1
  visibleMainIndicators: MainIndicatorId[]
  period?: string | null
  realtimeFollow?: boolean
}

export interface MainIndicatorRequestParams {
  symbol: string
  contract: string
  period: string
  indicator_codes: string
  display_start: string
  display_end: string
  display_bar_count: number
  provider?: string | null
  data_role?: string | null
  quote_mode?: boolean
  allow_continuous?: boolean
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
    alertCapable: false,
    available: true,
  },
  {
    id: 'ema_21',
    name: 'ema21',
    displayName: 'EMA21',
    pane: 'main',
    renderer: 'line',
    defaultVisible: true,
    color: '#f59e0b',
    parameters: { period: 21 },
    lookbackBars: 21,
    alertCapable: false,
    available: true,
  },
  {
    id: 'ema_60',
    name: 'ema60',
    displayName: 'EMA60',
    pane: 'main',
    renderer: 'line',
    defaultVisible: false,
    color: '#a78bfa',
    parameters: { period: 60 },
    lookbackBars: 60,
    alertCapable: false,
    available: true,
  },
  {
    id: 'htdy',
    name: 'htdy',
    displayName: '火天大有',
    pane: 'main',
    renderer: 'mixed',
    defaultVisible: false,
    color: '#14b8a6',
    parameters: {},
    lookbackBars: 0,
    alertCapable: false,
    available: false,
    unavailableReason: '等待 B 线统一指标内核冻结',
  },
]

export const DEFAULT_VISIBLE_MAIN_INDICATORS = MAIN_INDICATOR_DEFINITIONS
  .filter((definition) => definition.available && definition.defaultVisible)
  .map((definition) => definition.id)

export const TREND_EMA_INDICATORS: MainIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']

const definitionsById = new Map(MAIN_INDICATOR_DEFINITIONS.map((definition) => [definition.id, definition]))

export function isMainIndicatorId(value: unknown): value is MainIndicatorId {
  return typeof value === 'string' && definitionsById.has(value as MainIndicatorId)
}

export function mainIndicatorDefinition(id: MainIndicatorId) {
  return definitionsById.get(id) || null
}

export function indicatorCodeForId(id: MainIndicatorId) {
  return mainIndicatorDefinition(id)?.name || null
}

export function mainIndicatorIdForCode(code: string): MainIndicatorId | null {
  const definition = MAIN_INDICATOR_DEFINITIONS.find((item) => item.name === code)
  return definition?.id || null
}

export function activeIndicatorCodes(visibleIds: MainIndicatorId[]) {
  return visibleIds
    .map((id) => mainIndicatorDefinition(id))
    .filter((definition): definition is MainIndicatorDefinition => Boolean(definition?.available))
    .map((definition) => definition.name)
}

export function normalizeVisibleMainIndicators(value: unknown): MainIndicatorId[] {
  if (!Array.isArray(value)) return [...DEFAULT_VISIBLE_MAIN_INDICATORS]
  const result: MainIndicatorId[] = []
  value.forEach((item) => {
    if (!isMainIndicatorId(item)) return
    const definition = mainIndicatorDefinition(item)
    if (!definition?.available || result.includes(item)) return
    result.push(item)
  })
  return result
}

export function loadMainChartPreferences(storage: Pick<Storage, 'getItem'> | null = browserStorage()): MainChartPreferences {
  if (!storage) return defaultMainChartPreferences()
  try {
    const raw = storage.getItem(MAIN_CHART_PREFERENCES_KEY)
    if (!raw) return defaultMainChartPreferences()
    const parsed = JSON.parse(raw) as Partial<MainChartPreferences> | null
    if (!parsed || parsed.version !== MAIN_CHART_PREFERENCES_VERSION) return defaultMainChartPreferences()
    return {
      version: 1,
      visibleMainIndicators: normalizeVisibleMainIndicators(parsed.visibleMainIndicators),
      period: typeof parsed.period === 'string' ? parsed.period : null,
      realtimeFollow: Boolean(parsed.realtimeFollow),
    }
  } catch {
    return defaultMainChartPreferences()
  }
}

export function saveMainChartPreferences(
  preferences: MainChartPreferences,
  storage: Pick<Storage, 'setItem'> | null = browserStorage(),
) {
  if (!storage) return
  try {
    storage.setItem(
      MAIN_CHART_PREFERENCES_KEY,
      JSON.stringify({
        version: MAIN_CHART_PREFERENCES_VERSION,
        visibleMainIndicators: normalizeVisibleMainIndicators(preferences.visibleMainIndicators),
        period: preferences.period || null,
        realtimeFollow: Boolean(preferences.realtimeFollow),
      }),
    )
  } catch {
    // Preference persistence must never block the chart from opening.
  }
}

export function defaultMainChartPreferences(): MainChartPreferences {
  return {
    version: 1,
    visibleMainIndicators: [...DEFAULT_VISIBLE_MAIN_INDICATORS],
    period: null,
    realtimeFollow: false,
  }
}

export function buildMainIndicatorRequestParams(input: {
  symbol: string | null
  contract: string | null
  period: string | null
  bars: BarData[]
  visibleIds: MainIndicatorId[]
  provider?: string | null
  dataRole?: string | null
  quoteMode?: boolean
  allowContinuous?: boolean
}): MainIndicatorRequestParams | null {
  if (!input.symbol || !input.contract || !input.period || input.bars.length === 0) return null
  const indicatorCodes = activeIndicatorCodes(input.visibleIds)
  if (indicatorCodes.length === 0) return null
  return {
    symbol: input.symbol,
    contract: input.contract,
    period: input.period,
    indicator_codes: indicatorCodes.join(','),
    display_start: input.bars[0].time,
    display_end: input.bars[input.bars.length - 1].time,
    display_bar_count: input.bars.length,
    provider: input.provider,
    data_role: input.dataRole,
    quote_mode: Boolean(input.quoteMode),
    allow_continuous: Boolean(input.allowContinuous),
  }
}

export function normalizeMainIndicatorSeries(series: MainIndicatorSeries[]): MainIndicatorSeries[] {
  const result: MainIndicatorSeries[] = []
  series.forEach((item) => {
    const id = isMainIndicatorId(item.id) ? item.id : mainIndicatorIdForCode(item.indicator_code)
    const definition = id ? mainIndicatorDefinition(id) : null
    if (!id || !definition?.available) return
    result.push({
      ...item,
      id,
      points: item.points.map((point) => ({
        ...point,
        ready: Boolean(point.ready),
        valid: Boolean(point.valid),
        value: typeof point.value === 'number' ? point.value : null,
        reason: point.reason || null,
      })),
    })
  })
  return result
}

export function latestMainIndicatorValues(series: MainIndicatorSeries[], visibleIds: MainIndicatorId[]): MainIndicatorValue[] {
  const result: MainIndicatorValue[] = []
  visibleIds.forEach((id) => {
    const definition = mainIndicatorDefinition(id)
    if (!definition || !definition.available) return
    const latest = series.find((item) => item.id === id)?.points.at(-1)
    result.push({
      id: definition.id,
      displayName: definition.displayName,
      color: definition.color,
      value: latest?.ready && latest.valid ? latest.value : null,
      ready: latest?.ready ?? false,
      valid: latest?.valid ?? false,
      reason: latest?.reason ?? (latest ? null : 'indicator_not_loaded'),
    })
  })
  return result
}

function browserStorage() {
  return typeof window === 'undefined' ? null : window.localStorage
}
