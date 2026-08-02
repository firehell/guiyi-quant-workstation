import {
  type ContractViewMode,
  defaultContractViewForPeriod,
  resolveContractForView,
} from './marketChartWindow.ts'

/** 路由 query 中与 K 线图表相关的字段 */
export interface RouteChartQuery {
  symbol?: string | null
  product?: string | null
  contract?: string | null
  period?: string | null
  interval?: string | null
  contract_view?: string | null
  access_mode?: string | null
}

/** 市场数据访问模式：浏览器默认 / 研究模式 */
export type MarketAccessMode = 'browser' | 'research'

/**
 * 从路由 query 解析访问模式，默认 browser。
 */
export function resolveRouteAccessMode(query: RouteChartQuery): MarketAccessMode {
  return query.access_mode?.trim() === 'research' ? 'research' : 'browser'
}

/** 图表当前选中的品种、合约、周期与视图模式 */
export interface ChartSelectionState {
  selectedSymbol: string
  selectedActualContract: string
  selectedPeriod: string
  contractView: ContractViewMode
}

/**
 * 从路由 query 解析 K 线周期，支持 period / interval 别名，默认 15m。
 */
export function resolveRoutePeriod(query: RouteChartQuery, fallback = '15m'): string {
  return query.period?.trim() || query.interval?.trim() || fallback
}

/**
 * 从路由 query 解析合约视图（连续/具体），未指定时按周期默认。
 */
export function resolveRouteContractView(query: RouteChartQuery, period: string): ContractViewMode {
  const view = query.contract_view?.trim()
  if (view === 'continuous') return 'continuous'
  if (view === 'actual') return 'actual'
  return defaultContractViewForPeriod(period)
}

/**
 * 从路由 query 构建图表选中状态；缺少 symbol 或 contract 时返回 null。
 */
export function applyRouteSelectionFromQuery(query: RouteChartQuery): ChartSelectionState | null {
  const symbol = query.symbol?.trim() || query.product?.trim()
  const contract = query.contract?.trim()
  if (!symbol || !contract) return null

  const period = resolveRoutePeriod(query)
  return {
    selectedSymbol: symbol,
    selectedActualContract: contract,
    selectedPeriod: period,
    contractView: resolveRouteContractView(query, period),
  }
}

/**
 * 根据选中状态推导 bars API 请求参数（含连续合约解析）。
 */
export function deriveBarsRequestParams(state: ChartSelectionState) {
  return {
    symbol: state.selectedSymbol,
    contract: resolveContractForView(state.selectedSymbol, state.selectedActualContract, state.contractView),
    period: state.selectedPeriod,
  }
}

/**
 * 构建覆盖范围查询参数；无 symbol 时返回 undefined。
 */
export function scopedCoverageParams(query: RouteChartQuery) {
  const symbol = query.symbol?.trim() || query.product?.trim()
  if (!symbol) return undefined
  const accessMode = resolveRouteAccessMode(query)
  const actualContract = query.contract?.trim()
  const period = query.period?.trim() || query.interval?.trim()
  const contract =
    accessMode === 'research' && actualContract && period
      ? resolveContractForView(symbol, actualContract, resolveRouteContractView(query, period))
      : undefined
  return {
    symbol,
    ...(contract && period ? { contract, period } : {}),
    include_paths: false as const,
  }
}
