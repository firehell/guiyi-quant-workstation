import assert from 'node:assert/strict'
import test from 'node:test'

import {
  defaultMarketDetailPreferences,
  loadMarketDetailPreferences,
  saveMarketDetailPreferences,
} from '../src/utils/marketDetailPreferences.ts'

function storage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), values }
}

test('missing, corrupt, and wrong-version storage fail closed', () => {
  assert.deepEqual(loadMarketDetailPreferences(null), defaultMarketDetailPreferences())
  assert.deepEqual(loadMarketDetailPreferences(storage({ 'guiyi.market.detail.preferences.v1': '{bad' })), defaultMarketDetailPreferences())
  assert.deepEqual(loadMarketDetailPreferences(storage({ 'guiyi.market.detail.preferences.v1': '{"version":2}' })), defaultMarketDetailPreferences())
})

test('v9 migrates generic settings to free only and never selects HTDY', () => {
  const result = loadMarketDetailPreferences(storage({
    'guiyi.market.chart.preferences.v9': JSON.stringify({ version: 9, selectedOverlay: 'htdy', period: '60m', optionalEmaIndicators: ['ema_21', 'bad'], showRangeDetector: true }),
  }))
  assert.equal(result.lastView, 'trend')
  assert.deepEqual(result.free, { seriesKind: 'actual_dominant', frequency: '60m', optionalEmaIndicators: ['ema_21'], showRangeDetector: true })
  assert.deepEqual(result.htdy, defaultMarketDetailPreferences().htdy)
})

test('normalizes invalid saved values and isolates HTDY from Free', () => {
  const result = loadMarketDetailPreferences(storage({
    'guiyi.market.detail.preferences.v1': JSON.stringify({ version: 1, lastView: 'bad', htdy: { seriesKind: 'contract', frequency: 'bad', optionalEmaIndicators: ['ema_60', 'bad'], showRangeDetector: 1 }, free: { seriesKind: 'continuous', frequency: '5m', optionalEmaIndicators: ['ema_10'], showRangeDetector: true } }),
  }))
  assert.equal(result.lastView, 'trend')
  assert.deepEqual(result.htdy, { seriesKind: 'actual_dominant', frequency: '15m', optionalEmaIndicators: ['ema_60'], showRangeDetector: false })
  assert.deepEqual(result.free, { seriesKind: 'continuous', frequency: '5m', optionalEmaIndicators: ['ema_10'], showRangeDetector: true })
})

test('saving never persists a contract or unsupported values', () => {
  const target = storage()
  saveMarketDetailPreferences({ ...defaultMarketDetailPreferences(), free: { seriesKind: 'continuous', frequency: '1d', optionalEmaIndicators: ['ema_60'], showRangeDetector: true } }, target)
  assert.deepEqual(JSON.parse(target.values.get('guiyi.market.detail.preferences.v1')!), {
    version: 1, lastView: 'trend',
    htdy: defaultMarketDetailPreferences().htdy,
    free: { seriesKind: 'continuous', frequency: '1d', optionalEmaIndicators: ['ema_60'], showRangeDetector: true },
  })
})
