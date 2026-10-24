import { computed, getCurrentScope, nextTick, onScopeDispose, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { BarData } from '@/types/market'

export const RANGE_DETECTOR_REQUIRED_BARS = 520
export const RANGE_DETECTOR_WARMUP_INSUFFICIENT = 'RANGE_DETECTOR_WARMUP_INSUFFICIENT'
export const RANGE_DETECTOR_WARMUP_LOAD_FAILED = 'RANGE_DETECTOR_WARMUP_LOAD_FAILED'
const MAX_WARMUP_PAGES = 64
export interface RangeDetectorOverlayWarmupOptions {
  bars: Readonly<Ref<BarData[]>>
  hasMoreBefore: Readonly<Ref<boolean>>
  enabled: Readonly<Ref<boolean>>
  identityKey: Readonly<Ref<string>>
  visibleFrom?: Readonly<Ref<string | null>>
  loadMoreBefore: () => Promise<void>
}
function validRangeBar(bar: BarData): boolean {
  return [bar.high, bar.low, bar.close].every(Number.isFinite) && bar.low <= bar.close && bar.close <= bar.high
}
function sameSegment(left: BarData, right: BarData): boolean {
  return left.physicalContract === right.physicalContract && left.calculationSegmentId === right.calculationSegmentId
}
export function useRangeDetectorOverlayWarmup(options: RangeDetectorOverlayWarmupOptions) {
  const anchorTime = ref<string | null>(null), loading = ref(false), unavailableReason = ref<string | null>(null)
  const status = computed(() => !options.enabled.value ? 'idle' : loading.value ? 'loading' : unavailableReason.value === RANGE_DETECTOR_WARMUP_LOAD_FAILED ? 'failed' : unavailableReason.value ? 'insufficient' : anchorTime.value ? 'ready' : 'idle')
  let generation = 0, activeIdentity: string | null = null, activeRun: Promise<void> | null = null
  function reset(): void {
    generation++; activeIdentity = null; activeRun = null
    anchorTime.value = null; loading.value = false; unavailableReason.value = null
  }
  function requirement() {
    const bars = options.bars.value
    const visible = options.visibleFrom?.value
    const target = visible ? bars.findIndex(bar => Date.parse(bar.time) >= Date.parse(visible)) : bars.length - 1
    if (target < 0) return { enough: false, boundary: true }
    if (!validRangeBar(bars[target])) return { enough: false, boundary: true }
    let start = target
    while (start > 0 && validRangeBar(bars[start - 1]) && sameSegment(bars[start - 1], bars[target])) start--
    return { enough: target - start >= RANGE_DETECTOR_REQUIRED_BARS, boundary: start > 0 }
  }
  function ensureReady(): Promise<void> {
    if (!options.enabled.value) { reset(); return Promise.resolve() }
    const identity = options.identityKey.value
    if (activeIdentity !== identity) { reset(); activeIdentity = identity }
    if (activeRun) return activeRun
    const current = generation
    loading.value = true; unavailableReason.value = null
    const run = Promise.resolve().then(async () => {
      try {
        for (let pages = 0; current === generation && options.enabled.value; pages++) {
          const bars = options.bars.value
          anchorTime.value = bars[0]?.time ?? null
          const state = requirement()
          if (state.enough) return
          if (state.boundary || !options.hasMoreBefore.value) { unavailableReason.value = RANGE_DETECTOR_WARMUP_INSUFFICIENT; return }
          if (pages >= MAX_WARMUP_PAGES) throw new Error('WARMUP_PAGE_BUDGET')
          const first = bars[0]?.time, count = bars.length
          await options.loadMoreBefore(); await nextTick()
          if (current !== generation || !options.enabled.value) return
          if (options.bars.value.length <= count || options.bars.value[0]?.time === first) {
            if (!options.hasMoreBefore.value) { unavailableReason.value = RANGE_DETECTOR_WARMUP_INSUFFICIENT; return }
            throw new Error('NO_HISTORY_PROGRESS')
          }
        }
      } catch {
        if (current === generation && options.enabled.value) { anchorTime.value = options.bars.value[0]?.time ?? null; unavailableReason.value = RANGE_DETECTOR_WARMUP_LOAD_FAILED }
      } finally {
        if (current === generation) loading.value = false
        if (activeRun === run) activeRun = null
      }
    })
    activeRun = run
    return run
  }
  watch([() => options.enabled.value, () => options.identityKey.value], () => {
    if (!options.enabled.value) reset()
    else void ensureReady()
  }, { immediate: true })
  watch([() => options.bars.value, () => options.visibleFrom?.value], () => {
    if (!options.enabled.value) return
    // Bar updates may revise old boxes; the calculation anchor always follows the loaded prefix.
    anchorTime.value = options.bars.value[0]?.time ?? null
    void ensureReady()
  })
  if (getCurrentScope()) onScopeDispose(reset)
  return { anchorTime, loading, unavailableReason, status, ensureReady, reset }
}
