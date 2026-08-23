import type {
  MainIndicatorDefinition,
  MainIndicatorId,
  OptionalEmaIndicatorId,
  ResearchOverlayId,
  ResearchOverlayDefinition,
  SeriesKind,
  MarketFrequency,
} from '@/types/market'

/** 主图指标偏好 localStorage 键 */
export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v3'
/** 主图指标偏好 schema 版本 */
export const MAIN_CHART_PREFERENCES_VERSION = 3
const LEGACY_V2_MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v2'
const LEGACY_V1_MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v1'
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

/** 主图指标显示偏好（可见指标、周期、实时跟随） */
export interface MainChartPreferences {
  version: 3
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  period?: string | null
  realtimeFollow?: boolean
}

interface LegacyMainChartPreferences {
  version: 1
  visibleMainIndicators: MainIndicatorId[]
  period?: string | null
  realtimeFollow?: boolean
}

interface LegacyV2MainChartPreferences {
  version: 2
  selectedOverlay: ResearchOverlayId
  period?: string | null
  realtimeFollow?: boolean
}

const OPTIONAL_EMA_INDICATORS: OptionalEmaIndicatorId[] = ['ema_10', 'ema_60']

export const RESEARCH_OVERLAY_DEFINITIONS: readonly ResearchOverlayDefinition[] = [
  {
    id: 'none',
    label: '无',
    supportedSeriesKinds: ['continuous', 'actual_dominant', 'contract'],
    supportedFrequencies: ['1m', '5m', '15m', '30m', '60m', '1d', '1w'],
    mainIndicators: [],
    historicalSource: 'none',
  },
  {
    id: 'subing',
    label: '苏冰',
    supportedSeriesKinds: ['actual_dominant'],
    supportedFrequencies: ['5m', '15m'],
    mainIndicators: ['ema_21'],
    historicalSource: 'subing',
  },
  {
    id: 'n_structure',
    label: 'N字',
    supportedSeriesKinds: ['actual_dominant'],
    supportedFrequencies: ['5m'],
    mainIndicators: [],
    historicalSource: 'n_structure',
  },
  {
    id: 'jdj',
    label: '日进斗金',
    supportedSeriesKinds: ['actual_dominant'],
    supportedFrequencies: ['1m'],
    mainIndicators: ['ema_20'],
    historicalSource: 'jdj',
  },
  {
    id: 'jdj_strategy',
    label: '日进斗金策略',
    supportedSeriesKinds: ['actual_dominant'],
    supportedFrequencies: ['1m'],
    mainIndicators: [],
    historicalSource: 'jdj_strategy',
  },
  {
    id: 'htdy',
    label: '火天大有',
    supportedSeriesKinds: ['continuous', 'actual_dominant', 'contract'],
    supportedFrequencies: ['15m'],
    mainIndicators: ['htdy'],
    historicalSource: 'local',
  },
]

const overlayDefinitionsById = new Map(
  RESEARCH_OVERLAY_DEFINITIONS.map((definition) => [definition.id, definition]),
)

export function researchOverlayCapability(
  overlay: ResearchOverlayId,
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): { supported: boolean; definition: ResearchOverlayDefinition } {
  const definition = overlayDefinitionsById.get(overlay)
    ?? overlayDefinitionsById.get('subing')!
  return {
    definition,
    supported: definition.supportedSeriesKinds.includes(seriesKind)
      && definition.supportedFrequencies.includes(frequency),
  }
}

/** 主图可叠加指标定义表（EMA、火天大有等） */
export const MAIN_INDICATOR_DEFINITIONS: MainIndicatorDefinition[] = [
  {
    id: 'ema_10',
    name: 'ema10',
    displayName: 'EMA10',
    pane: 'main',
    renderer: 'line',
    capability: 'standard_overlay',
    defaultVisible: false,
    parameters: { period: 10 },
    lookbackBars: 10,
    alertCapable: false,
    available: true,
  },
  {
    id: 'ema_20',
    name: 'ema20',
    displayName: 'EMA20',
    pane: 'main',
    renderer: 'line',
    capability: 'standard_overlay',
    defaultVisible: false,
    parameters: { period: 20 },
    lookbackBars: 20,
    alertCapable: false,
    available: true,
  },
  {
    id: 'ema_21',
    name: 'ema21',
    displayName: 'EMA21',
    pane: 'main',
    renderer: 'line',
    capability: 'standard_overlay',
    defaultVisible: true,
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
    capability: 'standard_overlay',
    defaultVisible: false,
    parameters: { period: 60 },
    lookbackBars: 60,
    alertCapable: false,
    available: true,
  },
  {
    id: 'htdy',
    name: 'htdy',
    displayName: '火天大有（原始观察）',
    pane: 'main',
    renderer: 'mixed',
    capability: 'observation_overlay',
    defaultVisible: false,
    parameters: {},
    lookbackBars: 0,
    alertCapable: true,
    available: true,
    repaintingRisk: 'known',
    riskMessages: [
      '未来引用 / 重绘风险',
      '公式语义尚未完全对齐',
      '仅供人工观察',
      '只允许当前已收线 Bar 的预警观察',
      '不进入严格研究、回测、正式 live 或交易',
    ],
    unstableTailBars: HTDY_REPAINT_SCAN_ZONE_BARS,
  },
]

