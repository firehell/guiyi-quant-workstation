import assert from 'node:assert/strict'
import test from 'node:test'

import { filterAndSortMarketHomeRows } from '../src/utils/marketHomeWorkspace.ts'
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
})
