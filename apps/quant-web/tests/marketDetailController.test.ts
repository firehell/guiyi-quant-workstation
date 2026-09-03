import assert from 'node:assert/strict'
import test from 'node:test'

import { nextTick, ref } from 'vue'

import type { MarketSeriesMutation } from '../src/composables/useMarketSeries.ts'

import type {
  BarData,
  DominantContractItem,
  MarketOverlaySource,
  MarketReadState,
  ProductResearchResponse,
} from '../src/types/market.ts'
import type { MarketDetailIdentity } from '../src/types/marketDetail.ts'

const jmIdentity: MarketDetailIdentity = {
  view: 'free', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '15m',
}
const rbIdentity: MarketDetailIdentity = {
  view: 'free', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '15m',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept
    reject = decline
  })
  return { promise, resolve, reject }
}

function bar(symbol: string, close: number): BarData {
  return {
    time: '2026-09-03T02:45:00Z',
    trading_day: '2026-09-03',
    physicalContract: `${symbol.toUpperCase()}2601`,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 100,
    turnover: 1_000,
    openInterest: 200,
  }
}

function dominant(symbol: string): DominantContractItem {
  return {
    product: symbol,
    product_name: symbol === 'jm' ? '焦煤' : '螺纹钢',
    sector: '黑色',
    exchange: symbol === 'jm' ? 'DCE' : 'SHFE',
    actual_contract: `${symbol.toUpperCase()}2601`,
    dominant_mapping_date: '2026-09-03',
  }
}

function research(symbol: string): ProductResearchResponse {
  return {
    symbol,
    product_name: symbol === 'jm' ? '焦煤' : '螺纹钢',
    sector: '黑色',
    exchange: symbol === 'jm' ? 'DCE' : 'SHFE',
    series_kind: 'actual_dominant',
    contract: null,
    as_of: '2026-09-03T02:45:00Z',
    current_dominant: `${symbol.toUpperCase()}2601`,
    dominant_mapping_date: '2026-09-03',
    daily_trend: 'neutral',
    weekly_trend: 'neutral',
    position20: null,
    distance_to_20d_high: null,
    distance_to_20d_low: null,
    volume_ratio20: null,
    oi_change_1d: null,
    turnover_change_5d: null,
    atr14_percentile252: null,
    recent_daily: [],
  }
}

function marketState(symbol: string): MarketReadState {
  return {
    symbol,
    series_kind: 'actual_dominant',
    frequency: '15m',
    operational: true,
    phase: 'CLOSED',
    trading_day: '2026-09-03',
    live_eligible: false,
    live_available: false,
    live_contract: null,
    canonical_end: '2026-09-03T02:45:00Z',
    after_market: {},
  }
}

function fakeSeries() {
  const bars = ref<BarData[]>([])
  const hasMoreBefore = ref(false)
  const canonicalCoverage = ref<{ start: string; end: string } | null>(null)
  const loadingInitial = ref(false)
  const loadingBefore = ref(false)
  const marketStateRef = ref<MarketReadState | null>(null)
  const liveUnavailable = ref(false)
  const overlaySource = ref<MarketOverlaySource>('none')
  const mutation = ref<MarketSeriesMutation>({ kind: 'replace' })
  let disposed = false
  let loadMoreCalls = 0

  return {
    bars,
    hasMoreBefore,
    canonicalCoverage,
    loadingInitial,
    loadingBefore,
    marketState: marketStateRef,
    liveUnavailable,
    overlaySource,
    mutation,
    async replaceSeries(identity: MarketDetailIdentity) {
      bars.value = [bar(identity.symbol, identity.symbol === 'jm' ? 100 : 200)]
      marketStateRef.value = marketState(identity.symbol)
      canonicalCoverage.value = { start: '2026-09-01T02:45:00Z', end: '2026-09-03T02:45:00Z' }
    },
    clearSeries() { bars.value = [] },
    async loadMoreBefore() { loadMoreCalls += 1 },
    dispose() { disposed = true },
    get disposed() { return disposed },
    get loadMoreCalls() { return loadMoreCalls },
  }
}

