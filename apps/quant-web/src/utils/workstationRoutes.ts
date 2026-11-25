import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import { parseMarketDetailRoute, serializeMarketDetailIdentity } from './marketDetailRoute.ts'
import type { WorkstationContractActivity } from './workstationAccounts.ts'

const chartKey = 'guiyi.workstation.chart.v1'

export function workstationChartLink(identity: MarketDetailIdentity) {
  return { name: 'market-chart', query: serializeMarketDetailIdentity(identity) }
}

export function activityChartLink(row: Pick<WorkstationContractActivity, 'source' | 'product' | 'contract'>) {
  return {
    ...workstationChartLink({
      view: row.source, symbol: row.product, contract: row.contract,
      seriesKind: 'contract', frequency: row.source === 'htdy' ? '60m' : '30m',
    }),
    state: { showWorkstationExecutions: true },
  }
}

export function lastWorkstationChart() {
  try {
    const stored = localStorage.getItem(chartKey)
    const route = stored && parseMarketDetailRoute(JSON.parse(stored))
    if (route && route.kind === 'valid') return workstationChartLink(route.identity)
  } catch { /* Storage can be unavailable in private browsing. */ }
  return workstationChartLink({ view: 'free', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '60m' })
}

export function rememberWorkstationChart(identity: MarketDetailIdentity) {
  const { focusBarEnd: _focus, homeContext: _context, ...chart } = identity
  try { localStorage.setItem(chartKey, JSON.stringify(serializeMarketDetailIdentity(chart))) } catch { /* Optional preference. */ }
}

const newowModeKey = 'guiyi.workstation.after-market-mode.v1'

export function workstationNewowMode(): 'trend' | 'oscillation' | 'dual' {
  try {
    const mode = localStorage.getItem(newowModeKey)
    if (mode === 'oscillation' || mode === 'dual') return mode
  } catch { /* Optional preference. */ }
  return 'trend'
}

export function rememberWorkstationNewowMode(identity: MarketDetailIdentity) {
  const mode = identity.newowMode === 'dual' ? 'dual' : identity.strategy === 'oscillation' ? 'oscillation' : 'trend'
  try { localStorage.setItem(newowModeKey, mode) } catch { /* Optional preference. */ }
}