/** 默认可见的主图指标 id 列表 */
export const DEFAULT_VISIBLE_MAIN_INDICATORS = MAIN_INDICATOR_DEFINITIONS
  .filter((definition) => definition.available && definition.defaultVisible)
  .map((definition) => definition.id)

const definitionsById = new Map(MAIN_INDICATOR_DEFINITIONS.map((definition) => [definition.id, definition]))

/**
 * 类型守卫：判断值是否为已注册的主图指标 id。
 */
export function isMainIndicatorId(value: unknown): value is MainIndicatorId {
  return typeof value === 'string' && definitionsById.has(value as MainIndicatorId)
}

/**
 * 按 id 获取主图指标定义，未注册时返回 null。
 */
export function mainIndicatorDefinition(id: MainIndicatorId) {
  return definitionsById.get(id) || null
}

/**
 * 规范化可见主图指标 id：去重并过滤非法 id。
 */
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

export function normalizeOptionalEmaIndicators(value: unknown): OptionalEmaIndicatorId[] {
  if (!Array.isArray(value)) return []
  return OPTIONAL_EMA_INDICATORS.filter((id) => value.includes(id))
}

export function visibleMainIndicatorsForOverlay(
  overlay: ResearchOverlayId,
  optionalEmaIndicators: OptionalEmaIndicatorId[] = [],
): MainIndicatorId[] {
  const optional = normalizeOptionalEmaIndicators(optionalEmaIndicators)
  const definition = overlayDefinitionsById.get(overlay)
  if (definition?.id === 'subing') return [
    ...(optional.includes('ema_10') ? ['ema_10' as const] : []),
    'ema_21',
    ...(optional.includes('ema_60') ? ['ema_60' as const] : []),
  ]
  if (definition?.id === 'jdj') return [...definition.mainIndicators]
  if (definition?.id === 'htdy') return [...optional, ...definition.mainIndicators]
  return []
}

/** Research overlays do not own the Market display dataset identity. */
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

/**
 * 从 localStorage 加载主图偏好；版本不匹配或解析失败时返回默认值。
 */
export function loadMainChartPreferences(storage: Pick<Storage, 'getItem'> | null = browserStorage()): MainChartPreferences {
  if (!storage) return defaultMainChartPreferences()
  try {
    const raw = storage.getItem(MAIN_CHART_PREFERENCES_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<MainChartPreferences> | null
      if (!parsed || parsed.version !== MAIN_CHART_PREFERENCES_VERSION) return defaultMainChartPreferences()
      return {
        version: 3,
        selectedOverlay: normalizeResearchOverlay(parsed.selectedOverlay),
        optionalEmaIndicators: normalizeOptionalEmaIndicators(parsed.optionalEmaIndicators),
        period: typeof parsed.period === 'string' ? parsed.period : null,
        realtimeFollow: Boolean(parsed.realtimeFollow),
      }
    }
    const legacyV2Raw = storage.getItem(LEGACY_V2_MAIN_CHART_PREFERENCES_KEY)
    if (legacyV2Raw) {
      const legacy = JSON.parse(legacyV2Raw) as Partial<LegacyV2MainChartPreferences> | null
      if (legacy?.version === 2) return {
        version: 3,
        selectedOverlay: normalizeResearchOverlay(legacy.selectedOverlay),
        optionalEmaIndicators: [],
        period: typeof legacy.period === 'string' ? legacy.period : null,
        realtimeFollow: Boolean(legacy.realtimeFollow),
      }
    }
    const legacyRaw = storage.getItem(LEGACY_V1_MAIN_CHART_PREFERENCES_KEY)
    if (!legacyRaw) return defaultMainChartPreferences()
    const legacy = JSON.parse(legacyRaw) as Partial<LegacyMainChartPreferences> | null
    if (!legacy || legacy.version !== 1 || !Array.isArray(legacy.visibleMainIndicators)) {
      return defaultMainChartPreferences()
    }
    return {
      version: 3,
      selectedOverlay: normalizeVisibleMainIndicators(legacy.visibleMainIndicators).includes('htdy') ? 'htdy' : 'subing',
      optionalEmaIndicators: [],
      period: typeof legacy.period === 'string' ? legacy.period : null,
      realtimeFollow: Boolean(legacy.realtimeFollow),
    }
  } catch {
    return defaultMainChartPreferences()
  }
}

/**
 * 保存主图偏好到 localStorage；持久化失败不得阻塞图表打开。
 */
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
        selectedOverlay: normalizeResearchOverlay(preferences.selectedOverlay),
        optionalEmaIndicators: normalizeOptionalEmaIndicators(preferences.optionalEmaIndicators),
        period: preferences.period || null,
        realtimeFollow: Boolean(preferences.realtimeFollow),
      }),
    )
  } catch {
    // 偏好持久化失败不得阻塞图表打开
  }
}

/**
 * 返回默认主图偏好。
 */
export function defaultMainChartPreferences(): MainChartPreferences {
  return {
    version: 3,
    selectedOverlay: 'subing',
    optionalEmaIndicators: [],
    period: null,
    realtimeFollow: false,
  }
}

function browserStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function normalizeResearchOverlay(value: unknown): ResearchOverlayId {
  return value === 'none' || value === 'n_structure' || value === 'jdj' || value === 'htdy'
    ? value
    : 'subing'
}
