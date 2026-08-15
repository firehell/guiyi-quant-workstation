import { ref } from 'vue'
import type { CurrentFormalSignalsResponse } from '../api/alerts.ts'

interface CurrentFormalSignalsDependencies {
  fetchCurrent?: () => Promise<CurrentFormalSignalsResponse>
}

export function useCurrentFormalSignals(dependencies: CurrentFormalSignalsDependencies = {}) {
  const loading = ref(false)
  const status = ref<CurrentFormalSignalsResponse['status'] | null>(null)
  const tradingDay = ref<string | null>(null)
  const items = ref<CurrentFormalSignalsResponse['items']>([])
  const fetchCurrent = dependencies.fetchCurrent ?? (async () => {
    const { getCurrentFormalSignals } = await import('../api/alerts.ts')
    return getCurrentFormalSignals()
  })

  async function refresh() {
    loading.value = true
    try {
      const response = await fetchCurrent()
      status.value = response.status
      tradingDay.value = response.trading_day
      items.value = response.items
    } catch {
      status.value = 'unavailable'
      tradingDay.value = null
      items.value = []
    } finally {
      loading.value = false
    }
  }

  return { loading, status, tradingDay, items, refresh }
}
