import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import { calculateRangeDetectorLux, type RangeDetectorLuxResult } from '../src/utils/rangeDetectorLux.ts'
import {
  buildKlineDerivedData,
  formatKlineHoverValue,
  resolveKlineHoverContext,
} from '../src/utils/klineViewModel.ts'

const bars: BarData[] = Array.from({ length: 100 }, (_, index) => {
  const close = 100 + index
  return {
    time: new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString(),
    trading_day: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10),
    open: close - 1,
    high: close + 2,
    low: close - 3,
    close,
    volume: 1_000 + index,
    openInterest: 2_000 + index,
  }
})

test('only enabled EMA is derived while MACD is always available', () => {
  const result = buildKlineDerivedData(bars, ['ema_21'])

  assert.equal(result.ema.ema_10, undefined)
  assert.equal(result.ema.ema_60, undefined)
  assert.equal(result.ema.ema_21?.length, 80)
  assert.ok(result.macd.dif.length > 0)
  assert.equal(result.macd.dif.length, result.macd.dea.length)
  assert.equal(result.macd.dea.length, result.macd.histogram.length)
})

test('HTDY is only derived when its observation overlay is explicitly visible', () => {
  const htdyBars = makeDeterministicHtdyBars(2)
  const hidden = buildKlineDerivedData(htdyBars, ['ema_21'])
  const visible = buildKlineDerivedData(htdyBars, ['ema_21', 'htdy'])

  assert.equal(hidden.htdy, null)
  assert.ok(visible.htdy)
  assert.ok(visible.htdy?.zk1.length)
  assert.ok(visible.htdy?.zd1.length)
  assert.ok(visible.htdy?.zd2.length)
  assert.ok(visible.htdy?.markers.length)
  assert.ok(visible.htdy?.markers.every((marker) => ['买观察', '卖观察'].includes(marker.label)))
  assert.ok(visible.htdy?.markers.every((marker) => marker.tone === 'up' || marker.tone === 'down'))
})

test('Range Detector remains absent until its calculation anchor is frozen', () => {
  const result = buildKlineDerivedData(bars, ['range_detector'], {
    rangeDetector: { enabled: true, sourceIdentity: 'continuous|jm||15m', anchorTime: null },
  })

  assert.equal(result.rangeDetector, null)
})

test('Range Detector calculates only from its anchored bars and ignores later prepends', () => {
  const anchored = flatBars(530, 200)
  const anchorTime = anchored[0]!.time
  const withPrependedHistory = [...flatBars(40, 0), ...anchored]
  const options = {
    rangeDetector: { enabled: true, sourceIdentity: 'continuous|jm||15m', anchorTime },
  }

  const first = buildKlineDerivedData(anchored, ['range_detector'], options)
  const prepended = buildKlineDerivedData(withPrependedHistory, ['range_detector'], options)
  const appended = buildKlineDerivedData([...anchored, ...flatBars(1, 730)], ['range_detector'], options)

  assert.ok(first.rangeDetector)
  assert.deepEqual(prepended.rangeDetector, first.rangeDetector)
  assert.equal(appended.rangeDetector?.points.length, first.rangeDetector?.points.length + 1)
  assert.ok(first.rangeDetector?.ranges.length)
})

test('crosshair context keeps OHLCV OI EMA and MACD on the hovered bar timestamp', () => {
  const result = buildKlineDerivedData(bars, ['ema_21'])
  const target = bars[79]
  const hover = resolveKlineHoverContext(bars, result, ['ema_21'], target.time)

  assert.ok(hover)
  assert.equal(hover.time, target.time)
  assert.equal(hover.bar.open, 178)
  assert.equal(hover.bar.high, 181)
  assert.equal(hover.bar.low, 176)
  assert.equal(hover.bar.close, 179)
  assert.equal(hover.bar.volume, 1_079)
  assert.equal(hover.bar.openInterest, 2_079)
  assert.equal(hover.mainIndicators?.[0]?.id, 'ema_21')
  assert.ok(hover.mainIndicators?.[0]?.value)
  assert.notEqual(hover.macd?.dif, null)
  assert.notEqual(hover.macd?.dea, null)
  assert.notEqual(hover.macd?.histogram, null)
})

test('crosshair exposes the exact marker tooltip at its evidence bar', () => {
  const result = buildKlineDerivedData(bars, [])
  const target = bars[79]
  const marker = {
    id: 'research:marker-1',
    time: target.time,
    label: '跟随多',
    tooltip: 'Research marker detail',
    tone: 'up' as const,
    position: 'belowBar' as const,
    shape: 'arrowUp' as const,
  }

  const hover = resolveKlineHoverContext(bars, result, [], target.time, [marker])

  assert.deepEqual(hover?.marker, marker)
})

test('crosshair reports a causal Range Detector fact without treating visual start as confirmation', () => {
  const result = buildKlineDerivedData(bars, [])
  const visualStartAt = bars[60]!.time
  const confirmedAt = bars[70]!.time
  const rangeDetector: RangeDetectorLuxResult = {
    points: [{
      time: confirmedAt,
      ready: true,
      valid: true,
      reason: null,
      snapshot: {
        formulaVersion: 'range_detector_lux_v1',
        policyId: 'range_detector_lux_v1',
        rangeId: 'range-1',
        revision: 2,
        visualStartAt,
        confirmedAt,
        detectionRightAt: confirmedAt,
        levelsActiveFrom: confirmedAt,
        initialUpper: 110,
        initialLower: 90,
        currentUpper: 111,
        currentLower: 89,
        currentMid: 100,
        state: 'intact',
        brokenAt: null,
        mergedCount: 1,
        candidateValid: true,
        sourceBarEnd: confirmedAt,
        sourceTradingDay: null,
        sourceIdentity: 'continuous|jm||15m',
      },
      transition: null,
    }],
    ranges: [],
  }
  const hover = resolveKlineHoverContext(
    bars,
    { ...result, rangeDetector },
    ['range_detector'],
    bars[79]!.time,
  )

  assert.deepEqual(hover?.rangeDetector, {
    rangeId: 'range-1',
    revision: 2,
    state: 'intact',
    upper: 111,
    lower: 89,
    mid: 100,
    confirmedAt,
    visualStartAt,
  })
  assert.notEqual(hover?.rangeDetector?.confirmedAt, hover?.rangeDetector?.visualStartAt)
})

