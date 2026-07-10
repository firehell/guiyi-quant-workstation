import { ref } from 'vue'
import type { MarketWorkbenchCoverage } from '@/types/market'
import { getMarketWorkbenchCoverage, type MarketWorkbenchCoverageParams } from '@/api/market'

export function useMarketChartState() {
  const loadingMeta = ref(false)
  const metaWarning = ref<string | null>(null)
  const coverage = ref<MarketWorkbenchCoverage | null>(null)

  async function loadCoverage(params?: MarketWorkbenchCoverageParams) {
    loadingMeta.value = true
    metaWarning.value = null
    try {
      coverage.value = await getMarketWorkbenchCoverage(params)
    } catch (err) {
      metaWarning.value = err instanceof Error ? err.message : '加载 coverage 失败'
      coverage.value = null
    } finally {
      loadingMeta.value = false
    }
  }

  return {
    loadingMeta,
    metaWarning,
    coverage,
    loadCoverage,
  }
}
