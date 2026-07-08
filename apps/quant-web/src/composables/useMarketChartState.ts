import { ref } from 'vue'
import type { MarketWorkbenchCoverage } from '@/types/market'
import { getMarketWorkbenchCoverage } from '@/api/market'

export function useMarketChartState() {
  const loadingMeta = ref(false)
  const error = ref<string | null>(null)
  const coverage = ref<MarketWorkbenchCoverage | null>(null)

  async function loadCoverage() {
    loadingMeta.value = true
    error.value = null
    try {
      coverage.value = await getMarketWorkbenchCoverage()
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载 coverage 失败'
      coverage.value = null
    } finally {
      loadingMeta.value = false
    }
  }

  return {
    loadingMeta,
    error,
    coverage,
    loadCoverage,
  }
}