test('late responses cannot overwrite a newer identity', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const jmResearch = deferred<ProductResearchResponse>()
  const rbResearch = deferred<ProductResearchResponse>()
  const series = fakeSeries()
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('jm'), dominant('rb')] }),
    fetchResearch: ({ symbol }) => symbol === 'jm' ? jmResearch.promise : rbResearch.promise,
  })

  const first = controller.switchIdentity(jmIdentity)
  const second = controller.switchIdentity(rbIdentity)
  rbResearch.resolve(research('rb'))
  await second

  assert.equal(controller.state.value.identity?.symbol, 'rb')
  assert.equal(controller.state.value.header?.symbol, 'rb')
  assert.equal(controller.state.value.header?.close, 200)
  assert.equal(controller.state.value.loading, false)

  jmResearch.resolve(research('jm'))
  await first
  assert.equal(controller.state.value.identity?.symbol, 'rb')
  assert.equal(controller.state.value.header?.symbol, 'rb')
  assert.equal(controller.state.value.header?.close, 200)
})

test('keeps route state explicit and delegates pagination and disposal to useMarketSeries seam', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('jm')] }),
    fetchResearch: async () => research('jm'),
  })

  assert.equal(controller.state.value.route.kind, 'valid')
  await controller.switchIdentity(jmIdentity)
  assert.equal(controller.state.value.generation, 1)
  assert.equal(controller.state.value.header?.productName, '焦煤')
  assert.deepEqual(controller.bars.value, series.bars.value)

  await controller.loadMoreBefore()
  assert.equal(series.loadMoreCalls, 1)
  controller.dispose()
  assert.equal(series.disposed, true)
})

test('keeps sourced market facts readable when optional research is unavailable', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('jm')] }),
    fetchResearch: async () => { throw new Error('private endpoint detail') },
  })

  await controller.switchIdentity(jmIdentity)
  assert.equal(controller.state.value.identity?.symbol, 'jm')
  assert.equal(controller.state.value.header?.symbol, 'jm')
  assert.equal(controller.state.value.header?.close, 100)
  assert.equal(controller.state.value.loading, false)
  assert.equal(controller.state.value.error, null)
})

test('refreshes the header from live series mutations for the active identity', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('jm')] }),
    fetchResearch: async () => research('jm'),
  })

  await controller.switchIdentity(jmIdentity)
  const liveBar = { ...bar('jm', 108), time: '2026-09-03T03:00:00Z' }
  series.bars.value = [bar('jm', 100), liveBar]
  series.marketState.value = { ...marketState('jm'), phase: 'TRADING', live_available: true }
  series.overlaySource.value = 'realtime'
  series.mutation.value = { kind: 'live', bars: [liveBar] }
  await nextTick()

  assert.equal(controller.state.value.header?.close, 108)
  assert.equal(controller.state.value.header?.change, 8)
  assert.equal(controller.state.value.header?.phase, 'TRADING')
  assert.equal(controller.state.value.header?.displaySource, '实时观察')
})

test('fails closed when product metadata is unavailable', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => { throw new Error('metadata offline') },
    fetchResearch: async () => research('jm'),
  })

  await controller.switchIdentity(jmIdentity)
  assert.equal(controller.state.value.header, null)
  assert.deepEqual(controller.bars.value, [])
  assert.equal(controller.state.value.loading, false)
  assert.equal(controller.state.value.error, '品种元数据不可用')
})

test('fails closed when metadata does not contain the requested symbol', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('rb')] }),
    fetchResearch: async () => research('jm'),
  })

  await controller.switchIdentity(jmIdentity)
  assert.equal(controller.state.value.header, null)
  assert.equal(controller.state.value.error, '品种元数据不可用')
})

test('pagination failure preserves the successful identity snapshot', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  series.loadMoreBefore = async () => { throw new Error('older page unavailable') }
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('jm')] }),
    fetchResearch: async () => research('jm'),
  })

  await controller.switchIdentity(jmIdentity)
  const header = controller.state.value.header
  await assert.rejects(controller.loadMoreBefore(), /older page unavailable/)
  assert.equal(controller.state.value.header, header)
  assert.equal(controller.state.value.error, null)
})

test('reports only an active generation market-series failure', async () => {
  const { useMarketDetailController } = await import('../src/composables/useMarketDetailController.ts')
  const series = fakeSeries()
  series.replaceSeries = async () => { throw new Error('page unavailable') }
  const controller = useMarketDetailController({
    routeQuery: () => ({ symbol: 'jm', view: 'free', series_kind: 'actual_dominant', frequency: '15m' }),
    createSeries: () => series,
    fetchDominants: async () => ({ items: [dominant('jm')] }),
    fetchResearch: async () => research('jm'),
  })

  await controller.switchIdentity(jmIdentity)
  assert.equal(controller.state.value.identity?.symbol, 'jm')
  assert.equal(controller.state.value.header, null)
  assert.equal(controller.state.value.loading, false)
  assert.equal(controller.state.value.error, '详情行情加载失败')
})
