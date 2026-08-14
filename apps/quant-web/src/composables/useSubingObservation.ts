import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type {
  BarData,
  DominantContractItem,
  MarketFrequency,
  ResearchOverlayId,
  SubingResearchResponse,
} from '../types/market.ts'
import {
  isSubingSupportedFrequency,
  shouldScheduleSubingCompanionRefresh,
} from '../types/market.ts'


const COMMON_BOUNDARY_REFRESH_MS = 600

interface Dependencies {
  selectedOverlay: Ref<ResearchOverlayId>
  symbol: Ref<string>
  frequency: Ref<MarketFrequency>
  dominants: Ref<DominantContractItem[]>
  selectedDominant: ComputedRef<DominantContractItem | undefined>
  followLatest: Ref<boolean>
  fetchSnapshot: (params: {
    symbol: string
    frequency: '5m' | '15m' | '1d'
  }) => Promise<SubingResearchResponse>
  fetchDominants: () => Promise<{ items: DominantContractItem[] }>
  refreshSeries: () => Promise<boolean>
  visibleBars: () => BarData[]
  replaceChartBars: (bars: BarData[], preserveViewport?: boolean) => void
  scheduleTimeout?: (callback: () => void, delayMs: number) => unknown
  clearTimeout?: (handle: unknown) => void
}

export function useSubingObservation(dependencies: Dependencies) {
  const subing = ref<SubingResearchResponse | null>(null)
  const subingLoading = ref(false)
  const subingError = ref(false)
  const subingSupported = computed(() => (
    isSubingSupportedFrequency(dependencies.frequency.value)
  ))
  const scheduleTimeout = dependencies.scheduleTimeout
    ?? ((callback, delayMs) => setTimeout(callback, delayMs))
  const clearScheduledTimeout = dependencies.clearTimeout
    ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>))
  let generation = 0
  let refreshTimer: unknown = null

  function reset(): void {
    generation += 1
    clearRefreshTimer()
    subing.value = null
    subingError.value = false
    subingLoading.value = dependencies.selectedOverlay.value === 'subing'
      && subingSupported.value
    dependencies.replaceChartBars(dependencies.visibleBars())
  }

  async function refresh(allowDelayedRefresh = true): Promise<void> {
    const requestedSymbol = dependencies.symbol.value
    const requestedFrequency = dependencies.frequency.value
    if (
      dependencies.selectedOverlay.value !== 'subing'
      || !requestedSymbol
      || !isSubingSupportedFrequency(requestedFrequency)
    ) {
      subingLoading.value = false
      return
    }
    if (allowDelayedRefresh) clearRefreshTimer()
    const requestGeneration = ++generation
    subingLoading.value = true
    subingError.value = false
    try {
      const expectedDominant = dependencies.selectedDominant.value
      if (!expectedDominant) throw new Error('dominant metadata unavailable')
      let snapshot = await dependencies.fetchSnapshot({
        symbol: requestedSymbol,
        frequency: requestedFrequency,
      })
      if (!isCurrent(requestGeneration, requestedSymbol, requestedFrequency)) return
      if (!isSnapshotForDominant(snapshot, expectedDominant)) {
        subing.value = null
        replaceVisibleBars()
        const refreshedDominants = await dependencies.fetchDominants()
        if (!isCurrent(requestGeneration, requestedSymbol, requestedFrequency)) return
        dependencies.dominants.value = refreshedDominants.items
        const refreshedExpected = dependencies.selectedDominant.value
        if (!refreshedExpected) throw new Error('dominant metadata unavailable')
        if (!await dependencies.refreshSeries()) {
          throw new Error('dominant contract series reload failed')
        }
        if (!isCurrent(requestGeneration, requestedSymbol, requestedFrequency)) return
        snapshot = await dependencies.fetchSnapshot({
          symbol: requestedSymbol,
          frequency: requestedFrequency,
        })
        if (!isCurrent(requestGeneration, requestedSymbol, requestedFrequency)) return
        if (!isSnapshotForDominant(snapshot, refreshedExpected)) {
          throw new Error('SuBing snapshot dominant identity mismatch')
        }
      }
      subing.value = snapshot
      replaceVisibleBars()
      if (allowDelayedRefresh && shouldScheduleSubingCompanionRefresh(snapshot)) {
        refreshTimer = scheduleTimeout(() => {
          refreshTimer = null
          if (requestGeneration !== generation) return
          void refresh(false)
        }, COMMON_BOUNDARY_REFRESH_MS)
      }
    } catch {
      if (requestGeneration !== generation) return
      subing.value = null
      subingError.value = true
      replaceVisibleBars()
    } finally {
      if (requestGeneration === generation) subingLoading.value = false
    }
  }

  function isCurrent(
    requestGeneration: number,
    requestedSymbol: string,
    requestedFrequency: MarketFrequency,
  ): boolean {
    return requestGeneration === generation
      && dependencies.selectedOverlay.value === 'subing'
      && dependencies.symbol.value === requestedSymbol
      && dependencies.frequency.value === requestedFrequency
  }

  function replaceVisibleBars(): void {
    dependencies.replaceChartBars(
      dependencies.visibleBars(),
      !dependencies.followLatest.value,
    )
  }

  function clearRefreshTimer(): void {
    if (refreshTimer === null) return
    clearScheduledTimeout(refreshTimer)
    refreshTimer = null
  }

  function dispose(): void {
    generation += 1
    clearRefreshTimer()
  }

  return {
    subing,
    subingLoading,
    subingError,
    subingSupported,
    reset,
    refresh,
    dispose,
  }
}

function isSnapshotForDominant(
  snapshot: SubingResearchResponse,
  expected: DominantContractItem,
): boolean {
  return snapshot.actual_contract === expected.actual_contract
    && snapshot.dominant_mapping_date === expected.dominant_mapping_date
}
