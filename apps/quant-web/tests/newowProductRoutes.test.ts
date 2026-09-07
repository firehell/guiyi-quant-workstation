import assert from 'node:assert/strict'
import test from 'node:test'

import {
  defaultMarketDetailPreferences,
  loadMarketDetailPreferences,
  MARKET_DETAIL_PREFERENCES_KEY,
  saveMarketDetailPreferences,
} from '../src/utils/marketDetailPreferences.ts'
import {
  marketDetailEventIdentity,
  parseMarketDetailRoute,
  resolveViewSwitchIdentity,
  serializeMarketDetailIdentity,
} from '../src/utils/marketDetailRoute.ts'
import { marketHomeUnifiedProductChartQuery } from '../src/utils/marketHomeRoutes.ts'

function storage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    values,
  }
}

test('legacy Trend remains a fixed D1 deep link', () => {
  assert.equal(parseMarketDetailRoute({ symbol: 'rb', view: 'trend', frequency: '15m' }).kind, 'invalid')
  assert.equal(parseMarketDetailRoute({ symbol: 'rb', view: 'trend', frequency: '1d' }).kind, 'valid')
})

test('Newow accepts only its three strategies and independent completed periods', () => {
  for (const strategy of ['trend', 'oscillation', 'main_rise'] as const) {
    for (const frequency of ['1w', '1d', '60m'] as const) {
      assert.deepEqual(parseMarketDetailRoute({
        symbol: 'rb', view: 'newow', strategy, series_kind: 'actual_dominant', frequency,
      }), {
        kind: 'valid',
        identity: { view: 'newow', symbol: 'rb', strategy, seriesKind: 'actual_dominant', frequency },
      })
    }
  }

  for (const query of [
    { symbol: 'rb', view: 'newow', strategy: 'private_screener', series_kind: 'actual_dominant', frequency: '1d' },
    { symbol: 'rb', view: 'newow', strategy: 'trend', series_kind: 'continuous', frequency: '1d' },
    { symbol: 'rb', view: 'newow', strategy: 'trend', series_kind: 'contract', contract: 'RB2610', frequency: '1d' },
    { symbol: 'rb', view: 'newow', strategy: 'trend', series_kind: 'actual_dominant', contract: ['RB2610'], frequency: '1d' },
    { symbol: 'rb', view: 'newow', strategy: 'trend', series_kind: 'actual_dominant', frequency: '15m' },
    { symbol: 'rb', view: 'newow', strategy: 'trend', series_kind: 'actual_dominant', frequency: '1d', focus_bar_end: '2026-09-02T07:00:00Z' },
  ]) assert.equal(parseMarketDetailRoute(query).kind, 'invalid')
})

test('Newow defaults, serializes, and switches with one route identity authority', () => {
  const defaults = {
    kind: 'valid' as const,
    identity: {
      view: 'newow' as const,
      symbol: 'rb',
      strategy: 'trend' as const,
      seriesKind: 'actual_dominant' as const,
      frequency: '1d' as const,
    },
  }
  assert.deepEqual(parseMarketDetailRoute({ symbol: 'rb', view: 'newow' }), defaults)
  assert.deepEqual(serializeMarketDetailIdentity(defaults.identity), {
    view: 'newow', symbol: 'rb', strategy: 'trend', series_kind: 'actual_dominant',
    contract: undefined, frequency: '1d', focus_bar_end: undefined,
  })

  const restore = {
    newow: { strategy: 'oscillation' as const, frequency: '60m' as const },
    htdy: { seriesKind: 'continuous' as const, frequency: '30m' as const },
    free: { seriesKind: 'actual_dominant' as const, frequency: '5m' as const },
  }
  assert.deepEqual(resolveViewSwitchIdentity('newow', 'ag', null, restore), {
    view: 'newow', symbol: 'ag', strategy: 'oscillation', seriesKind: 'actual_dominant', frequency: '60m',
  })
})

test('existing HTDY and SuBing Event identities remain unchanged', () => {
  assert.deepEqual(marketDetailEventIdentity({
    id: 1, symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-02', frequency: '30m',
    bar_end: '2026-09-02T02:45:00Z', detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
    rule_code: 'htdy_original_15m', result_codes: ['buy'],
  }), {
    view: 'htdy', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '30m',
    focusBarEnd: '2026-09-02T02:45:00Z',
  })
  assert.deepEqual(marketDetailEventIdentity({
    id: 2, symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-02', frequency: '15m',
    bar_end: '2026-09-02T02:45:00Z', detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
    rule_code: 'subing_ths_alert_15m_v1', result_codes: ['sell'],
  }), {
    view: 'subing', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '15m',
    focusBarEnd: '2026-09-02T02:45:00Z',
  })
})

test('detail preferences v2 migrate v1 and v9 without persisting route-owned facts', () => {
  assert.equal(MARKET_DETAIL_PREFERENCES_KEY, 'guiyi.market.detail.preferences.v2')
  assert.deepEqual(defaultMarketDetailPreferences().newow, { strategy: 'trend', frequency: '1d' })
  assert.equal(defaultMarketDetailPreferences().lastView, 'newow')

  const fromV1 = loadMarketDetailPreferences(storage({
    'guiyi.market.detail.preferences.v1': JSON.stringify({
      version: 1,
      lastView: 'trend',
      htdy: { seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true },
      free: { seriesKind: 'actual_dominant', frequency: '5m', optionalEmaIndicators: ['ema_10'], showRangeDetector: true },
    }),
  }))
  assert.equal(fromV1.version, 2)
  assert.equal(fromV1.lastView, 'newow')
  assert.deepEqual(fromV1.newow, { strategy: 'trend', frequency: '1d' })
  assert.equal(fromV1.htdy.frequency, '30m')
  assert.equal(fromV1.free.frequency, '5m')

  const fromV9 = loadMarketDetailPreferences(storage({
    'guiyi.market.chart.preferences.v9': JSON.stringify({
      version: 9, selectedOverlay: 'htdy', period: '60m',
      optionalEmaIndicators: ['ema_21'], showRangeDetector: true,
    }),
  }))
  assert.equal(fromV9.lastView, 'newow')
  assert.deepEqual(fromV9.newow, { strategy: 'trend', frequency: '1d' })
  assert.equal(fromV9.free.frequency, '60m')
  assert.deepEqual(fromV9.htdy, defaultMarketDetailPreferences().htdy)

  const target = storage()
  saveMarketDetailPreferences({
    ...defaultMarketDetailPreferences(),
    newow: {
      strategy: 'main_rise', frequency: '1w',
      contract: 'RB2610', focusBarEnd: '2026-09-02T07:00:00Z', referenceReturn: 9.9,
    },
  } as never, target)
  assert.deepEqual(JSON.parse(target.values.get(MARKET_DETAIL_PREFERENCES_KEY)!), {
    version: 2,
    lastView: 'newow',
    newow: { strategy: 'main_rise', frequency: '1w' },
    htdy: defaultMarketDetailPreferences().htdy,
    free: defaultMarketDetailPreferences().free,
  })
})

test('ordinary unified Market Home product entry defaults to Newow Trend D1', () => {
  assert.deepEqual(marketHomeUnifiedProductChartQuery('ag'), {
    view: 'newow', symbol: 'ag', strategy: 'trend', series_kind: 'actual_dominant',
    contract: undefined, frequency: '1d', focus_bar_end: undefined,
  })
})
