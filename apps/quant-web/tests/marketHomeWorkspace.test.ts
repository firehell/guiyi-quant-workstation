import assert from 'node:assert/strict'
import test from 'node:test'

import { filterAndSortMarketHomeRows, nextMarketHomeSort } from '../src/utils/marketHomeWorkspace.ts'
import type { MarketHomeRow } from '../src/utils/marketHomeViewModel.ts'

const rows = [
  { symbol: 'ag', product_name: '白银', sector: 'precious', price_change_1d: 0.02, volume_ratio20: 2, oi_change_1d: null, dailyState: 'up', weeklyState: 'up', alignment: 'aligned-up', event: null },
  { symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: -0.01, volume_ratio20: 1, oi_change_1d: 3, dailyState: 'down', weeklyState: 'down', alignment: 'aligned-down', event: { id: 1 } },
] as unknown as MarketHomeRow[]

test('filters and sorts Market Home rows locally without changing resource inputs', () => {
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'up', sort: 'default' }).map((row) => row.symbol), ['ag'])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '焦煤', sector: '', filter: 'all', sort: 'default' }).map((row) => row.symbol), ['jm'])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'all', sort: 'event' }).map((row) => row.symbol), ['jm', 'ag'])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'all', sort: 'change' }).map((row) => row.symbol), ['ag', 'jm'])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'all', sort: 'default', daily: 'down', event: 'with-event' }).map((row) => row.symbol), ['jm'])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'flat', sort: 'default' }).map((row) => row.symbol), [])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'daily-up', sort: 'default' }).map((row) => row.symbol), ['ag'])
  assert.deepEqual(filterAndSortMarketHomeRows(rows, { query: '', sector: '', filter: 'with-event', sort: 'default' }).map((row) => row.symbol), ['jm'])
})

test('orders Event rows by the latest immutable detection time before symbol', () => {
  const eventRows = [
    { ...rows[0]!, symbol: 'ag', event: { id: 1, detected_at: '2026-09-02T01:00:00Z', bar_end: '2026-09-02T00:59:00Z' } },
    { ...rows[1]!, symbol: 'jm', event: { id: 2, detected_at: '2026-09-02T02:00:00Z', bar_end: '2026-09-02T01:59:00Z' } },
    { ...rows[0]!, symbol: 'au', event: null },
  ] as unknown as MarketHomeRow[]

  assert.deepEqual(filterAndSortMarketHomeRows(eventRows, { query: '', sector: '', filter: 'all', sort: 'event' }).map((row) => row.symbol), ['jm', 'ag', 'au'])
})

test('cycles a sortable column through descending, ascending, and default order', () => {
  assert.deepEqual(nextMarketHomeSort({ sort: 'default', sortDirection: 'desc' }, 'change'), { sort: 'change', sortDirection: 'desc' })
  assert.deepEqual(nextMarketHomeSort({ sort: 'change', sortDirection: 'desc' }, 'change'), { sort: 'change', sortDirection: 'asc' })
  assert.deepEqual(nextMarketHomeSort({ sort: 'change', sortDirection: 'asc' }, 'change'), { sort: 'default', sortDirection: 'desc' })
  assert.deepEqual(nextMarketHomeSort({ sort: 'change', sortDirection: 'asc' }, 'close'), { sort: 'close', sortDirection: 'desc' })
})

test('sorts exact close values and uses symbol ascending for equal values', () => {
  const closeRows = [
    { ...rows[0]!, symbol: 'zn', close: 100.0000002 },
    { ...rows[0]!, symbol: 'ag', close: 100.0000001 },
    { ...rows[0]!, symbol: 'au', close: 100.0000002 },
  ] as MarketHomeRow[]

  assert.deepEqual(filterAndSortMarketHomeRows(closeRows, {
    query: '', sector: '', filter: 'all', sort: 'close', sortDirection: 'asc',
  }).map((row) => row.symbol), ['ag', 'au', 'zn'])
  assert.deepEqual(filterAndSortMarketHomeRows(closeRows, {
    query: '', sector: '', filter: 'all', sort: 'close', sortDirection: 'desc',
  }).map((row) => row.symbol), ['au', 'zn', 'ag'])
})

test('keeps null and non-finite numeric values last in both directions', () => {
  const numericRows = [
    { ...rows[0]!, symbol: 'null', close: null },
    { ...rows[0]!, symbol: 'nan', close: Number.NaN },
    { ...rows[0]!, symbol: 'infinity', close: Number.POSITIVE_INFINITY },
    { ...rows[0]!, symbol: 'negative', close: -1 },
    { ...rows[0]!, symbol: 'positive', close: 2 },
  ] as MarketHomeRow[]

  assert.deepEqual(filterAndSortMarketHomeRows(numericRows, {
    query: '', sector: '', filter: 'all', sort: 'close', sortDirection: 'asc',
  }).map((row) => row.symbol), ['negative', 'positive', 'infinity', 'nan', 'null'])
  assert.deepEqual(filterAndSortMarketHomeRows(numericRows, {
    query: '', sector: '', filter: 'all', sort: 'close', sortDirection: 'desc',
  }).map((row) => row.symbol), ['positive', 'negative', 'infinity', 'nan', 'null'])
})

test('sorts only filtered rows without changing the source array', () => {
  const source = Object.freeze([
    { ...rows[0]!, symbol: 'ag', sector: 'precious', price_change_1d: null },
    { ...rows[1]!, symbol: 'jm', sector: 'black', price_change_1d: -0.01 },
    { ...rows[0]!, symbol: 'au', sector: 'precious', price_change_1d: -0.01 },
  ] as MarketHomeRow[])
  const originalSymbols = source.map((row) => row.symbol)

  assert.deepEqual(filterAndSortMarketHomeRows(source, {
    query: '', sector: 'precious', filter: 'all', sort: 'change', sortDirection: 'asc',
  }).map((row) => row.symbol), ['au', 'ag'])
  assert.deepEqual(source.map((row) => row.symbol), originalSymbols)
})
