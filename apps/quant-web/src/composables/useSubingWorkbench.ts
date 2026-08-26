import type { getSubingDailyWatchCurrent } from '../api/market.ts'
import type { SubingDailyWatchCurrentResponse } from '../types/market.ts'
import { useLatestResource } from './useLatestResource.ts'

export interface SubingWorkbenchDependencies {
  fetchDailyWatch: typeof getSubingDailyWatchCurrent
}

export function useSubingWorkbench(dependencies: SubingWorkbenchDependencies) {
  const daily = useLatestResource<SubingDailyWatchCurrentResponse>({
    fetch: dependencies.fetchDailyWatch,
  })
  let disposed = false

  async function refreshAll() {
    await daily.refresh()
  }

  async function refreshOperational() {
    await daily.refresh()
  }

  function dispose() {
    if (disposed) return
    disposed = true
    daily.invalidate()
  }

  return {
    dailyWatch: daily.data,
    dailyLoading: daily.loading,
    dailyStale: daily.failed,
    refreshAll,
    refreshOperational,
    dispose,
  }
}
