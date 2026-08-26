import { ref } from 'vue'
import type {
  MarketFrequency,
  SeriesKind,
  SubingStrategyCurrentResponse,
} from '../types/market.ts'


export interface SubingStrategyCurrentIdentity {
  seriesKind: SeriesKind
  symbol: string
  frequency: MarketFrequency
  contract: string | null
}

interface Dependencies {
  fetchCurrent: (params: {
    seriesKind: 'actual_dominant'
    symbol: string
    frequency: '15m'
  }) => Promise<SubingStrategyCurrentResponse>
}

export function useSubingStrategyCurrent(dependencies: Dependencies) {
  const current = ref<SubingStrategyCurrentResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0
  let activeIdentity: SubingStrategyCurrentIdentity | null = null

  async function refresh(identity: SubingStrategyCurrentIdentity): Promise<void> {
    const requestGeneration = ++generation
    activeIdentity = { ...identity }
    current.value = null
    error.value = null
    if (!supported(identity)) {
      loading.value = false
      return
    }
    loading.value = true
    try {
      const response = await dependencies.fetchCurrent({
        seriesKind: 'actual_dominant',
        symbol: identity.symbol,
        frequency: '15m',
      })
      if (
        requestGeneration !== generation
        || identityKey(identity) !== identityKey(activeIdentity)
        || response.series_kind !== identity.seriesKind
        || response.symbol !== identity.symbol
        || response.frequency !== identity.frequency
        || response.contract !== identity.contract
      ) return
      current.value = response
    } catch {
      if (
        requestGeneration === generation
        && identityKey(identity) === identityKey(activeIdentity)
      ) error.value = 'CURRENT_STRATEGY_UNAVAILABLE'
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function invalidate(): void {
    generation += 1
    activeIdentity = null
    current.value = null
    loading.value = false
    error.value = null
  }

  function markUnavailable(): void {
    generation += 1
    activeIdentity = null
    current.value = null
    loading.value = false
    error.value = 'CURRENT_STRATEGY_UNAVAILABLE'
  }

  return { current, loading, error, refresh, invalidate, markUnavailable, dispose: invalidate }
}

function supported(identity: SubingStrategyCurrentIdentity): identity is SubingStrategyCurrentIdentity & {
  seriesKind: 'actual_dominant'
  frequency: '15m'
  contract: string
} {
  return identity.seriesKind === 'actual_dominant'
    && identity.frequency === '15m'
    && typeof identity.contract === 'string'
    && identity.contract.length > 0
}

function identityKey(identity: SubingStrategyCurrentIdentity | null): string {
  return identity
    ? [identity.seriesKind, identity.symbol, identity.frequency, identity.contract ?? ''].join('|')
    : ''
}
