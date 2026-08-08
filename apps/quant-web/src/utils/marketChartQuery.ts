import type { MarketAccessMode } from './marketChartInit.ts'
import { defaultContractViewForPeriod, type ContractViewMode } from './marketChartWindow.ts'
import { toSafeApiError } from './errorRedaction.ts'

/** 写回路由所需的 chart 选中状态（仅 historical/canonical） */
export interface MarketChartQueryState {
  symbol: string
  actualContract: string
  period: string
  contractView: ContractViewMode
  accessMode: MarketAccessMode
}

/** 保留在 URL 中的 deep-link 字段（行情观察，不含 signal/review） */
export interface MarketChartDeepLink {
  strategy?: string | null
  time?: string | null
  datetime?: string | null
}

/**
 * 将 chart 状态与 deep-link 合并为 route query。
 * 默认值（browser / 默认 contract_view）省略以保持 URL 简洁。
 */
export function buildMarketChartRouteQuery(
  state: MarketChartQueryState,
  deepLink: MarketChartDeepLink = {},
): Record<string, string | undefined> {
  const defaultView = defaultContractViewForPeriod(state.period)
  return {
    symbol: state.symbol,
    contract: state.actualContract,
    period: state.period,
    contract_view: state.contractView === defaultView ? undefined : state.contractView,
    access_mode: state.accessMode === 'research' ? 'research' : undefined,
    strategy: deepLink.strategy?.trim() || undefined,
    time: deepLink.time?.trim() || deepLink.datetime?.trim() || undefined,
  }
}

/** 数据质量 failed 时的观察文案（禁止拼接 file_path）。 */
export function qualityFailedObservationText(): string {
  return '数据质量为 failed，暂不可展示。'
}

/** DataGap facts.reason 白名单（禁止透出 path/SQL）。 */
const DATA_GAP_REASON_LABELS: Record<string, string> = {
  catalog_gap: 'Catalog 登记缺口',
  catalog_coverage_missing: 'Catalog 覆盖缺失',
  canonical_bars_missing: 'Canonical bars 为空',
  canonical_bar_coverage_missing: 'Canonical session 覆盖不全',
  main_contract_mapping_missing: 'MainContractMap 缺失',
}

const STALE_DOMINANT_MAPPING_DAYS = 5

/** 将 API 错误转为安全单行文案，供 chart / list 共用。 */
export function safeMarketApiError(err: unknown, fallback: string): string {
  const detail = (err as {
    response?: { data?: { detail?: { code?: unknown; facts?: { reason?: unknown } } } }
  })?.response?.data?.detail
  if (detail?.code === 'DATA_GAP') {
    const base = '请求窗口存在 DataGap，canonical 读取已失败关闭并拒绝回退到 legacy 数据。'
    const reason = typeof detail.facts?.reason === 'string' ? detail.facts.reason.trim() : ''
    const label = reason ? DATA_GAP_REASON_LABELS[reason] : undefined
    return label ? `${base}（${label}）` : base
  }
  return toSafeApiError(err, fallback)
}

/**
 * MainContractMap 映射日是否明显落后于「今天」。
 * 过期时提示换主连研究或更新映射，不假装有可读行情。
 */
export function isDominantMappingStale(
  mappingDate: string | Date | null | undefined,
  options: { today?: Date; staleDays?: number } = {},
): boolean {
  if (mappingDate == null || mappingDate === '') return false
  const today = options.today ?? new Date()
  const staleDays = options.staleDays ?? STALE_DOMINANT_MAPPING_DAYS
  const raw = typeof mappingDate === 'string' ? mappingDate.slice(0, 10) : mappingDate.toISOString().slice(0, 10)
  const parsed = Date.parse(`${raw}T00:00:00Z`)
  if (!Number.isFinite(parsed)) return false
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
  const lagDays = (todayUtc - parsed) / (24 * 60 * 60 * 1000)
  return lagDays > staleDays
}

export function staleDominantMappingMessage(): string {
  return 'MainContractMap 映射日可能过期：请改用「主连研究」或更新 rank=1 映射后再看真实主力。'
}

/** 技术观察区 EMA 文案前缀 */
export const TECHNICAL_OBSERVATION_PREFIX = '前端展示计算 · 技术观察 · 非 StrategySignal'

export function buildEmaObservationStatus(close: number, ema21: number) {
  if (close >= ema21) {
    return {
      label: 'EMA21 上方',
      type: 'error' as const,
      text: `${TECHNICAL_OBSERVATION_PREFIX} · 收盘价位于 EMA21 上方，可结合 MACD 继续观察。`,
    }
  }
  return {
    label: 'EMA21 下方',
    type: 'success' as const,
    text: `${TECHNICAL_OBSERVATION_PREFIX} · 收盘价位于 EMA21 下方，先按趋势过滤观察。`,
  }
}
