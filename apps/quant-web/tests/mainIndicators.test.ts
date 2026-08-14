import test from 'node:test'
import assert from 'node:assert/strict'
import type { BarData } from '../src/types/market.ts'
import {
  HTDY_REPAINT_SCAN_ZONE_BARS,
  DEFAULT_VISIBLE_MAIN_INDICATORS,
  defaultMainChartPreferences,
  loadMainChartPreferences,
  MAIN_CHART_PREFERENCES_KEY,
  MAIN_INDICATOR_DEFINITIONS,
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
