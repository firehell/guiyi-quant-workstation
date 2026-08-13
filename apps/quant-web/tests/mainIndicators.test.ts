import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData, MainIndicatorSeries } from '../src/types/market.ts'
import {
  HTDY_REPAINT_SCAN_ZONE_BARS,
  activeIndicatorCodes,
  DEFAULT_VISIBLE_MAIN_INDICATORS,
  defaultMainChartPreferences,
  latestMainIndicatorValues,
  loadMainChartPreferences,
  MAIN_CHART_PREFERENCES_KEY,
  MAIN_INDICATOR_DEFINITIONS,
  normalizeMainIndicatorSeries,
  normalizeVisibleMainIndicators,
  resolveEffectiveSeriesIdentity,
  saveMainChartPreferences,
  visibleMainIndicatorsForOverlay,
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

test('main indicator registry keeps EMA overlays available and HTDY original observation-only', () => {
  assert.deepEqual(DEFAULT_VISIBLE_MAIN_INDICATORS, ['ema_21'])
  assert.equal(MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'ema_10')?.available, true)
  assert.equal(MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'ema_60')?.available, true)
  const htdy = MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'htdy')
  assert.equal(htdy?.available, true)
  assert.equal(htdy?.displayName, '火天大有（原始观察）')
  assert.equal(htdy?.capability, 'observation_overlay')
  assert.equal(htdy?.alertCapable, true)
  assert.equal(htdy?.repaintingRisk, 'known')
  assert.ok(htdy?.riskMessages?.includes('未来引用 / 重绘风险'))
  assert.ok(htdy?.riskMessages?.includes('公式语义尚未完全对齐'))
  assert.ok(htdy?.riskMessages?.includes('仅供人工观察'))
  assert.ok(htdy?.riskMessages?.includes('只允许当前已收线 Bar 的预警观察'))
  assert.ok(htdy?.riskMessages?.includes('不进入严格研究、回测、正式 live 或交易'))
  assert.equal(HTDY_REPAINT_SCAN_ZONE_BARS, 27)
  assert.equal(htdy?.unstableTailBars, HTDY_REPAINT_SCAN_ZONE_BARS)
})

test('normalizeVisibleMainIndicators keeps available indicators without a second access language', () => {
  assert.deepEqual(normalizeVisibleMainIndicators(['ema_60', 'unknown', 'htdy', 'ema_10', 'ema_10']), ['ema_60', 'htdy', 'ema_10'])
  assert.deepEqual(normalizeVisibleMainIndicators([]), [])
  assert.deepEqual(normalizeVisibleMainIndicators('bad'), ['ema_21'])
})

test('research overlay defaults to SuBing and exposes exactly one overlay indicator set', () => {
  assert.equal(defaultMainChartPreferences().selectedOverlay, 'subing')
  assert.deepEqual(visibleMainIndicatorsForOverlay('subing'), ['ema_21'])
  assert.deepEqual(visibleMainIndicatorsForOverlay('htdy'), ['htdy'])
  assert.deepEqual(visibleMainIndicatorsForOverlay('none'), [])
})

test('SuBing resolves current dominant without replacing the user Market series preference', () => {
  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'subing',
    userSeriesKind: 'continuous',
    userContract: undefined,
    dominantContract: 'JM2609',
  }), { seriesKind: 'contract', contract: 'JM2609' })

  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'htdy',
    userSeriesKind: 'continuous',
    userContract: undefined,
    dominantContract: 'JM2609',
  }), { seriesKind: 'continuous', contract: undefined })

  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'none',
    userSeriesKind: 'contract',
    userContract: 'JM2605',
    dominantContract: 'JM2609',
  }), { seriesKind: 'contract', contract: 'JM2605' })
})

test('preference v2 migrates legacy HTDY visibility and preserves period and realtime follow', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  values.set(MAIN_CHART_PREFERENCES_KEY, 'not-json')
  assert.equal(loadMainChartPreferences(storage).selectedOverlay, 'subing')

  values.delete(MAIN_CHART_PREFERENCES_KEY)
  values.set('guiyi.market.chart.preferences.v1', JSON.stringify({
    version: 1,
    visibleMainIndicators: ['ema_10', 'htdy', 'ema_60'],
    period: '15m',
    realtimeFollow: true,
  }))
  assert.deepEqual(loadMainChartPreferences(storage), {
    version: 2,
    selectedOverlay: 'htdy',
    period: '15m',
    realtimeFollow: true,
  })

  values.set('guiyi.market.chart.preferences.v1', JSON.stringify({
    version: 1,
    visibleMainIndicators: ['ema_10', 'ema_60'],
    period: '1d',
    realtimeFollow: false,
  }))
  assert.deepEqual(loadMainChartPreferences(storage), {
    version: 2,
    selectedOverlay: 'subing',
    period: '1d',
    realtimeFollow: false,
  })
})

test('preference v2 saves only the selected overlay and chart UI preferences', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  saveMainChartPreferences(
    {
      version: 2,
      selectedOverlay: 'none',
      period: '15m',
      realtimeFollow: true,
    },
    storage,
  )
  const loaded = loadMainChartPreferences(storage)
  assert.equal(loaded.version, 2)
  assert.equal(loaded.selectedOverlay, 'none')
  assert.equal(loaded.period, '15m')
  assert.equal(loaded.realtimeFollow, true)
  const saved = JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!)
  assert.equal(saved.visibleMainIndicators, undefined)
  assert.equal(saved.bars, undefined)
})

test('activeIndicatorCodes maps visible ids to backend indicator codes', () => {
  assert.deepEqual(activeIndicatorCodes(['ema_10', 'ema_21', 'ema_60']), ['ema10', 'ema21', 'ema60'])
  assert.deepEqual(activeIndicatorCodes(['ema_10', 'htdy', 'ema_21']), ['ema10', 'ema21'])
  assert.deepEqual(activeIndicatorCodes(['htdy']), [])
})

test('activeIndicatorCodes only changes when standard overlays change, not HTDY observation', () => {
  const withEma21 = activeIndicatorCodes(['ema_21']).join(',')
  const withEma21AndHtdy = activeIndicatorCodes(['ema_21', 'htdy']).join(',')
  const withEma10And21 = activeIndicatorCodes(['ema_10', 'ema_21']).join(',')
  assert.equal(withEma21, withEma21AndHtdy)
  assert.notEqual(withEma21, withEma10And21)
  assert.equal(withEma10And21, 'ema10,ema21')
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
  assert.equal(normalized[0].seed_policy, 'sma_window')
  assert.equal(normalized[0].calculation_start, '2026-01-01T09:00:00')
  assert.equal(normalized[0].confirmed_only, true)
  assert.equal(normalized[0].data_version, 'indicator-test')
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
    seed_policy: 'sma_window',
    calculation_start: '2026-01-01T09:00:00',
    warmup_bars: 20,
    confirmed_only: true,
    data_version: 'indicator-test',
    calculation_source: 'guiyi_quant.indicators.ema.ema_series',
    repainting_risk: 'none',
    points,
  }
}
