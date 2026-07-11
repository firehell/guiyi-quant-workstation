import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData, MainIndicatorSeries } from '../src/types/market.ts'
import {
  activeIndicatorCodes,
  buildMainIndicatorRequestParams,
  DEFAULT_VISIBLE_MAIN_INDICATORS,
  latestMainIndicatorValues,
  loadMainChartPreferences,
  MAIN_CHART_PREFERENCES_KEY,
  MAIN_INDICATOR_DEFINITIONS,
  normalizeMainIndicatorSeries,
  normalizeVisibleMainIndicators,
  saveMainChartPreferences,
} from '../src/utils/mainIndicators.ts'

const bars: BarData[] = Array.from({ length: 80 }, (_, index) => {
  const close = 100 + index
  return {
    time: `2026-01-${String(index + 1).padStart(2, '0')}`,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 100 + index,
  }
})

test('main indicator registry keeps EMA overlays available and HTDY disabled', () => {
  assert.deepEqual(DEFAULT_VISIBLE_MAIN_INDICATORS, ['ema_21'])
  assert.equal(MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'ema_10')?.available, true)
  assert.equal(MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'ema_60')?.available, true)
  const htdy = MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'htdy')
  assert.equal(htdy?.available, false)
  assert.equal(htdy?.alertCapable, false)
})

test('normalizeVisibleMainIndicators ignores unknown and unavailable ids while allowing empty selection', () => {
  assert.deepEqual(normalizeVisibleMainIndicators(['ema_60', 'unknown', 'htdy', 'ema_10', 'ema_10']), ['ema_60', 'ema_10'])
  assert.deepEqual(normalizeVisibleMainIndicators([]), [])
  assert.deepEqual(normalizeVisibleMainIndicators('bad'), ['ema_21'])
})

test('loadMainChartPreferences recovers from corrupt storage and saves only UI preferences', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  values.set(MAIN_CHART_PREFERENCES_KEY, 'not-json')
  assert.deepEqual(loadMainChartPreferences(storage).visibleMainIndicators, ['ema_21'])

  saveMainChartPreferences(
    {
      version: 1,
      visibleMainIndicators: ['ema_10', 'ema_60'],
      period: '15m',
      realtimeFollow: true,
    },
    storage,
  )
  const loaded = loadMainChartPreferences(storage)
  assert.deepEqual(loaded.visibleMainIndicators, ['ema_10', 'ema_60'])
  assert.equal(loaded.period, '15m')
  assert.equal(loaded.realtimeFollow, true)
  assert.equal(JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!).bars, undefined)
})

test('activeIndicatorCodes maps visible ids to backend indicator codes', () => {
  assert.deepEqual(activeIndicatorCodes(['ema_10', 'ema_21', 'ema_60']), ['ema10', 'ema21', 'ema60'])
  assert.deepEqual(activeIndicatorCodes(['htdy']), [])
})

test('buildMainIndicatorRequestParams uses visible bars as display window and skips empty active selection', () => {
  const params = buildMainIndicatorRequestParams({
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    bars: bars.slice(10, 20),
    visibleIds: ['ema_21', 'ema_60'],
    provider: 'rqdata',
    dataRole: 'primary',
    quoteMode: true,
    allowContinuous: false,
  })

  assert.deepEqual(params, {
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    indicator_codes: 'ema21,ema60',
    display_start: '2026-01-11',
    display_end: '2026-01-20',
    display_bar_count: 10,
    provider: 'rqdata',
    data_role: 'primary',
    quote_mode: true,
    allow_continuous: false,
  })
  assert.equal(buildMainIndicatorRequestParams({
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    bars,
    visibleIds: [],
  }), null)
})

test('normalizeMainIndicatorSeries keeps backend EMA points and drops unknown series', () => {
  const normalized = normalizeMainIndicatorSeries([
    series('ema_21', 'ema21', [
      { time: '2026-01-21', value: 110, ready: true, valid: true },
      { time: '2026-01-22', value: null, ready: false, valid: true, reason: 'warming_up' },
    ]),
    series('htdy', 'huo_tian_da_you', [{ time: '2026-01-21', value: 1, ready: true, valid: true }]),
    series('ema_21', 'unknown', [{ time: '2026-01-21', value: 1, ready: true, valid: true }], 'bad_id'),
  ])
  assert.equal(normalized.length, 1)
  assert.equal(normalized[0].id, 'ema_21')
  assert.equal(normalized[0].points[1].value, null)
  assert.equal(normalized[0].points[1].reason, 'warming_up')
})

test('latestMainIndicatorValues uses API readiness instead of local EMA calculation', () => {
  const values = latestMainIndicatorValues(
    [
      series('ema_10', 'ema10', [{ time: '2026-01-22', value: 120, ready: true, valid: true }]),
      series('ema_21', 'ema21', [{ time: '2026-01-22', value: null, ready: false, valid: true, reason: 'warming_up' }]),
    ],
    ['ema_10', 'ema_21', 'ema_60'],
  )
  assert.deepEqual(values.map((item) => item.id), ['ema_10', 'ema_21', 'ema_60'])
  assert.equal(values[0].value, 120)
  assert.equal(values[1].value, null)
  assert.equal(values[1].reason, 'warming_up')
  assert.equal(values[2].reason, 'indicator_not_loaded')
})

function series(
  id: string,
  code: string,
  points: MainIndicatorSeries['points'],
  rawId: string = id,
): MainIndicatorSeries {
  return {
    id: rawId as MainIndicatorSeries['id'],
    indicator_code: code,
    display_name: code.toUpperCase(),
    indicator_version: 'v1',
    parameters: { period: 21 },
    parameters_hash: 'hash',
    warmup_bars: 20,
    calculation_source: 'guiyi_quant.indicators.ema.ema_series',
    repainting_risk: 'none',
    points,
  }
}
