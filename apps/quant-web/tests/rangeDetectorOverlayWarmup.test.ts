import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, nextTick, ref } from 'vue'

import type { BarData } from '../src/types/market.ts'
import {
  RANGE_DETECTOR_REQUIRED_BARS,
  RANGE_DETECTOR_WARMUP_INSUFFICIENT,
  RANGE_DETECTOR_WARMUP_LOAD_FAILED,
  useRangeDetectorOverlayWarmup,
} from '../src/composables/useRangeDetectorOverlayWarmup.ts'

function barSeries(count: number, start = 0): BarData[] {
  return Array.from({ length: count }, (_, index) => {
    const sequence = start + index
    return {
      time: new Date(Date.UTC(2026, 0, 1) + sequence * 3600000).toISOString(),
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
      bars.value = barSeries(RANGE_DETECTOR_REQUIRED_BARS + 1)
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

test('same identity requires all 520 warm-up bars', async () => {
  const bars = ref(barSeries(499))
  let loadCalls = 0
  const warmup = useRangeDetectorOverlayWarmup({
    bars,
    hasMoreBefore: ref(false),
    enabled: ref(true),
    identityKey: ref('continuous|jm||15m'),
    async loadMoreBefore() {
      loadCalls += 1
    },
  })

  await warmup.ensureReady()
  const frozenAnchor = warmup.anchorTime.value
  assert.equal(warmup.unavailableReason.value, RANGE_DETECTOR_WARMUP_INSUFFICIENT)

  bars.value = barSeries(521)
  await nextTick()

  assert.equal(warmup.anchorTime.value, frozenAnchor)
  assert.equal(warmup.unavailableReason.value, null)
  assert.equal(loadCalls, 0)
})

test('fails closed when a successful older-page request makes no history progress', async () => {
  const bars = ref(barSeries(300, 220))
  let calls = 0
  const warmup = useRangeDetectorOverlayWarmup({
    bars,
    hasMoreBefore: ref(true),
    enabled: ref(true),
    identityKey: ref('continuous|jm||15m'),
    async loadMoreBefore() {
      calls += 1
    },
  })

  await warmup.ensureReady()

  assert.equal(calls, 1)
  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  assert.equal(warmup.unavailableReason.value, RANGE_DETECTOR_WARMUP_LOAD_FAILED)
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
  bars.value = barSeries(RANGE_DETECTOR_REQUIRED_BARS + 1, 1_000)
  hasMoreBefore.value = false
  pending.forEach((resolve) => resolve())
  await stale
  await Promise.resolve()

  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  assert.equal(warmup.unavailableReason.value, null)
})

test('a manual prepend updates the calculation anchor', async () => {
  const bars = ref(barSeries(RANGE_DETECTOR_REQUIRED_BARS + 1, 220))
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

  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  assert.notEqual(warmup.anchorTime.value, frozen)
})

test('viewport near loaded left edge fetches preceding same-segment history despite enough total bars', async () => {
  const bars = ref(barSeries(700, 600).map(bar => ({ ...bar, physicalContract: 'JM2701', calculationSegmentId: 'segment-a' })))
  const visibleFrom = ref(bars.value[100].time)
  let calls = 0
  const warmup = useRangeDetectorOverlayWarmup({ bars, visibleFrom, hasMoreBefore: ref(true), enabled: ref(true), identityKey: ref('jm'), async loadMoreBefore() { calls++; bars.value = [...barSeries(300, 600 - calls * 300).map(bar => ({ ...bar, physicalContract: 'JM2701', calculationSegmentId: 'segment-a' })), ...bars.value] } })
  await warmup.ensureReady()
  assert.equal(calls, 2)
  assert.equal(warmup.status.value, 'ready')
  assert.equal(warmup.anchorTime.value, bars.value[0].time)
})
test('known physical or calculation boundary reports insufficient without downloading unrelated history', async () => {
  const bars = ref(barSeries(800).map((bar, index) => ({ ...bar, physicalContract: 'JM2701', calculationSegmentId: index < 400 ? 'old-quality' : 'new-quality' })))
  let calls = 0
  const visibleFrom = ref(bars.value[450].time)
  const warmup = useRangeDetectorOverlayWarmup({ bars, visibleFrom, hasMoreBefore: ref(true), enabled: ref(true), identityKey: ref('jm'), async loadMoreBefore() { calls++ } })
  await warmup.ensureReady(); visibleFrom.value = bars.value[460].time; await nextTick(); await warmup.ensureReady()
  assert.equal(calls, 0)
  assert.equal(warmup.status.value, 'insufficient')
})
test('quick viewport changes share one serial run and evaluate the latest visible target', async () => {
  const bars = ref(barSeries(300, 300))
  const visibleFrom = ref(bars.value[10].time)
  let release!: () => void, calls = 0
  const warmup = useRangeDetectorOverlayWarmup({ bars, visibleFrom, hasMoreBefore: ref(true), enabled: ref(true), identityKey: ref('jm'), loadMoreBefore: async () => { calls++; await new Promise<void>(resolve => { release = resolve }); bars.value = barSeries(600) } })
  const first = warmup.ensureReady(); await Promise.resolve()
  visibleFrom.value = bars.value[299].time; await nextTick()
  assert.equal(warmup.ensureReady(), first)
  release(); await first
  assert.equal(calls, 1)
  assert.equal(warmup.status.value, 'ready')
})

test('520 total bars are insufficient because the visible target itself is excluded', async () => {
  const bars = ref(barSeries(520))
  const warmup = useRangeDetectorOverlayWarmup({ bars, hasMoreBefore: ref(false), enabled: ref(true), identityKey: ref('jm'), async loadMoreBefore() {} })
  await warmup.ensureReady()
  assert.equal(warmup.status.value, 'insufficient')
  assert.equal(warmup.anchorTime.value, bars.value[0].time)
  bars.value = barSeries(521); await nextTick(); await warmup.ensureReady()
  assert.equal(warmup.status.value, 'ready')
})

test('invalid OHLC resets the visible-prefix warm-up without downloading unrelated history', async () => {
  for (const patch of [{ close: Number.NaN }, { low: 105 }, { high: 95 }]) {
    const bars = ref(barSeries(800)); bars.value[400] = { ...bars.value[400], ...patch }
    let calls = 0
    const warmup = useRangeDetectorOverlayWarmup({ bars, visibleFrom: ref(bars.value[600].time), hasMoreBefore: ref(true), enabled: ref(true), identityKey: ref('jm'), async loadMoreBefore() { calls++ } })
    await warmup.ensureReady()
    assert.equal(warmup.status.value, 'insufficient')
    assert.equal(calls, 0)
    assert.equal(warmup.anchorTime.value, bars.value[0].time)
  }
})
test('a shared terminal pagination response with no new bars reports earliest-history insufficiency', async () => {
  const bars = ref(barSeries(300)), hasMoreBefore = ref(true)
  const warmup = useRangeDetectorOverlayWarmup({ bars, hasMoreBefore, enabled: ref(true), identityKey: ref('jm'), async loadMoreBefore() { hasMoreBefore.value = false } })
  await warmup.ensureReady()
  assert.equal(warmup.unavailableReason.value, RANGE_DETECTOR_WARMUP_INSUFFICIENT)
  assert.equal(warmup.anchorTime.value, bars.value[0].time)
})

test('scope disposal stops a pending warm-up from reading more pages or publishing', async () => {
  const scope = effectScope()
  const bars = ref(barSeries(100, 600))
  let release!: () => void, calls = 0
  const warmup = scope.run(() => useRangeDetectorOverlayWarmup({ bars, hasMoreBefore: ref(true), enabled: ref(true), identityKey: ref('jm'), async loadMoreBefore() { calls++; await new Promise<void>(resolve => { release = resolve }); bars.value = barSeries(200, 500) } }))!
  const pending = warmup.ensureReady(); await Promise.resolve()
  scope.stop(); release(); await pending; await nextTick()
  assert.equal(calls, 1)
  assert.equal(warmup.anchorTime.value, null)
  assert.equal(warmup.loading.value, false)
  assert.equal(warmup.unavailableReason.value, null)
})
