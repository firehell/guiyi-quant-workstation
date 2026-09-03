import assert from 'node:assert/strict'
import test from 'node:test'

const identity = {
  view: 'free', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '15m',
} as const

function bar(time: string, close: number, physicalContract = 'JM2601') {
  return {
    time, physicalContract,
    open: close - 2, high: close + 3, low: close - 4, close,
    volume: 100, turnover: 2_000, openInterest: 300,
  }
}

function input(overrides: Record<string, unknown> = {}) {
  return {
    identity,
    dominant: {
      product: 'jm', product_name: '焦煤', sector: '黑色', exchange: 'DCE',
      actual_contract: 'JM2601', dominant_mapping_date: '2026-09-02',
    },
    bars: [bar('2026-09-02T02:30:00Z', 100), bar('2026-09-02T02:45:00Z', 110)],
    research: {
      symbol: 'jm', product_name: '焦煤研究', sector: '黑色研究', exchange: 'DCE',
      series_kind: 'actual_dominant', contract: null, as_of: '2026-09-02T02:45:00Z',
      current_dominant: 'JM2601', dominant_mapping_date: '2026-09-02',
      daily_trend: 'up', weekly_trend: 'up', position20: null, distance_to_20d_high: null,
      distance_to_20d_low: null, volume_ratio20: null, oi_change_1d: null,
      turnover_change_5d: null, atr14_percentile252: null, recent_daily: [],
    },
    marketState: {
      symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', operational: true,
      phase: 'TRADING', trading_day: '2026-09-02', live_eligible: true,
      live_available: true, live_contract: 'JM2601', canonical_end: '2026-09-02T02:30:00Z',
      after_market: {},
    },
    overlaySource: 'realtime',
    canonicalCoverage: { start: '2026-08-01T01:00:00Z', end: '2026-09-02T02:30:00Z' },
    hasMoreBefore: true,
    stale: false,
    ...overrides,
  }
}

test('builds sourced market facts from the latest completed bar without synthetic decisions', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input())

  assert.equal(model.close, 110)
  assert.equal(model.open, 108)
  assert.equal(model.change, 10)
  assert.equal(model.pct, 10)
  assert.equal(model.displayContract, 'JM2601')
  assert.equal(model.displaySource, '实时观察')
  assert.equal(model.freshness, 'fresh')
  assert.equal('score' in model, false)
  assert.equal('confidence' in model, false)
  assert.equal('positionAdvice' in model, false)
  assert.equal('targetPrice' in model, false)
  assert.ok(model.extendedSections.every((section) => section.rows.every((row) => row.source === 'market')))
})

test('withholds change and pct when the previous completed bar is absent', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({ bars: [bar('2026-09-02T02:45:00Z', 110)] }))

  assert.equal(model.change, null)
  assert.equal(model.pct, null)
})

test('does not invent a physical contract for continuous data', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({
    identity: { view: 'free', symbol: 'jm', seriesKind: 'continuous', frequency: '15m' },
    bars: [bar('2026-09-02T02:30:00Z', 100, undefined), bar('2026-09-02T02:45:00Z', 110, undefined)],
  }))

  assert.equal(model.displayContract, null)
})

test('keeps the contract route identity as the displayed contract', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({
    identity: { view: 'free', symbol: 'jm', seriesKind: 'contract', contract: 'JM2605', frequency: '15m' },
    bars: [bar('2026-09-02T02:30:00Z', 100, 'JM2605'), bar('2026-09-02T02:45:00Z', 110, 'JM2605')],
    research: null,
  }))

  assert.equal(model.displayContract, 'JM2605')
  assert.equal(model.freshness, 'fresh')
})

test('fails closed when metadata or bars disagree with the requested identity', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const actualMismatch = buildMarketDetailHeaderModel(input({
    dominant: { ...input().dominant, actual_contract: 'JM2605' },
  }))
  const contractMismatch = buildMarketDetailHeaderModel(input({
    identity: { view: 'free', symbol: 'jm', seriesKind: 'contract', contract: 'JM2605', frequency: '15m' },
  }))

  assert.equal(actualMismatch.freshness, 'unavailable')
  assert.equal(contractMismatch.freshness, 'unavailable')
  assert.equal(actualMismatch.close, null)
  assert.equal(contractMismatch.close, null)
})

test('fails closed when the latest actual-dominant bar has no physical contract', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({
    bars: [
      bar('2026-09-02T02:30:00Z', 100),
      { ...bar('2026-09-02T02:45:00Z', 110), physicalContract: undefined },
    ],
  }))

  assert.equal(model.freshness, 'unavailable')
  assert.equal(model.displayContract, null)
  assert.deepEqual(
    [model.open, model.high, model.low, model.close, model.change, model.pct],
    [null, null, null, null, null, null],
  )
})

test('keeps stale data distinct from unavailable data', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({ stale: true }))

  assert.equal(model.freshness, 'stale')
  assert.equal(model.close, 110)
})

test('ignores research from another symbol instead of contaminating the header', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({
    dominant: null,
    research: { ...input().research, symbol: 'rb', product_name: '螺纹钢', exchange: 'SHFE', sector: '黑色' },
  }))

  assert.equal(model.productName, 'JM')
  assert.equal(model.exchange, '')
  assert.equal(model.sector, '')
})

test('marks empty bars unavailable without manufacturing market prices', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const model = buildMarketDetailHeaderModel(input({ bars: [] }))

  assert.equal(model.freshness, 'unavailable')
  assert.deepEqual([model.open, model.high, model.low, model.close, model.change, model.pct], [null, null, null, null, null, null])
})

test('is deterministic and does not mutate source bars', async () => {
  const { buildMarketDetailHeaderModel } = await import('../src/utils/marketDetailViewModel.ts')
  const fixture = input()
  const originalBars = structuredClone(fixture.bars)

  assert.deepEqual(buildMarketDetailHeaderModel(fixture), buildMarketDetailHeaderModel(fixture))
  assert.deepEqual(fixture.bars, originalBars)
})
