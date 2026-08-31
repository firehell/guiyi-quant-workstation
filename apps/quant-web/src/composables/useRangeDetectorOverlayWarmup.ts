import { ref, watch } from 'vue'
import type { Ref } from 'vue'

import type { BarData } from '@/types/market'

export const RANGE_DETECTOR_REQUIRED_BARS = 520
export const RANGE_DETECTOR_WARMUP_INSUFFICIENT = 'RANGE_DETECTOR_WARMUP_INSUFFICIENT'
export const RANGE_DETECTOR_WARMUP_LOAD_FAILED = 'RANGE_DETECTOR_WARMUP_LOAD_FAILED'

export interface RangeDetectorOverlayWarmupOptions {
  bars: Readonly<Ref<BarData[]>>
  hasMoreBefore: Readonly<Ref<boolean>>
  enabled: Readonly<Ref<boolean>>
  identityKey: Readonly<Ref<string>>
  loadMoreBefore: () => Promise<void>
}

export function useRangeDetectorOverlayWarmup(options: RangeDetectorOverlayWarmupOptions) {
  const anchorTime = ref<string | null>(null)
  const loading = ref(false)
  const unavailableReason = ref<string | null>(null)
  let generation = 0
  let activeIdentity: string | null = null
  let activeRun: Promise<void> | null = null

  function reset(): void {
    generation += 1
    activeIdentity = null
    activeRun = null
    anchorTime.value = null
    loading.value = false
    unavailableReason.value = null
  }

  function ensureReady(): Promise<void> {
    if (!options.enabled.value) {
      reset()
      return Promise.resolve()
    }
    const identity = options.identityKey.value
    if (activeIdentity === identity && activeRun) return activeRun
    const currentGeneration = ++generation
    activeIdentity = identity
    anchorTime.value = null
    unavailableReason.value = null
    loading.value = true
    activeRun = (async () => {
      try {
        while (
          currentGeneration === generation
          && options.enabled.value
          && options.bars.value.length < RANGE_DETECTOR_REQUIRED_BARS
          && options.hasMoreBefore.value
        ) {
          const barCountBeforeLoad = options.bars.value.length
          await options.loadMoreBefore()
          if (currentGeneration !== generation || !options.enabled.value) return
          if (options.bars.value.length <= barCountBeforeLoad) {
            anchorTime.value = null
            unavailableReason.value = RANGE_DETECTOR_WARMUP_LOAD_FAILED
            return
          }
        }
        if (currentGeneration !== generation || !options.enabled.value) return
        if (options.bars.value.length > 0) anchorTime.value = options.bars.value[0].time
        unavailableReason.value = options.bars.value.length < 500
          ? RANGE_DETECTOR_WARMUP_INSUFFICIENT
          : null
      } catch {
        if (currentGeneration === generation && options.enabled.value) {
          anchorTime.value = null
          unavailableReason.value = RANGE_DETECTOR_WARMUP_LOAD_FAILED
        }
      }
    })().finally(() => {
      if (currentGeneration === generation) loading.value = false
    })
    return activeRun
  }

  watch(
    [() => options.enabled.value, () => options.identityKey.value],
    () => {
      if (!options.enabled.value) reset()
      else void ensureReady()
    },
    { immediate: true },
  )
  watch(
    () => options.bars.value.length,
    (barCount) => {
      if (
        options.enabled.value
        && activeIdentity === options.identityKey.value
        && unavailableReason.value === RANGE_DETECTOR_WARMUP_INSUFFICIENT
        && barCount >= 500
      ) {
        unavailableReason.value = null
      }
    },
  )

  return { anchorTime, loading, unavailableReason, ensureReady, reset }
}
