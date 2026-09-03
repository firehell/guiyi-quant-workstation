import assert from 'node:assert/strict'
import test from 'node:test'

import {
  marketHomeEventChartQuery,
  marketHomeProductChartQuery,
  marketHomeUnifiedEventChartQuery,
  marketHomeUnifiedProductChartQuery,
} from '../src/utils/marketHomeRoutes.ts'

test('uses only actual-dominant chart route intents for products and immutable HTDY Events', () => {
  assert.deepEqual(marketHomeProductChartQuery('ag'), { symbol: 'ag', series_kind: 'actual_dominant', frequency: '1d' })
  assert.deepEqual(marketHomeEventChartQuery({
    symbol: 'jm', frequency: '15m', rule_code: 'htdy_original_15m',
    bar_end: '2026-09-02T02:45:00Z', id: 1, contract: 'JM2601',
    trading_day: '2026-09-02', result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
  }), { symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', overlay: 'htdy' })
  assert.deepEqual(marketHomeEventChartQuery({
    symbol: 'jm',
    frequency: '15m',
    rule_code: 'subing_ths_alert_15m_v1',
    bar_end: '2026-09-02T02:45:00Z',
  }), {
    symbol: 'jm',
    series_kind: 'actual_dominant',
    frequency: '15m',
    focus_bar_end: '2026-09-02T02:45:00Z',
  })
})

test('adds unified detail route helpers without changing the active Home entry helpers', () => {
  assert.deepEqual(marketHomeUnifiedProductChartQuery('ag'), {
    view: 'trend', symbol: 'ag', series_kind: 'actual_dominant', contract: undefined,
    frequency: '1d', focus_bar_end: undefined,
  })
  assert.deepEqual(marketHomeUnifiedEventChartQuery({
    symbol: 'jm', frequency: '15m', rule_code: 'subing_ths_alert_15m_v1',
    bar_end: '2026-09-02T02:45:00Z', id: 1, contract: 'JM2601',
    trading_day: '2026-09-02', result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
  }), {
    view: 'subing', symbol: 'jm', series_kind: 'actual_dominant', contract: undefined,
    frequency: '15m', focus_bar_end: '2026-09-02T02:45:00Z',
  })
})
