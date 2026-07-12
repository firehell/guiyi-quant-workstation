import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  barsTimeExtent,
  computeViewportLoadRequest,
  continuousContractFor,
  defaultContractViewForPeriod,
  defaultDateRangeMs,
  fullCoverageDateRangeMs,
  isLivePeriodSupported,
  preferredOpenPeriod,
  resolveContractForView,
  resolveInitialBarsQuery,
  trimBarsToMaxCount,
} from '../src/utils/marketChartWindow.ts'
import { mergeBarsByPeriod as mergeBarsByTime } from '../src/utils/barTime.ts'

describe('marketChartWindow', () => {
  it('resolves contract by view mode', () => {
    assert.equal(resolveContractForView('jm', 'JM2609', 'actual'), 'JM2609')
    assert.equal(resolveContractForView('jm', 'JM2609', 'continuous'), 'jm.MAIN')
    assert.equal(continuousContractFor('JM'), 'jm.MAIN')
  })

  it('defaults contract view by period', () => {
    assert.equal(defaultContractViewForPeriod('1d'), 'continuous')
    assert.equal(defaultContractViewForPeriod('1w'), 'continuous')
    assert.equal(defaultContractViewForPeriod('15m'), 'actual')
  })

  it('builds period-aware default date windows', () => {
    const end = Date.parse('2026-07-09T00:00:00')
    const start = Date.parse('2020-01-01T00:00:00')
    const day = 24 * 60 * 60 * 1000
    const [oneMinuteStart] = defaultDateRangeMs('1m', start, end)
    const [dailyStart] = defaultDateRangeMs('1d', start, end)
    assert.ok(end - oneMinuteStart <= 8 * day)
    assert.ok(end - dailyStart >= 365 * 3 * day - day)
    assert.ok(dailyStart > start)
  })

  it('prefers open period from coverage', () => {
    assert.equal(
      preferredOpenPeriod({
        '1d': { available: true },
        '1w': { available: true },
      }),
      '1d',
    )
    assert.equal(
      preferredOpenPeriod({
        '1m': { available: true },
      }),
      '1m',
    )
  })

  it('knows live supported periods', () => {
    assert.equal(isLivePeriodSupported('15m'), true)
    assert.equal(isLivePeriodSupported('1d'), false)
    assert.equal(isLivePeriodSupported('1w'), false)
  })

  it('returns full coverage date range', () => {
    const start = Date.parse('2020-01-01T00:00:00')
    const end = Date.parse('2026-07-09T00:00:00')
    assert.deepEqual(fullCoverageDateRangeMs(start, end), [start, end])
  })

  it('resolves initial bars query from coverage row count', () => {
    const small = resolveInitialBarsQuery({
      start_time: '2026-01-01T00:00:00',
      end_time: '2026-01-31T00:00:00',
      row_count: 500,
    })
    assert.equal(small?.tail, true)
    assert.equal(small?.limit, 10000)

    const large = resolveInitialBarsQuery({
      start_time: '2023-01-01T00:00:00',
      end_time: '2026-01-01T00:00:00',
      row_count: 25000,
    })
    assert.equal(large?.tail, true)
    assert.equal(large?.limit, 10000)
  })

  it('merges bars by time and computes extent', () => {
    const merged = mergeBarsByTime(
      [{ time: '2026-01-01T09:00:00', close: 1 }],
      [{ time: '2026-01-01T09:15:00', close: 2 }, { time: '2026-01-01T09:00:00', close: 3 }],
      '15m',
    )
    assert.equal(merged.length, 2)
    assert.equal(merged[0].close, 3)
    const extent = barsTimeExtent(merged as Array<{ time: string }>)
    assert.ok(extent)
    assert.ok(extent!.startMs <= extent!.endMs)
  })

  it('trims bars around visible center', () => {
    const bars = Array.from({ length: 20 }, (_, index) => ({
      time: `2026-01-01T${String(9 + Math.floor(index / 4)).padStart(2, '0')}:${String((index % 4) * 15).padStart(2, '0')}:00`,
    }))
    const center = Date.parse('2026-01-01T12:30:00')
    const trimmed = trimBarsToMaxCount(bars, 5, center, '15m')
    assert.equal(trimmed.length, 5)
  })

  it('computes viewport load request when visible range exceeds loaded data', () => {
    const day = 24 * 60 * 60 * 1000
    const request = computeViewportLoadRequest({
      visibleFromMs: Date.parse('2026-03-01T00:00:00'),
      visibleToMs: Date.parse('2026-03-31T00:00:00'),
      loadedStartMs: Date.parse('2026-04-01T00:00:00'),
      loadedEndMs: Date.parse('2026-06-01T00:00:00'),
      coverageStartMs: Date.parse('2026-01-01T00:00:00'),
      coverageEndMs: Date.parse('2026-12-31T00:00:00'),
    })
    assert.ok(request)
    assert.ok(request!.startMs < Date.parse('2026-04-01T00:00:00'))
    assert.ok(request!.endMs >= Date.parse('2026-03-31T00:00:00') - 7 * day)
  })
})
