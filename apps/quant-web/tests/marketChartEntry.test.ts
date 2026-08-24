import test from 'node:test'
import assert from 'node:assert/strict'
import type { LocationQuery } from 'vue-router'
import { resolveSubingDailyWatchChartEntry } from '../src/utils/marketChartEntry.ts'

const exactEntry = {
  entry: 'subing-daily-watch',
  overlay: 'subing',
  series_kind: 'actual_dominant',
  frequency: '15m',
  symbol: 'JM',
} satisfies LocationQuery

test('exact SuBing Daily Watch query resolves a normalized one-shot chart entry', () => {
  assert.deepEqual(resolveSubingDailyWatchChartEntry(exactEntry), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  })
  assert.deepEqual(resolveSubingDailyWatchChartEntry({ ...exactEntry, contract: '' }), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  })
  assert.deepEqual(resolveSubingDailyWatchChartEntry({ ...exactEntry, contract: null }), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  })
})

test('partial or mismatched Daily Watch queries apply no chart entry override', () => {
  const invalidQueries: LocationQuery[] = [
    { ...exactEntry, entry: undefined },
    { ...exactEntry, overlay: 'htdy' },
    { ...exactEntry, series_kind: 'continuous' },
    { ...exactEntry, frequency: '5m' },
    { ...exactEntry, contract: 'JM2701' },
  ]

  invalidQueries.forEach((query) => {
    assert.equal(resolveSubingDailyWatchChartEntry(query), null)
  })
})

test('array-valued Daily Watch query fields are rejected instead of partially applied', () => {
  const invalidQueries: LocationQuery[] = [
    { ...exactEntry, entry: ['subing-daily-watch'] },
    { ...exactEntry, overlay: ['subing'] },
    { ...exactEntry, series_kind: ['actual_dominant'] },
    { ...exactEntry, frequency: ['15m'] },
    { ...exactEntry, symbol: ['jm'] },
    { ...exactEntry, contract: [''] },
  ]

  invalidQueries.forEach((query) => {
    assert.equal(resolveSubingDailyWatchChartEntry(query), null)
  })
})

test('malformed product symbols are rejected', () => {
  const malformedSymbols = ['', '   ', 'jm2701', 'jm-rb', '焦煤']

  malformedSymbols.forEach((symbol) => {
    assert.equal(resolveSubingDailyWatchChartEntry({ ...exactEntry, symbol }), null)
  })
})
