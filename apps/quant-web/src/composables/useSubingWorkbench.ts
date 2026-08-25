import { ref, watch } from 'vue'
import type { CurrentFormalSignalItem } from '../api/alerts.ts'
import type { getCurrentFormalSignals } from '../api/alerts.ts'
import type { getEventStates } from '../api/executionReview.ts'
import type { getSubingDailyWatchCurrent } from '../api/market.ts'
import type { SubingDailyWatchCurrentResponse } from '../types/market.ts'
import type { EventState } from '../types/executionReview.ts'
import { useCurrentFormalSignals } from './useCurrentFormalSignals.ts'
import { useLatestResource } from './useLatestResource.ts'

export interface SubingWorkbenchDependencies {
  fetchFormal: typeof getCurrentFormalSignals
  fetchDailyWatch: typeof getSubingDailyWatchCurrent
  fetchEventStates: typeof getEventStates
}

export function useSubingWorkbench(dependencies: SubingWorkbenchDependencies) {
  const formal = useCurrentFormalSignals({ fetchCurrent: dependencies.fetchFormal })
  const daily = useLatestResource<SubingDailyWatchCurrentResponse>({
    fetch: dependencies.fetchDailyWatch,
  })
  const formalEventStates = ref<Record<number, EventState>>({})
  let eventStateGeneration = 0
  let formalEventIdentity = ''
  let disposed = false

  const stopFormalWatch = watch(
    [formal.status, formal.items],
    () => {
      const generation = ++eventStateGeneration
      const eventIds = formal.status.value === 'ready'
        ? [...new Set(formal.items.value.map((item: CurrentFormalSignalItem) => item.id))]
          .sort((left, right) => left - right)
        : []
      const nextIdentity = eventIds.join(',')
      const identityChanged = nextIdentity !== formalEventIdentity
      if (identityChanged) {
        formalEventIdentity = nextIdentity
        formalEventStates.value = {}
      }
      if (disposed || eventIds.length === 0) return
      void dependencies.fetchEventStates(eventIds).then((response) => {
        if (disposed || generation !== eventStateGeneration) return
        formalEventStates.value = Object.fromEntries(
          response.items.map((item) => [item.event_id, item]),
        )
      }).catch(() => {
        if (!disposed && generation === eventStateGeneration && identityChanged) {
          formalEventStates.value = {}
        }
      })
    },
    { flush: 'sync' },
  )

  async function refreshAll() {
    await Promise.all([formal.refresh(), daily.refresh()])
  }

  async function refreshOperational() {
    await Promise.all([formal.refresh(), daily.refresh()])
  }

  function dispose() {
    if (disposed) return
    disposed = true
    stopFormalWatch()
    eventStateGeneration += 1
    formal.invalidate()
    daily.invalidate()
  }

  return {
    formalStatus: formal.status,
    formalTradingDay: formal.tradingDay,
    formalItems: formal.items,
    formalEventStates,
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
