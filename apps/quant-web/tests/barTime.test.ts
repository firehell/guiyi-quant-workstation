import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  canonicalBarTimeKey,
  chartLookupKeyForBar,
  chartLookupKeyForTimeString,
  coerceTradingDay,
  dedupeBarsByPeriod,
  mergeBarsByPeriod,
  BarMergeConflictError,
  normalizePeriod,
  toChartTimeForPeriod,
} from '../src/utils/barTime.ts'

describe('barTime', () => {
  it('merges daily bars with different time strings on the same trading_day', () => {
    const merged = mergeBarsByPeriod(
      [
        { time: '2024-07-10', trading_day: '2024-07-10', close: 1 },
        { time: '2024-07-11T15:00:00', trading_day: '2024-07-11', close: 2 },
      ],
      [
        { time: '2024-07-10T00:00:00', trading_day: '2024-07-10', close: 1 },
        { time: '2024-07-10T15:00:00', trading_day: '2024-07-10', close: 1 },
      ],
      '1d',
    )
    assert.equal(merged.length, 2)
    assert.equal(merged[0].close, 1)
    assert.equal(merged[1].close, 2)
  })

  it('refuses to hide different OHLCV values for the same canonical key', () => {
    assert.throws(
      () => mergeBarsByPeriod(
        [{ time: '2024-07-10T09:15:00', close: 100, volume: 10 }],
        [{ time: '2024-07-10T09:15:00', close: 101, volume: 10 }],
        '15m',
      ),
      (error) => error instanceof BarMergeConflictError && error.conflicts[0]?.fields.includes('close'),
    )
  })

  it('maps daily bars to the same BusinessDay chart time', () => {
    const first = toChartTimeForPeriod({ time: '2024-07-10', trading_day: '2024-07-10' }, '1d')
    const second = toChartTimeForPeriod({ time: '2024-07-10T15:00:00', trading_day: '2024-07-10' }, '1d')
    assert.deepEqual(first, { year: 2024, month: 7, day: 10 })
    assert.deepEqual(second, first)
  })

  it('keeps intraday bars distinct by normalized datetime', () => {
    const bars = dedupeBarsByPeriod(
      [
        { time: '2024-07-10T09:15:00' },
        { time: '2024-07-10T09:15:00' },
        { time: '2024-07-10T09:30:00' },
      ],
      '15m',
    )
    assert.equal(bars.length, 2)
    assert.equal(canonicalBarTimeKey({ time: '2024-07-10T09:15:00' }, '15m'), '2024-07-10T09:15:00')
  })

  it('normalizes period case for daily dedupe', () => {
    const bars = dedupeBarsByPeriod(
      [
        { time: '2024-07-10', trading_day: '2024-07-10', close: 1 },
        { time: '2024-07-10T15:00:00', trading_day: '2024-07-10', close: 1 },
      ],
      '1D',
    )
    assert.equal(bars.length, 1)
    assert.equal(bars[0]?.close, 1)
    assert.equal(normalizePeriod('1D'), '1d')
  })

  it('uses chart time keys for intraday hover lookup', () => {
    const bar = { time: '2026-07-10T09:15:00' }
    const chartTime = toChartTimeForPeriod(bar, '15m')

    assert.equal(chartLookupKeyForBar(bar, '15m'), String(chartTime))
    assert.equal(chartLookupKeyForTimeString(bar.time, '15m'), String(chartTime))
  })

  it('uses canonical trading day chart keys for daily hover lookup', () => {
    const bar = { time: '2026-07-10T15:00:00', trading_day: '2026-07-11' }

    assert.equal(chartLookupKeyForBar(bar, '1d'), '2026-07-11')
    assert.equal(chartLookupKeyForTimeString('2026-07-11T00:00:00', '1d'), '2026-07-11')
  })

  it('coerces trading_day values from mixed formats', () => {
    assert.equal(coerceTradingDay('2024-07-10T00:00:00'), '2024-07-10')
    assert.equal(coerceTradingDay('2024-07-10'), '2024-07-10')
    const merged = dedupeBarsByPeriod(
      [
        { time: '2024-07-10T15:00:00', trading_day: '2024-07-10T00:00:00', close: 1 },
        { time: '2024-07-10', trading_day: '2024-07-10', close: 1 },
      ],
      '1d',
    )
    assert.equal(merged.length, 1)
    assert.equal(merged[0]?.close, 1)
  })
})
