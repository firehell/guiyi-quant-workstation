import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  isCurrentGeneration,
  mergeInitialPage,
  prependHistoricalPage,
} from '../src/composables/useMarketSeries.ts'
import type { MarketBarsPageResponse } from '../src/types/market.ts'

function page(
  bars: Array<{ bar_end: string; close: number }>,
  pageMeta: { has_more_before: boolean; next_before: string | null },
): MarketBarsPageResponse {
  return {
    request: {
      series_kind: 'continuous',
      symbol: 'jm',
      contract: null,
      frequency: '15m',
      before: null,
      limit: 1200,
    },
    bars: bars.map((bar) => ({
      bar_end: bar.bar_end,
      trading_day: bar.bar_end.slice(0, 10),
      open: bar.close - 1,
      high: bar.close + 1,
      low: bar.close - 2,
      close: bar.close,
      volume: 10,
      turnover: null,
      open_interest: null,
    })),
    coverage: null,
    page: pageMeta,
    resolved_contract_segments: [],
  }
}

describe('market historical series', () => {
  it('sorts and deduplicates an initial page by formal bar_end', () => {
    const result = mergeInitialPage(page([
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 103 },
    ], { has_more_before: true, next_before: '2026-08-07T09:15:00Z' }))

    assert.deepEqual(result.bars.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:15:00Z', 101],
      ['2026-08-07T09:30:00Z', 103],
    ])
  })

  it('prepends an older page without duplicating an overlapping bar_end', () => {
    const current = mergeInitialPage(page([
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
      { bar_end: '2026-08-07T09:45:00Z', close: 103 },
    ], { has_more_before: true, next_before: '2026-08-07T09:30:00Z' }))

    const result = prependHistoricalPage(current.bars, page([
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
    ], { has_more_before: false, next_before: null }))

    assert.deepEqual(result.bars.map((bar) => bar.time), [
      '2026-08-07T09:15:00Z',
      '2026-08-07T09:30:00Z',
      '2026-08-07T09:45:00Z',
    ])
  })

  it('rejects a page response from an older identity generation', () => {
    assert.equal(isCurrentGeneration(4, 5), false)
    assert.equal(isCurrentGeneration(5, 5), true)
  })

  it('keeps the API next_before cursor for the earliest formal bar', () => {
    const result = mergeInitialPage(page([
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
    ], { has_more_before: true, next_before: '2026-08-07T09:15:00Z' }))

    assert.equal(result.nextBefore, '2026-08-07T09:15:00Z')
    assert.equal(result.hasMoreBefore, true)
  })
})
