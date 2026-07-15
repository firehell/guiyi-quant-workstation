import {
  type ContractViewMode,
  defaultContractViewForPeriod,
  resolveContractForView,
} from './marketChartWindow.ts'

export interface RouteChartQuery {
  symbol?: string | null
  product?: string | null
  contract?: string | null
  period?: string | null
  interval?: string | null
  contract_view?: string | null
  profile_id?: string | null
}

export interface ChartSelectionState {
  selectedSymbol: string
  selectedActualContract: string
  selectedPeriod: string
  contractView: ContractViewMode
}

export function resolveRoutePeriod(query: RouteChartQuery, fallback = '15m'): string {
  return query.period?.trim() || query.interval?.trim() || fallback
}

export function resolveRouteContractView(query: RouteChartQuery, period: string): ContractViewMode {
  const view = query.contract_view?.trim()
  if (view === 'continuous') return 'continuous'
  if (view === 'actual') return 'actual'
  return defaultContractViewForPeriod(period)
}

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

export function deriveBarsRequestParams(state: ChartSelectionState) {
  return {
    symbol: state.selectedSymbol,
    contract: resolveContractForView(state.selectedSymbol, state.selectedActualContract, state.contractView),
    period: state.selectedPeriod,
  }
}

export function scopedCoverageParams(query: RouteChartQuery) {
  const symbol = query.symbol?.trim() || query.product?.trim()
  if (!symbol) return undefined
  return {
    symbol,
    profile_id: query.profile_id?.trim() || undefined,
    include_paths: false as const,
  }
}
