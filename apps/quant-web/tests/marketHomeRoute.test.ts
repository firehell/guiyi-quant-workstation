import assert from 'node:assert/strict'
import test from 'node:test'

import { marketHomeEventChartQuery, marketHomeProductChartQuery } from '../src/utils/marketHomeRoutes.ts'

test('uses only actual-dominant chart route intents for products and immutable HTDY Events', () => {
  assert.deepEqual(marketHomeProductChartQuery('ag'), { symbol: 'ag', series_kind: 'actual_dominant', frequency: '1d' })
  assert.deepEqual(marketHomeEventChartQuery({ symbol: 'jm', frequency: '15m' }), { symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', overlay: 'htdy' })
})
