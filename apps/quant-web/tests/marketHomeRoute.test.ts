import assert from 'node:assert/strict'
import test from 'node:test'

import {
  marketHomeEventChartQuery,
  marketHomeViewChartQuery,
  marketHomeUnifiedEventChartQuery,
  marketHomeUnifiedProductChartQuery,
} from '../src/utils/marketHomeRoutes.ts'

test('uses only actual-dominant chart route intents for products and immutable HTDY Events', () => {
  assert.deepEqual(marketHomeEventChartQuery({
    symbol: 'jm', frequency: '15m', rule_code: 'htdy_original_15m',
    bar_end: '2026-09-02T02:45:00Z', id: 1, contract: 'JM2601',
    trading_day: '2026-09-02', result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
  }), { view: 'htdy', symbol: 'jm', series_kind: 'actual_dominant', contract: undefined, frequency: '15m', focus_bar_end: '2026-09-02T02:45:00Z' })
  assert.deepEqual(marketHomeEventChartQuery({
    symbol: 'jm',
    frequency: '15m',
    rule_code: 'subing_ths_alert_15m_v1',
    bar_end: '2026-09-02T02:45:00Z',
  }), {
    view: 'subing', symbol: 'jm', series_kind: 'actual_dominant', contract: undefined,
    frequency: '15m', focus_bar_end: '2026-09-02T02:45:00Z',
  })
})

test('sends the ordinary unified product entry to Newow while preserving Event identity', () => {
  assert.deepEqual(marketHomeUnifiedProductChartQuery('ag'), {
    view: 'newow', symbol: 'ag', strategy: 'trend', series_kind: 'actual_dominant', contract: undefined,
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


test('explicit Home view choices preserve symbol and fixed view frequency', () => {
  for (const [view, frequency] of [['newow', '1d'], ['htdy', '1d'], ['subing', '15m'], ['free', '1d']] as const) {
    assert.deepEqual(marketHomeViewChartQuery(view, 'ag'), {
      view, symbol: 'ag', ...(view === 'newow' ? { strategy: 'trend' } : {}),
      series_kind: 'actual_dominant', contract: undefined, frequency, focus_bar_end: undefined,
    })
  }
})
