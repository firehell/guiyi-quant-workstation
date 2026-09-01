import { MARKET_FREQUENCIES } from '../types/market.ts'
import type {
  MainIndicatorDefinition,
  MainIndicatorId,
  MarketFrequency,
  OptionalEmaIndicatorId,
  ResearchOverlayDefinition,
  ResearchOverlayId,
  SeriesKind,
} from '@/types/market'

export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v9'
export const MAIN_CHART_PREFERENCES_VERSION = 9
const LEGACY_KEYS = [
  'guiyi.market.chart.preferences.v1',
  'guiyi.market.chart.preferences.v2',
  'guiyi.market.chart.preferences.v3',
  'guiyi.market.chart.preferences.v4',
  'guiyi.market.chart.preferences.v5',
  'guiyi.market.chart.preferences.v6',
  'guiyi.market.chart.preferences.v7',
  'guiyi.market.chart.preferences.v8',
] as const
export const HTDY_REPAINT_SCAN_ZONE_BARS = 27
export const HTDY_WEB_OBSERVATION_METADATA = {
  indicator_code: 'huotian_dayou_original_v0',
  indicator_version: 'original-v0',
  status: 'observation_only',
  future_looking: true,
  repainting_accepted: true,
  historical_backtest_allowed: false,
  future_dependency_horizon_bars: 24,
  configured_repaint_scan_zone_bars: HTDY_REPAINT_SCAN_ZONE_BARS,
  xma_rule: 'symmetric_clipped_finite_mean; even_period_normalizes_to_next_odd',
  xma6_oracle_status: 'externally_unresolved',
} as const

export interface MainChartPreferences {
  version: 9
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showRangeDetector: boolean
  period?: string | null
  realtimeFollow?: boolean
}

const OPTIONAL_EMA_INDICATORS: OptionalEmaIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']

export const RESEARCH_OVERLAY_DEFINITIONS: readonly ResearchOverlayDefinition[] = [
  {
    id: 'none', label: '无',
    supportedSeriesKinds: ['continuous', 'actual_dominant', 'contract'],
    supportedFrequencies: MARKET_FREQUENCIES,
    mainIndicators: [], historicalSource: 'none',
  },
  {
    id: 'htdy', label: '火天大有',
    supportedSeriesKinds: ['continuous', 'actual_dominant', 'contract'],
    supportedFrequencies: MARKET_FREQUENCIES,
    mainIndicators: ['htdy'], historicalSource: 'local',
  },
]

const overlayDefinitionsById = new Map(RESEARCH_OVERLAY_DEFINITIONS.map((item) => [item.id, item]))

export function researchOverlayCapability(
  overlay: ResearchOverlayId,
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): { supported: boolean; definition: ResearchOverlayDefinition } {
  const definition = overlayDefinitionsById.get(overlay) ?? overlayDefinitionsById.get('none')!
  return {
    definition,
    supported: definition.supportedSeriesKinds.includes(seriesKind)
      && definition.supportedFrequencies.includes(frequency),
  }
}

export const MAIN_INDICATOR_DEFINITIONS: MainIndicatorDefinition[] = [
  { id: 'ema_10', name: 'ema10', displayName: 'EMA10', pane: 'main', renderer: 'line', capability: 'standard_overlay', defaultVisible: false, parameters: { period: 10 }, lookbackBars: 10, alertCapable: false, available: true },
  { id: 'ema_21', name: 'ema21', displayName: 'EMA21', pane: 'main', renderer: 'line', capability: 'standard_overlay', defaultVisible: false, parameters: { period: 21 }, lookbackBars: 21, alertCapable: false, available: true },
  { id: 'ema_60', name: 'ema60', displayName: 'EMA60', pane: 'main', renderer: 'line', capability: 'standard_overlay', defaultVisible: false, parameters: { period: 60 }, lookbackBars: 60, alertCapable: false, available: true },
  {
    id: 'range_detector', name: 'range_detector_lux_v1', displayName: '箱体识别（Lux Range）',
    pane: 'main', renderer: 'band', capability: 'standard_overlay', defaultVisible: false,
    parameters: { minimumRangeLength: 20, rangeWidthAtrMultiplier: 1, rangeAtrLength: 500 },
    lookbackBars: 500, alertCapable: false, available: true,
  },
  {
    id: 'htdy', name: 'htdy', displayName: '火天大有（原始观察）', pane: 'main',
    renderer: 'mixed', capability: 'observation_overlay', defaultVisible: false,
    parameters: {}, lookbackBars: 0, alertCapable: true, available: true,
    repaintingRisk: 'known', unstableTailBars: HTDY_REPAINT_SCAN_ZONE_BARS,
    riskMessages: ['未来引用 / 重绘风险', '公式语义尚未完全对齐', '仅供人工观察', '只允许当前已收线 Bar 的预警观察', '不进入严格研究、回测、正式 live 或交易'],
  },
]

