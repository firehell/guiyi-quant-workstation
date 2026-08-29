import { readFileSync } from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'
import type { LocationQuery } from 'vue-router'
import {
  resolveSubingConfirmChartEntry,
  resolveSubingDailyWatchChartEntry,
  seriesRefreshQuery,
} from '../src/utils/marketChartEntry.ts'

const dailyWatchQuery = {
  entry: 'subing-daily-watch',
  overlay: 'subing',
  series_kind: 'actual_dominant',
  frequency: '15m',
  symbol: 'JM',
} satisfies LocationQuery

const strategyQuery = {
  entry: 'subing-strategy-action',
  overlay: 'subing',
  series_kind: 'actual_dominant',
  frequency: '15m',
  symbol: 'jm',
  action_id: 'subing-action:jm:open',
} satisfies LocationQuery

test('exact SuBing Daily Watch query resolves a normalized one-shot chart entry', () => {
  assert.deepEqual(resolveSubingDailyWatchChartEntry(dailyWatchQuery), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  })
  assert.deepEqual(resolveSubingDailyWatchChartEntry({ ...dailyWatchQuery, contract: '' }), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  })
  assert.deepEqual(resolveSubingDailyWatchChartEntry({ ...dailyWatchQuery, contract: null }), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  })
})

test('partial or mismatched Daily Watch queries apply no chart entry override', () => {
  const invalidQueries: LocationQuery[] = [
    { ...dailyWatchQuery, entry: undefined },
    { ...dailyWatchQuery, overlay: 'htdy' },
    { ...dailyWatchQuery, series_kind: 'continuous' },
    { ...dailyWatchQuery, frequency: '5m' },
    { ...dailyWatchQuery, contract: 'JM2701' },
    { ...dailyWatchQuery, action_id: 'subing-action:jm:open' },
  ]

  invalidQueries.forEach((query) => {
    assert.equal(resolveSubingDailyWatchChartEntry(query), null)
  })
})

test('array-valued Daily Watch query fields are rejected instead of partially applied', () => {
  const invalidQueries: LocationQuery[] = [
    { ...dailyWatchQuery, entry: ['subing-daily-watch'] },
    { ...dailyWatchQuery, overlay: ['subing'] },
    { ...dailyWatchQuery, series_kind: ['actual_dominant'] },
    { ...dailyWatchQuery, frequency: ['15m'] },
    { ...dailyWatchQuery, symbol: ['jm'] },
    { ...dailyWatchQuery, contract: [''] },
  ]

  invalidQueries.forEach((query) => {
    assert.equal(resolveSubingDailyWatchChartEntry(query), null)
  })
})

test('malformed product symbols are rejected', () => {
  const malformedSymbols = ['', '   ', 'jm2701', 'jm-rb', '焦煤']

  malformedSymbols.forEach((symbol) => {
    assert.equal(resolveSubingDailyWatchChartEntry({ ...dailyWatchQuery, symbol }), null)
  })
})

test('strategy action query resolves overlay, 15m dominant identity, and action id', () => {
  assert.deepEqual(resolveSubingConfirmChartEntry(strategyQuery), {
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
    entry: 'subing-strategy-action',
    actionId: 'subing-action:jm:open',
  })
})

test('strategy action query without a valid action_id does not override the chart', () => {
  assert.equal(resolveSubingConfirmChartEntry({ ...strategyQuery, action_id: undefined }), null)
  assert.equal(resolveSubingConfirmChartEntry({ ...strategyQuery, action_id: '' }), null)
  assert.equal(resolveSubingConfirmChartEntry({ ...strategyQuery, action_id: 'not-an-action' }), null)
  assert.equal(resolveSubingConfirmChartEntry({ ...strategyQuery, action_id: ['subing-action:jm:open'] }), null)
})

test('series refresh keeps confirm query only while still on SuBing 15m dominant', () => {
  const confirm = resolveSubingConfirmChartEntry(strategyQuery)
  assert.ok(confirm)
  assert.deepEqual(seriesRefreshQuery({
    symbol: 'jm',
    contract: '',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
    confirm,
  }), {
    symbol: 'jm',
    contract: undefined,
    series_kind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
    entry: 'subing-strategy-action',
    action_id: 'subing-action:jm:open',
  })
  assert.deepEqual(seriesRefreshQuery({
    symbol: 'jm',
    contract: '',
    seriesKind: 'actual_dominant',
    frequency: '5m',
    overlay: 'subing',
    confirm,
  }), {
    symbol: 'jm',
    contract: undefined,
    series_kind: 'actual_dominant',
    frequency: '5m',
  })
  assert.deepEqual(seriesRefreshQuery({
    symbol: 'jm',
    contract: '',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'htdy',
    confirm,
  }), {
    symbol: 'jm',
    contract: undefined,
    series_kind: 'actual_dominant',
    frequency: '15m',
  })
})

test('home and chart wire the shared confirm query instead of overlay-only navigation', () => {
  const home = readFileSync(new URL('../src/pages/market/index.vue', import.meta.url), 'utf8')
  const chart = readFileSync(new URL('../src/pages/market/chart.vue', import.meta.url), 'utf8')
  assert.match(home, /entry: 'subing-strategy-action'/)
  assert.match(home, /action_id: item.action_id/)
  assert.match(chart, /seriesRefreshQuery\(/)
  assert.match(chart, /data-focused-action-id/)
})
