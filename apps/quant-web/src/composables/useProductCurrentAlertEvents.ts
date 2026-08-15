import { ref, watch, type Ref } from 'vue'
import type { ProductCurrentAlertEventsResponse } from '../api/alerts.ts'

interface Dependencies {
  symbol: Ref<string>
  fetchCurrentEvents?: (symbol: string) => Promise<ProductCurrentAlertEventsResponse>
}

export function useProductCurrentAlertEvents(dependencies: Dependencies) {
  const loading = ref(false)
  const status = ref<ProductCurrentAlertEventsResponse['status'] | null>(null)
  const tradingDay = ref<string | null>(null)
  const items = ref<ProductCurrentAlertEventsResponse['items']>([])
  const fetchCurrentEvents = dependencies.fetchCurrentEvents ?? (async (symbol: string) => {
    const { getProductCurrentAlertEvents } = await import('../api/alerts.ts')
    return getProductCurrentAlertEvents(symbol)
  })
  let generation = 0

  async function refresh(): Promise<void> {
    const requestedSymbol = dependencies.symbol.value
    if (!requestedSymbol) return
    const requestGeneration = ++generation
    loading.value = true
    try {
      const response = await fetchCurrentEvents(requestedSymbol)
      if (!isCurrent(requestGeneration, requestedSymbol)) return
      status.value = response.status
      tradingDay.value = response.trading_day
      items.value = response.items
    } catch {
      if (!isCurrent(requestGeneration, requestedSymbol)) return
      status.value = 'unavailable'
      tradingDay.value = null
      items.value = []
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  const stop = watch(dependencies.symbol, () => { void refresh() })

  function isCurrent(requestGeneration: number, requestedSymbol: string): boolean {
    return requestGeneration === generation && dependencies.symbol.value === requestedSymbol
  }

  function dispose(): void {
    generation += 1
    stop()
    loading.value = false
  }

  return { loading, status, tradingDay, items, refresh, dispose }
}
