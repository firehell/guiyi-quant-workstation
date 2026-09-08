import assert from 'node:assert/strict'
import test from 'node:test'

import * as marketApi from '../src/api/marketWire.ts'

const pageWire = (numeric: string | number = '101.2500') => ({
  request: { series_kind: 'actual_dominant', symbol: 'rb', contract: null, frequency: '1d', before: null, limit: 2 },
  bars: [{
    bar_end: '2026-09-03T07:00:00Z', trading_day: '2026-09-03',
    open: numeric, high: '102.5000', low: 100, close: '102.0000', volume: '12',
    turnover: '1234.5000', open_interest: null,
  }],
  canonical_coverage: { start: '2026-09-03T07:00:00Z', end: '2026-09-03T07:00:00Z' },
  page: { has_more_before: false, next_before: null },
  resolved_contract_segments: [{ contract: 'RB2605', start_trading_day: '2026-09-03', end_trading_day: '2026-09-03' }],
})

test('normalizes the real Decimal-string Market bar wire once at the shared API boundary', () => {
  const normalize = (marketApi as unknown as {
    normalizeMarketBarsPageResponse?: (payload: unknown) => { bars: Array<Record<string, unknown>> }
  }).normalizeMarketBarsPageResponse
  assert.equal(typeof normalize, 'function')

  const response = normalize!(pageWire())
  assert.deepEqual(response.bars[0], {
    bar_end: '2026-09-03T07:00:00Z', trading_day: '2026-09-03',
    open: 101.25, high: 102.5, low: 100, close: 102, volume: 12,
    turnover: 1234.5, open_interest: null,
  })
  assert.equal(normalize!(pageWire(101.25)).bars[0]!.open, 101.25, 'existing numeric fixtures remain valid')
})

test('rejects non-finite, blank, boolean, null and malformed Market numeric wire values', () => {
  const normalize = (marketApi as unknown as {
    normalizeMarketBarsPageResponse: (payload: unknown) => unknown
  }).normalizeMarketBarsPageResponse
  for (const invalid of ['', ' ', 'NaN', 'Infinity', '-Infinity', '1px', '0x10', true, null, NaN, Infinity]) {
    const payload = pageWire() as Record<string, any>
    payload.bars[0].open = invalid
    assert.throws(() => normalize(payload), /bars\[0\]\.open/)
  }
})
