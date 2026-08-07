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

/** 保留在 URL 中的 deep-link 字段 */
export interface MarketChartDeepLink {
  strategy?: string | null
  time?: string | null
  datetime?: string | null
  signal_layer?: string | null
  signal_id?: string | null
  signal_event_id?: string | null
  review_id?: string | null
  return_route?: string | null
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
    signal_layer: deepLink.signal_layer?.trim() || undefined,
    signal_id: deepLink.signal_id?.trim() || undefined,
    signal_event_id: deepLink.signal_event_id?.trim() || undefined,
    review_id: deepLink.review_id?.trim() || undefined,
    return_route: deepLink.return_route?.trim() || undefined,
  }
}

/** 数据质量 failed 时的观察文案（禁止拼接 file_path）。 */
export function qualityFailedObservationText(): string {
  return '数据质量为 failed，暂不可展示。'
}

/** 将 API 错误转为安全单行文案，供 chart / list 共用。 */
export function safeMarketApiError(err: unknown, fallback: string): string {
  const detail = (err as {
    response?: { data?: { detail?: { code?: unknown } } }
  })?.response?.data?.detail
  if (detail?.code === 'DATA_GAP') {
    return '请求窗口存在 DataGap，canonical 读取已失败关闭并拒绝回退到 legacy 数据。'
  }
  return toSafeApiError(err, fallback)
}

/** 技术观察区 EMA 文案前缀 */
export const TECHNICAL_OBSERVATION_PREFIX = '前端展示计算 · 技术观察 · 非 StrategySignal'

export function buildEmaObservationStatus(close: number, ema21: number) {
  if (close >= ema21) {
    return {
      label: 'EMA21 上方',
      type: 'error' as const,
      text: `${TECHNICAL_OBSERVATION_PREFIX} · 收盘价位于 EMA21 上方，可结合 MACD 与信号复核继续验证。`,
    }
  }
  return {
    label: 'EMA21 下方',
    type: 'success' as const,
    text: `${TECHNICAL_OBSERVATION_PREFIX} · 收盘价位于 EMA21 下方，先按趋势过滤观察。`,
  }
}
