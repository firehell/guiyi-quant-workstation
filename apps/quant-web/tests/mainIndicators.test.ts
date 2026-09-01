import assert from 'node:assert/strict'
import test from 'node:test'
import {
  HTDY_WEB_OBSERVATION_METADATA,
  MAIN_CHART_PREFERENCES_KEY,
  RESEARCH_OVERLAY_DEFINITIONS,
  defaultMainChartPreferences,
  loadMainChartPreferences,
  normalizeOptionalEmaIndicators,
  researchOverlayCapability,
  resolveEffectiveSeriesIdentity,
  saveMainChartPreferences,
  visibleMainIndicatorsForOverlay,
} from '../src/utils/mainIndicators.ts'

test('chart preferences default to a strategy-free v9 view', () => {
  assert.deepEqual(defaultMainChartPreferences(), {
    version: 9,
    selectedOverlay: 'none',
    optionalEmaIndicators: [],
    showRangeDetector: false,
    period: null,
    realtimeFollow: false,
  })
})

test('only none and HTDY remain as research overlays', () => {
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS.map((item) => item.id), ['none', 'htdy'])
  assert.equal(researchOverlayCapability('htdy', 'actual_dominant', '15m').supported, true)
  assert.equal(researchOverlayCapability('none', 'contract', '1w').supported, true)
})

test('generic EMA and Range visibility is independent from the selected overlay', () => {
  assert.deepEqual(
    visibleMainIndicatorsForOverlay('none', ['ema_10', 'ema_21', 'ema_60'], true),
    ['ema_10', 'ema_21', 'ema_60', 'range_detector'],
  )
  assert.deepEqual(
    visibleMainIndicatorsForOverlay('htdy', ['ema_21'], false),
    ['ema_21', 'htdy'],
  )
  assert.deepEqual(normalizeOptionalEmaIndicators(['ema_60', 'ema_21', 'ema_10', 'ema_21']), [
    'ema_10', 'ema_21', 'ema_60',
  ])
})

test('effective series identity never changes for an overlay', () => {
  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'htdy',
    userSeriesKind: 'contract',
    userContract: 'JM2601',
    dominantContract: 'JM2605',
  }), { seriesKind: 'contract', contract: 'JM2601' })
})

test('v8 preferences are purged without a compatibility migration', () => {
  const values = new Map<string, string>([[
    'guiyi.market.chart.preferences.v8',
    JSON.stringify({
      version: 8,
      selectedOverlay: 'removed',
      optionalEmaIndicators: ['ema_21'],
      showRangeDetector: true,
    }),
  ]])
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  }
  assert.deepEqual(loadMainChartPreferences(storage), defaultMainChartPreferences())
  assert.equal(values.has(MAIN_CHART_PREFERENCES_KEY), false)
  assert.equal(values.has('guiyi.market.chart.preferences.v8'), false)
})

test('saving preferences normalizes unsupported values', () => {
  let value = ''
  saveMainChartPreferences({
    version: 9,
    selectedOverlay: 'htdy',
    optionalEmaIndicators: ['ema_60', 'ema_21'],
    showRangeDetector: false,
    period: '15m',
    realtimeFollow: true,
  }, { setItem: (_key, next) => { value = next } })
  assert.deepEqual(JSON.parse(value), {
    version: 9,
    selectedOverlay: 'htdy',
    optionalEmaIndicators: ['ema_21', 'ema_60'],
    showRangeDetector: false,
    period: '15m',
    realtimeFollow: true,
  })
})

test('HTDY remains explicitly repainting and observation-only', () => {
  assert.equal(HTDY_WEB_OBSERVATION_METADATA.status, 'observation_only')
  assert.equal(HTDY_WEB_OBSERVATION_METADATA.future_looking, true)
  assert.equal(HTDY_WEB_OBSERVATION_METADATA.historical_backtest_allowed, false)
})