export const DEFAULT_VISIBLE_MAIN_INDICATORS = MAIN_INDICATOR_DEFINITIONS
  .filter((item) => item.available && item.defaultVisible).map((item) => item.id)
const definitionsById = new Map(MAIN_INDICATOR_DEFINITIONS.map((item) => [item.id, item]))

export function isMainIndicatorId(value: unknown): value is MainIndicatorId {
  return typeof value === 'string' && definitionsById.has(value as MainIndicatorId)
}

export function mainIndicatorDefinition(id: MainIndicatorId) {
  return definitionsById.get(id) || null
}

export function normalizeVisibleMainIndicators(value: unknown): MainIndicatorId[] {
  if (!Array.isArray(value)) return [...DEFAULT_VISIBLE_MAIN_INDICATORS]
  const result: MainIndicatorId[] = []
  for (const item of value) {
    if (!isMainIndicatorId(item)) continue
    if (!definitionsById.get(item)?.available || result.includes(item)) continue
    result.push(item)
  }
  return result
}

export function normalizeOptionalEmaIndicators(value: unknown): OptionalEmaIndicatorId[] {
  if (!Array.isArray(value)) return []
  return OPTIONAL_EMA_INDICATORS.filter((id) => value.includes(id))
}

export function visibleMainIndicatorsForOverlay(
  overlay: ResearchOverlayId,
  optionalEmaIndicators: OptionalEmaIndicatorId[] = [],
  showRangeDetector = false,
): MainIndicatorId[] {
  const definition = overlayDefinitionsById.get(overlay)
  if (!definition) return []
  return [
    ...normalizeOptionalEmaIndicators(optionalEmaIndicators),
    ...(showRangeDetector ? ['range_detector' as const] : []),
    ...definition.mainIndicators,
  ]
}

export function resolveEffectiveSeriesIdentity(input: {
  overlay: ResearchOverlayId
  userSeriesKind: SeriesKind
  userContract?: string
  dominantContract?: string
}): { seriesKind: SeriesKind; contract?: string } {
  return {
    seriesKind: input.userSeriesKind,
    contract: input.userSeriesKind === 'contract' ? input.userContract : undefined,
  }
}

export function defaultMainChartPreferences(): MainChartPreferences {
  return { version: 9, selectedOverlay: 'none', optionalEmaIndicators: [], showRangeDetector: false, period: null, realtimeFollow: false }
}

export function loadMainChartPreferences(
  storage: Pick<Storage, 'getItem'> & Partial<Pick<Storage, 'setItem' | 'removeItem'>> | null = browserStorage(),
): MainChartPreferences {
  if (!storage) return defaultMainChartPreferences()
  try {
    const current = storage.getItem(MAIN_CHART_PREFERENCES_KEY)
    if (current) {
      const parsed = JSON.parse(current) as Record<string, unknown>
      if (parsed.version === 9) return normalizePreferences(parsed)
    }
    const legacyV8 = storage.getItem('guiyi.market.chart.preferences.v8')
    if (legacyV8) {
      const parsed = JSON.parse(legacyV8) as Record<string, unknown>
      if (parsed.version === 8) {
        const migrated = normalizePreferences(parsed)
        storage.setItem?.(MAIN_CHART_PREFERENCES_KEY, JSON.stringify(migrated))
        storage.removeItem?.('guiyi.market.chart.preferences.v8')
        purgeLegacy(storage)
        return migrated
      }
    }
    purgeLegacy(storage)
  } catch {
    return defaultMainChartPreferences()
  }
  return defaultMainChartPreferences()
}

export function saveMainChartPreferences(
  preferences: MainChartPreferences,
  storage: Pick<Storage, 'setItem'> | null = browserStorage(),
) {
  if (!storage) return
  try { storage.setItem(MAIN_CHART_PREFERENCES_KEY, JSON.stringify(normalizePreferences(preferences as unknown as Record<string, unknown>))) } catch { /* noop */ }
}

function normalizePreferences(value: Record<string, unknown>): MainChartPreferences {
  return {
    version: 9,
    selectedOverlay: value.selectedOverlay === 'htdy' ? 'htdy' : 'none',
    optionalEmaIndicators: normalizeOptionalEmaIndicators(value.optionalEmaIndicators),
    showRangeDetector: Boolean(value.showRangeDetector),
    period: typeof value.period === 'string' ? value.period : null,
    realtimeFollow: Boolean(value.realtimeFollow),
  }
}

function purgeLegacy(storage: Partial<Pick<Storage, 'removeItem'>>) {
  for (const key of LEGACY_KEYS) {
    if (key === 'guiyi.market.chart.preferences.v8') continue
    try { storage.removeItem?.(key) } catch { /* noop */ }
  }
}

function browserStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try { return window.localStorage } catch { return null }
}
