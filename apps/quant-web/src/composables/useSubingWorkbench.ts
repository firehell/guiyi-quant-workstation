import type { getCurrentStrategyActions } from '../api/alerts.ts'
import type { getSubingDailyWatchCurrent } from '../api/market.ts'
import type { SubingDailyWatchCurrentResponse } from '../types/market.ts'
import { useCurrentStrategyActions } from './useCurrentStrategyActions.ts'
import { useLatestResource } from './useLatestResource.ts'

export interface SubingWorkbenchDependencies {
  fetchStrategyActions: typeof getCurrentStrategyActions
  fetchDailyWatch: typeof getSubingDailyWatchCurrent
}

export function useSubingWorkbench(dependencies: SubingWorkbenchDependencies) {
  const strategy = useCurrentStrategyActions({ fetchCurrent: dependencies.fetchStrategyActions })
  const daily = useLatestResource<SubingDailyWatchCurrentResponse>({
    fetch: dependencies.fetchDailyWatch,
  })
  let disposed = false

  async function refreshAll() {
    await Promise.all([strategy.refresh(), daily.refresh()])
  }

  async function refreshOperational() {
    await Promise.all([strategy.refresh(), daily.refresh()])
  }

  function dispose() {
    if (disposed) return
    disposed = true
    strategy.invalidate()
    daily.invalidate()
  }

  return {
    strategyStatus: strategy.status,
    strategyTradingDay: strategy.tradingDay,
    strategyItems: strategy.items,
    strategyLoading: strategy.loading,
    strategyStale: strategy.stale,
    dailyWatch: daily.data,
    dailyLoading: daily.loading,
    dailyStale: daily.failed,
    refreshAll,
    refreshOperational,
    dispose,
  }
}
