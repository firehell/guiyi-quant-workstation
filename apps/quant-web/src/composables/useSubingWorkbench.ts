import type { getCurrentFormalSignals } from '../api/alerts.ts'
import type { getSubingDailyWatchCurrent } from '../api/market.ts'
import type { SubingDailyWatchCurrentResponse } from '../types/market.ts'
import { useCurrentFormalSignals } from './useCurrentFormalSignals.ts'
import { useLatestResource } from './useLatestResource.ts'

export interface SubingWorkbenchDependencies {
  fetchFormal: typeof getCurrentFormalSignals
  fetchDailyWatch: typeof getSubingDailyWatchCurrent
}

export function useSubingWorkbench(dependencies: SubingWorkbenchDependencies) {
  const formal = useCurrentFormalSignals({ fetchCurrent: dependencies.fetchFormal })
  const daily = useLatestResource<SubingDailyWatchCurrentResponse>({
    fetch: dependencies.fetchDailyWatch,
  })
  let disposed = false

  async function refreshAll() {
    await Promise.all([formal.refresh(), daily.refresh()])
  }

  async function refreshOperational() {
    await Promise.all([formal.refresh(), daily.refresh()])
  }

  function dispose() {
    if (disposed) return
    disposed = true
    formal.invalidate()
    daily.invalidate()
  }

  return {
    formalStatus: formal.status,
    formalTradingDay: formal.tradingDay,
    formalItems: formal.items,
    formalLoading: formal.loading,
    formalStale: formal.stale,
    dailyWatch: daily.data,
    dailyLoading: daily.loading,
    dailyStale: daily.failed,
    refreshAll,
    refreshOperational,
    dispose,
  }
}