test('missing hover values render as unavailable instead of a fabricated zero', () => {
  assert.equal(formatKlineHoverValue(undefined), '—')
  assert.equal(formatKlineHoverValue(null), '—')
  assert.equal(formatKlineHoverValue(0), '0')
})

function makeDeterministicHtdyBars(seed: number, length = 100): BarData[] {
  let state = seed >>> 0
  const random = () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0
    return state / 2 ** 32
  }
  const normal = () => Array.from({ length: 6 }, random).reduce((sum, value) => sum + value, -3)
  const close: number[] = []
  let value = 100
  for (let index = 0; index < length; index += 1) {
    value += normal() * 2
    close.push(value)
  }
  const open = close.map((item) => item + normal())
  const high = close.map((item, index) => Math.max(open[index], item) + 0.1 + random() * 1.9)
  const low = close.map((item, index) => Math.min(open[index], item) - 0.1 - random() * 1.9)

  return close.map((item, index) => ({
    time: `htdy-${index}`,
    open: open[index],
    high: high[index],
    low: low[index],
    close: item,
    volume: 1000,
  }))
}

function flatBars(count: number, start: number): BarData[] {
  return Array.from({ length: count }, (_, index) => ({
    time: new Date(Date.UTC(2026, 2, 1, 0, start + index)).toISOString(),
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 1,
  }))
}


function deriveRanges(input: BarData[]) {
  return buildKlineDerivedData(input, ['range_detector'], {
    rangeDetector: { enabled: true, sourceIdentity: 'actual_dominant|jm|15m', anchorTime: input[0]?.time ?? null },
  }).rangeDetector!
}

test('single owned segment preserves the original Range Detector kernel values exactly', () => {
  const input = flatBars(700, 0).map(bar => ({ ...bar, physicalContract: 'JM2701', calculationSegmentId: 'quality-one' }))
  const result = deriveRanges(input)
  const identity = result.points.find(point => point.snapshot)?.snapshot?.sourceIdentity
  assert.equal(identity, 'actual_dominant|jm|15m')
  assert.deepEqual(result, calculateRangeDetectorLux(input, { sourceIdentity: 'actual_dominant|jm|15m' }))
})

test('physical and quality boundaries independently require 500 real warm-up Bars', () => {
  for (const boundary of ['physicalContract', 'calculationSegmentId'] as const) {
    const input = flatBars(800, 0).map((bar, index) => ({ ...bar,
      physicalContract: boundary === 'physicalContract' && index >= 400 ? 'JM2705' : 'JM2701',
      calculationSegmentId: boundary === 'calculationSegmentId' && index >= 400 ? 'quality-two' : 'quality-one',
    }))
    const result = deriveRanges(input)
    assert.equal(result.points.length, 800)
    assert.equal(result.ranges.length, 0)
    assert.ok(result.points.every(point => !point.ready && point.snapshot === null))
  }
})

test('owned segment ranges are distinct and stop at the true owner boundary', () => {
  const input = flatBars(1200, 0).map((bar, index) => ({ ...bar,
    physicalContract: index < 600 ? 'JM2701' : 'JM2705', calculationSegmentId: 'quality-one',
  }))
  const result = deriveRanges(input)
  assert.equal(result.ranges.length, 2)
  assert.notEqual(result.ranges[0].rangeId, result.ranges[1].rangeId)
  assert.equal(result.ranges[0].levelsActiveUntil, input[599].time)
  assert.equal(result.ranges[1].levelsActiveUntil, null)
  assert.ok(result.points.slice(600, 1099).every(point => !point.ready))
  const secondIdentity = result.points[1099].snapshot!.sourceIdentity
  const second = calculateRangeDetectorLux(input.slice(600), { sourceIdentity: secondIdentity })
  assert.deepEqual(result.points.slice(600), second.points)
  assert.deepEqual(result.ranges.slice(1), second.ranges)
})

test('invalid Bar stays a kernel reset and does not borrow previous warm-up', () => {
  const input = flatBars(1100, 0).map(bar => ({ ...bar, physicalContract: 'JM2701', calculationSegmentId: 'quality-one' }))
  input[550] = { ...input[550], close: Number.NaN }
  const result = deriveRanges(input)
  assert.equal(result.points[550].transition?.kind, 'invalid_reset')
  assert.ok(result.points.slice(551, 1050).every(point => !point.ready && point.snapshot === null))
  const identity = result.points[499].snapshot!.sourceIdentity
  assert.deepEqual(result, calculateRangeDetectorLux(input, { sourceIdentity: identity }))
})

test('rebasing the external anchor includes earlier loaded history without fabricating Bars', () => {
  const input = flatBars(1100, 0).map(bar => ({ ...bar, physicalContract: 'JM2701', calculationSegmentId: 'quality-one' }))
  const recent = deriveRanges(input.slice(600))
  const full = deriveRanges(input)
  assert.equal(recent.points.length, 500)
  assert.equal(full.points.length, input.length)
  assert.equal(full.points[0].time, input[0].time)
})
