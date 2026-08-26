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
  subingStrategyHistoricalCapability,
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
    version: 5,
    selectedOverlay: 'subing',
    optionalEmaIndicators: [],
    showNStructureBands: false,
    showSubingInternalProcess: false,
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

test('SuBing Strategy history is independently restricted to actual-dominant 15m', () => {
  assert.equal(researchOverlayCapability('subing', 'actual_dominant', '5m').supported, true)
  assert.equal(
    researchOverlayCapability('subing', 'actual_dominant', '15m').definition.historicalSource,
    'subing_strategy',
  )
  assert.equal(subingStrategyHistoricalCapability('actual_dominant', '15m'), true)
  assert.equal(subingStrategyHistoricalCapability('actual_dominant', '5m'), false)
  assert.equal(subingStrategyHistoricalCapability('continuous', '15m'), false)
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

test('preference loading purges and ignores legacy schemas', () => {
  const values = new Map<string, string>()
  const removed: string[] = []
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => {
      removed.push(key)
      values.delete(key)
    },
  }

  values.set('guiyi.market.chart.preferences.v1', JSON.stringify({
    version: 1,
    visibleMainIndicators: ['htdy'],
  }))
  values.set('guiyi.market.chart.preferences.v2', JSON.stringify({
    version: 2,
    selectedOverlay: 'htdy',
  }))
  values.set('guiyi.market.chart.preferences.v3', JSON.stringify({
    version: 3,
    selectedOverlay: 'jdj_strategy',
    optionalEmaIndicators: ['ema_10'],
  }))

  assert.deepEqual(loadMainChartPreferences(storage), defaultMainChartPreferences())
  assert.deepEqual(removed, [
    'guiyi.market.chart.preferences.v1',
    'guiyi.market.chart.preferences.v2',
    'guiyi.market.chart.preferences.v3',
  ])
  assert.equal(values.size, 0)
})

test('preference v5 saves and loads overlays plus the internal-process toggle', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  saveMainChartPreferences(
    {
      version: 5,
      selectedOverlay: 'none',
      optionalEmaIndicators: ['ema_60', 'ema_10'],
      showNStructureBands: true,
      showSubingInternalProcess: true,
      period: '15m',
      realtimeFollow: true,
    },
    storage,
  )
  const loaded = loadMainChartPreferences(storage)
  assert.equal(loaded.version, 5)
  assert.equal(loaded.selectedOverlay, 'none')
  assert.deepEqual(loaded.optionalEmaIndicators, ['ema_10', 'ema_60'])
  assert.equal(loaded.showNStructureBands, true)
  assert.equal(loaded.showSubingInternalProcess, true)
  assert.equal(loaded.period, '15m')
  assert.equal(loaded.realtimeFollow, true)
  const saved = JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!)
  assert.equal(saved.visibleMainIndicators, undefined)
  assert.equal(saved.bars, undefined)

  values.set(MAIN_CHART_PREFERENCES_KEY, 'not-json')
  assert.deepEqual(loadMainChartPreferences(storage), defaultMainChartPreferences())
})

test('current preferences preserve the JDJ strategy overlay across save and load', () => {
  const values = new Map<string, string>()
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
  }

  saveMainChartPreferences({
    version: 5,
    selectedOverlay: 'jdj_strategy',
    optionalEmaIndicators: [],
    showNStructureBands: false,
    showSubingInternalProcess: false,
    period: '1m',
    realtimeFollow: false,
  }, storage)

  assert.equal(loadMainChartPreferences(storage).selectedOverlay, 'jdj_strategy')
  assert.equal(JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!).selectedOverlay, 'jdj_strategy')
})

test('preference v4 migrates losslessly to v5 with internal process off', () => {
  const values = new Map<string, string>()
  const removed: string[] = []
  const storage = {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => { removed.push(key); values.delete(key) },
  }
  values.set('guiyi.market.chart.preferences.v4', JSON.stringify({
    version: 4,
    selectedOverlay: 'subing',
    optionalEmaIndicators: ['ema_60'],
    showNStructureBands: true,
    period: '15m',
    realtimeFollow: true,
  }))

  assert.deepEqual(loadMainChartPreferences(storage), {
    version: 5,
    selectedOverlay: 'subing',
    optionalEmaIndicators: ['ema_60'],
    showNStructureBands: true,
    showSubingInternalProcess: false,
    period: '15m',
    realtimeFollow: true,
  })
  assert.equal(JSON.parse(values.get(MAIN_CHART_PREFERENCES_KEY)!).version, 5)
  assert.deepEqual(removed, ['guiyi.market.chart.preferences.v1',
    'guiyi.market.chart.preferences.v2', 'guiyi.market.chart.preferences.v3',
    'guiyi.market.chart.preferences.v4'])
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
