import test from 'node:test'
import assert from 'node:assert/strict'
import { MARKET_FREQUENCIES, type BarData, type SeriesKind } from '../src/types/market.ts'
import {
  HTDY_REPAINT_SCAN_ZONE_BARS,
  DEFAULT_VISIBLE_MAIN_INDICATORS,
  defaultMainChartPreferences,
  loadMainChartPreferences,
  MAIN_CHART_PREFERENCES_KEY,
  MAIN_INDICATOR_DEFINITIONS,
  nStructureBandCapability,
  normalizeOptionalEmaIndicators,
  normalizeVisibleMainIndicators,
  resolveEffectiveSeriesIdentity,
  researchOverlayCapability,
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
  assert.deepEqual(defaultMainChartPreferences(), {
    version: 4,
    selectedOverlay: 'subing',
    optionalEmaIndicators: [],
    showNStructureBands: false,
    period: null,
    realtimeFollow: false,
  })
  assert.deepEqual(normalizeOptionalEmaIndicators(['ema_60', 'ema_21', 'ema_10', 'ema_60', 'htdy']), ['ema_10', 'ema_60'])
  assert.deepEqual(visibleMainIndicatorsForOverlay('subing', []), ['ema_21'])
  assert.deepEqual(visibleMainIndicatorsForOverlay('subing', ['ema_10', 'ema_60']), ['ema_10', 'ema_21', 'ema_60'])
  assert.deepEqual(visibleMainIndicatorsForOverlay('htdy', ['ema_10', 'ema_60']), ['ema_10', 'ema_60', 'htdy'])
  assert.deepEqual(visibleMainIndicatorsForOverlay('none', ['ema_10', 'ema_60']), [])
})

test('N structure bands are independently supported only for actual-dominant 5m', () => {
  assert.equal(nStructureBandCapability('actual_dominant', '5m'), true)
  assert.equal(nStructureBandCapability('actual_dominant', '15m'), false)
  assert.equal(nStructureBandCapability('continuous', '5m'), false)
  assert.equal(nStructureBandCapability('contract', '5m'), false)
})

test('HTDY overlay stays available on every formal frequency and existing chart series kind', () => {
  const seriesKinds: SeriesKind[] = ['continuous', 'actual_dominant', 'contract']

  for (const seriesKind of seriesKinds) {
    for (const frequency of MARKET_FREQUENCIES) {
      assert.equal(
        researchOverlayCapability('htdy', seriesKind, frequency).supported,
        true,
        `${seriesKind} ${frequency}`,
      )
      assert.deepEqual(
        visibleMainIndicatorsForOverlay('htdy', ['ema_10', 'ema_60']),
        ['ema_10', 'ema_60', 'htdy'],
      )
    }
  }
})

test('research overlays never replace the user Market display series identity', () => {
  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'subing',
    userSeriesKind: 'continuous',
    userContract: undefined,
    dominantContract: 'JM2609',
  }), { seriesKind: 'continuous', contract: undefined })

  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'subing',
    userSeriesKind: 'actual_dominant',
    userContract: undefined,
    dominantContract: 'JM2609',
  }), { seriesKind: 'actual_dominant', contract: undefined })

  assert.deepEqual(resolveEffectiveSeriesIdentity({
    overlay: 'subing',
    userSeriesKind: 'contract',
    userContract: 'JM2605',
    dominantContract: 'JM2609',
  }), { seriesKind: 'contract', contract: 'JM2605' })

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

