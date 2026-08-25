import { ref } from 'vue'
import type { CurrentFormalSignalsResponse } from '../api/alerts.ts'

interface CurrentFormalSignalsDependencies {
  fetchCurrent?: () => Promise<CurrentFormalSignalsResponse>
}

export function useCurrentFormalSignals(dependencies: CurrentFormalSignalsDependencies = {}) {
  const loading = ref(false)
  const stale = ref(false)
  const status = ref<CurrentFormalSignalsResponse['status'] | null>(null)
  const tradingDay = ref<string | null>(null)
  const items = ref<CurrentFormalSignalsResponse['items']>([])
  const fetchCurrent = dependencies.fetchCurrent ?? (async () => {
    const { getCurrentFormalSignals } = await import('../api/alerts.ts')
    return getCurrentFormalSignals()
  })
  let generation = 0
  let hasSuccessfulResponse = false

  async function refresh() {
    const requestGeneration = ++generation
    loading.value = true
    try {
      const response = await fetchCurrent()
      if (requestGeneration !== generation) return
      status.value = response.status
      tradingDay.value = response.trading_day
      items.value = response.items
      stale.value = false
      hasSuccessfulResponse = true
    } catch {
      if (requestGeneration !== generation) return
      if (hasSuccessfulResponse) {
        stale.value = true
      } else {
        status.value = 'unavailable'
        tradingDay.value = null
        items.value = []
        stale.value = false
      }
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function invalidate() {
    generation += 1
    loading.value = false
  }

  return { loading, stale, status, tradingDay, items, refresh, invalidate }
}
