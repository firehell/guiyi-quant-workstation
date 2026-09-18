import { computed, readonly, shallowRef } from 'vue'

import { getNewowProductCapabilities } from '../api/newowProduct.ts'
import type {
  NewowProductCapabilities,
  NewowProductFrequency,
  NewowProductSection,
} from '../types/newowProduct.ts'

type FetchCapabilities = () => Promise<NewowProductCapabilities>
type CapabilityState = 'not_requested' | 'loading' | 'ready' | 'unavailable'

export function useNewowCapabilities(fetchCapabilities: FetchCapabilities = getNewowProductCapabilities) {
  const capabilities = shallowRef<NewowProductCapabilities | null>(null)
  const state = shallowRef<CapabilityState>('not_requested')
  const error = shallowRef<string | null>(null)
  let inFlight: Promise<void> | null = null

  function load(): Promise<void> {
    if (state.value === 'ready') return Promise.resolve()
    if (inFlight !== null) return inFlight
    state.value = 'loading'
    error.value = null
    inFlight = fetchCapabilities()
      .then((value) => {
        capabilities.value = value
        state.value = 'ready'
      })
      .catch(() => {
        capabilities.value = null
        state.value = 'unavailable'
        error.value = '牛哇开放能力暂不可用，已停止推断默认周期。'
      })
      .finally(() => { inFlight = null })
    return inFlight
  }

  const openFrequencies = computed<readonly NewowProductFrequency[]>(() => capabilities.value?.open_frequencies ?? [])
  const openFrequenciesFor = (symbol: string): readonly NewowProductFrequency[] =>
    capabilities.value?.schema_version === 'newow_product_capabilities_v5' && symbol.toLowerCase() !== 'au'
      ? [] : openFrequencies.value
  const isFrequencyOpen = (frequency: NewowProductFrequency, symbol = '') =>
    openFrequenciesFor(symbol).includes(frequency)
  const isSectionOpen = (section: NewowProductSection) => (capabilities.value?.open_sections as readonly string[] | undefined)?.includes(section) === true
  const deferredFrequencyReason = (frequency: NewowProductFrequency) => capabilities.value?.deferred_frequencies.find(item => item.frequency === frequency)?.reason_code ?? null
  const deferredSectionReason = (section: NewowProductSection) => capabilities.value?.deferred_sections.find(item => item.section === section)?.reason_code ?? null

  return {
    capabilities: readonly(capabilities),
    state: readonly(state),
    error: readonly(error),
    openFrequencies,
    openFrequenciesFor,
    load,
    isFrequencyOpen,
    isSectionOpen,
    deferredFrequencyReason,
    deferredSectionReason,
  }
}
