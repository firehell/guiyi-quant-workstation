import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import type { BarData } from '../src/types/market.ts'
import {
  RANGE_DETECTOR_REQUIRED_BARS,
  useRangeDetectorOverlayWarmup,
} from '../src/composables/useRangeDetectorOverlayWarmup.ts'

function barSeries(count: number, start = 0): BarData[] {
  return Array.from({ length: count }, (_, index) => {
    const sequence = start + index
    return {
      time: `2026-01-${String(Math.floor(sequence / 24) + 1).padStart(2, '0')}T${String(sequence % 24).padStart(2, '0')}:00:00Z`,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 1,
    }
  })
}

test('loads older pages until the fixed Range Detector warm-up is ready', async () => {
  const bars = ref(barSeries(300, 220))
  const hasMoreBefore = ref(true)
  const enabled = ref(false)
  const identityKey = ref('continuous|jm||15m')
  let calls = 0
  const warmup = useRangeDetectorOverlayWarmup({
    bars,
    hasMoreBefore,
    enabled,
    identityKey,
    async loadMoreBefore() {
      calls += 1
      bars.value = barSeries(RANGE_DETECTOR_REQUIRED_BARS)
      hasMoreBefore.value = false
    },
  })

  enabled.value = true
  await warmup.ensureReady()

  assert.equal(calls, 1)
  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  assert.equal(warmup.loading.value, false)
  assert.equal(warmup.unavailableReason.value, null)
})

test('reports an explicit unavailable reason when available history is below ATR warm-up', async () => {
  const bars = ref(barSeries(420, 100))
  const warmup = useRangeDetectorOverlayWarmup({
    bars,
    hasMoreBefore: ref(false),
    enabled: ref(true),
    identityKey: ref('continuous|jm||15m'),
    async loadMoreBefore() {},
  })

  await warmup.ensureReady()

  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  assert.equal(warmup.unavailableReason.value, 'RANGE_DETECTOR_WARMUP_INSUFFICIENT')
})

test('identity change discards a stale warm-up generation', async () => {
  const bars = ref(barSeries(300, 220))
  const hasMoreBefore = ref(true)
  const enabled = ref(true)
  const identityKey = ref('continuous|jm||15m')
  const pending: Array<() => void> = []
  const warmup = useRangeDetectorOverlayWarmup({
    bars,
    hasMoreBefore,
    enabled,
    identityKey,
    loadMoreBefore: () => new Promise<void>((resolve) => pending.push(resolve)),
  })

  const stale = warmup.ensureReady()
  await Promise.resolve()
  identityKey.value = 'contract|jm|JM2609|15m'
  await nextTick()
  bars.value = barSeries(RANGE_DETECTOR_REQUIRED_BARS, 1_000)
  hasMoreBefore.value = false
  pending.forEach((resolve) => resolve())
  await stale
  await Promise.resolve()

  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  assert.equal(warmup.unavailableReason.value, null)
})

test('a manual prepend does not move a frozen calculation anchor', async () => {
  const bars = ref(barSeries(RANGE_DETECTOR_REQUIRED_BARS, 220))
  const warmup = useRangeDetectorOverlayWarmup({
    bars,
    hasMoreBefore: ref(false),
    enabled: ref(true),
    identityKey: ref('continuous|jm||15m'),
    async loadMoreBefore() {},
  })

  await warmup.ensureReady()
  const frozen = warmup.anchorTime.value
  bars.value = [...barSeries(20, 0), ...bars.value]
  await nextTick()

  assert.equal(warmup.anchorTime.value, frozen)
})