test('preference v2 migrates legacy overlay and preserves period and realtime follow', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  values.set(MAIN_CHART_PREFERENCES_KEY, 'not-json')
  assert.deepEqual(loadMainChartPreferences(storage), defaultMainChartPreferences())

  values.delete(MAIN_CHART_PREFERENCES_KEY)
  values.set('guiyi.market.chart.preferences.v2', JSON.stringify({
    version: 2,
    selectedOverlay: 'htdy',
    period: '15m',
    realtimeFollow: true,
  }))
  assert.deepEqual(loadMainChartPreferences(storage), {
    version: 4,
    selectedOverlay: 'htdy',
    optionalEmaIndicators: [],
    showNStructureBands: false,
    period: '15m',
    realtimeFollow: true,
  })

  values.delete(MAIN_CHART_PREFERENCES_KEY)
  values.delete('guiyi.market.chart.preferences.v2')
  values.set('guiyi.market.chart.preferences.v1', JSON.stringify({
    version: 1,
    visibleMainIndicators: ['ema_10', 'htdy', 'ema_60'],
    period: '15m',
    realtimeFollow: true,
  }))
  assert.deepEqual(loadMainChartPreferences(storage), {
    version: 4,
    selectedOverlay: 'htdy',
    optionalEmaIndicators: [],
    showNStructureBands: false,
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
    version: 4,
    selectedOverlay: 'subing',
    optionalEmaIndicators: [],
    showNStructureBands: false,
    period: '1d',
    realtimeFollow: false,
  })
})

test('preference v4 saves and loads optional EMAs plus N structure bands', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  saveMainChartPreferences(
    {
      version: 4,
      selectedOverlay: 'none',
      optionalEmaIndicators: ['ema_60', 'ema_10'],
      showNStructureBands: true,
      period: '15m',
      realtimeFollow: true,
    },
    storage,
  )
  const loaded = loadMainChartPreferences(storage)
  assert.equal(loaded.version, 4)
  assert.equal(loaded.selectedOverlay, 'none')
  assert.deepEqual(loaded.optionalEmaIndicators, ['ema_10', 'ema_60'])
  assert.equal(loaded.showNStructureBands, true)
  assert.equal(loaded.period, '15m')
  assert.equal(loaded.realtimeFollow, true)
  const saved = JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!)
  assert.equal(saved.visibleMainIndicators, undefined)
  assert.equal(saved.bars, undefined)

  values.set(MAIN_CHART_PREFERENCES_KEY, 'not-json')
  assert.deepEqual(loadMainChartPreferences(storage), defaultMainChartPreferences())
})

test('preference v3 migrates retired overlays and defaults N structure bands off', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  const cases = [
    ['n_structure', 'none'],
    ['jdj', 'none'],
    ['unknown', 'none'],
    ['jdj_strategy', 'jdj_strategy'],
    ['htdy', 'htdy'],
  ] as const
  for (const [storedOverlay, expectedOverlay] of cases) {
    values.set('guiyi.market.chart.preferences.v3', JSON.stringify({
      version: 3,
      selectedOverlay: storedOverlay,
      optionalEmaIndicators: [],
      period: '1m',
      realtimeFollow: false,
    }))
    const loaded = loadMainChartPreferences(storage)
    assert.equal(loaded.selectedOverlay, expectedOverlay, storedOverlay)
    assert.equal(loaded.showNStructureBands, false, storedOverlay)
  }
})

test('preference v3 preserves the JDJ strategy overlay across save and load', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  saveMainChartPreferences({
    version: 4,
    selectedOverlay: 'jdj_strategy',
    optionalEmaIndicators: [],
    showNStructureBands: false,
    period: '1m',
    realtimeFollow: false,
  }, storage)

  assert.equal(loadMainChartPreferences(storage).selectedOverlay, 'jdj_strategy')
  assert.equal(JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!).selectedOverlay, 'jdj_strategy')
})

test('preference loading falls back when accessing browser localStorage throws', () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      get localStorage() {
        throw new Error('SecurityError')
      },
    },
  })

  try {
    assert.deepEqual(loadMainChartPreferences(), defaultMainChartPreferences())
    assert.doesNotThrow(() => saveMainChartPreferences(defaultMainChartPreferences()))
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
    else Reflect.deleteProperty(globalThis, 'window')
  }
})

test('preference loading falls back when localStorage getItem throws', () => {
  assert.deepEqual(loadMainChartPreferences({
    getItem() {
      throw new Error('SecurityError')
    },
  }), defaultMainChartPreferences())
})

test('preference saving ignores localStorage setItem failures', () => {
  assert.doesNotThrow(() => saveMainChartPreferences(defaultMainChartPreferences(), {
    setItem() {
      throw new Error('SecurityError')
    },
  }))
})
