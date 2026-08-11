import type { MainIndicatorDefinition, MainIndicatorId, MainIndicatorSeries, MainIndicatorValue } from '@/types/market'

/** 主图指标偏好 localStorage 键 */
export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v1'
/** 主图指标偏好 schema 版本 */
export const MAIN_CHART_PREFERENCES_VERSION = 1
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
  version: 1
  visibleMainIndicators: MainIndicatorId[]
  period?: string | null
  realtimeFollow?: boolean
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
    capability: 'standard_overlay',
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
    capability: 'standard_overlay',
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
    displayName: '火天大有（原始观察）',
    pane: 'main',
    renderer: 'mixed',
    capability: 'observation_overlay',
    defaultVisible: false,
    color: '#2dd4bf',
    parameters: {},
    lookbackBars: 0,
    alertCapable: false,
    available: true,
    repaintingRisk: 'known',
    riskMessages: [
      '未来引用 / 重绘风险',
      '公式语义尚未完全对齐',
      '仅供人工观察',
      '不进入严格研究、回测、信号、提醒或交易',
    ],
    unstableTailBars: HTDY_REPAINT_SCAN_ZONE_BARS,
  },
]

/** 默认可见的主图指标 id 列表 */
export const DEFAULT_VISIBLE_MAIN_INDICATORS = MAIN_INDICATOR_DEFINITIONS
  .filter((definition) => definition.available && definition.defaultVisible)
  .map((definition) => definition.id)

/** 趋势 EMA 指标 id 列表 */
export const TREND_EMA_INDICATORS: MainIndicatorId[] = ['ema_10', 'ema_21', 'ema_60']

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
 * 将指标 id 转为后端 indicator_code（name 字段）。
 */
export function indicatorCodeForId(id: MainIndicatorId) {
  return mainIndicatorDefinition(id)?.name || null
}

/**
 * 将后端 indicator_code 反查为主图指标 id。
 */
export function mainIndicatorIdForCode(code: string): MainIndicatorId | null {
  const definition = MAIN_INDICATOR_DEFINITIONS.find((item) => item.name === code)
  return definition?.id || null
}

/**
 * 从可见 id 列表提取需请求的后端指标 code（仅 standard_overlay 且 available）。
 */
export function activeIndicatorCodes(visibleIds: MainIndicatorId[]) {
  return visibleIds
    .map((id) => mainIndicatorDefinition(id))
    .filter(
      (definition): definition is MainIndicatorDefinition =>
        Boolean(definition?.available && definition.capability === 'standard_overlay'),
    )
    .map((definition) => definition.name)
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

/**
 * 从 localStorage 加载主图偏好；版本不匹配或解析失败时返回默认值。
 */
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
        visibleMainIndicators: normalizeVisibleMainIndicators(preferences.visibleMainIndicators),
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
    version: 1,
    visibleMainIndicators: [...DEFAULT_VISIBLE_MAIN_INDICATORS],
    period: null,
    realtimeFollow: false,
  }
}

/**
 * 规范化后端返回的主图指标序列：映射 id、过滤非 overlay 指标、统一点字段。
 */
export function normalizeMainIndicatorSeries(series: MainIndicatorSeries[]): MainIndicatorSeries[] {
  const result: MainIndicatorSeries[] = []
  series.forEach((item) => {
    const id = isMainIndicatorId(item.id) ? item.id : mainIndicatorIdForCode(item.indicator_code)
    const definition = id ? mainIndicatorDefinition(id) : null
    if (!id || !definition?.available || definition.capability !== 'standard_overlay') return
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

/**
 * 提取可见 overlay 指标的最新有效数值，用于图例/状态栏展示。
 */
export function latestMainIndicatorValues(series: MainIndicatorSeries[], visibleIds: MainIndicatorId[]): MainIndicatorValue[] {
  const result: MainIndicatorValue[] = []
  visibleIds.forEach((id) => {
    const definition = mainIndicatorDefinition(id)
    if (!definition || !definition.available || definition.capability !== 'standard_overlay') return
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
