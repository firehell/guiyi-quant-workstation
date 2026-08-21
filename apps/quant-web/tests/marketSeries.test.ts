import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  isCurrentGeneration,
  MarketSeriesPhysicalIdentityError,
  mergeInitialPage,
  prependHistoricalPage,
  resolveHistoricalPhysicalContract,
  useMarketSeries,
} from '../src/composables/useMarketSeries.ts'
import type { MarketBarsPageResponse, MarketReadState } from '../src/types/market.ts'

function page(
  bars: Array<{ bar_end: string; close: number }>,
  pageMeta: { has_more_before: boolean; next_before: string | null },
  canonicalCoverage: { start: string; end: string } | null = null,
): MarketBarsPageResponse {
  return {
    request: {
      series_kind: 'continuous',
      symbol: 'jm',
      contract: null,
      frequency: '15m',
      before: null,
      limit: 1200,
    },
    bars: bars.map((bar) => ({
      bar_end: bar.bar_end,
      trading_day: bar.bar_end.slice(0, 10),
      open: bar.close - 1,
      high: bar.close + 1,
      low: bar.close - 2,
      close: bar.close,
      volume: 10,
      turnover: null,
      open_interest: null,
    })),
    canonical_coverage: canonicalCoverage,
    page: pageMeta,
    resolved_contract_segments: [],
  }
}

describe('market historical series', () => {
  it('binds contract history to the normalized requested physical contract', () => {
    const response = page([
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
    ], { has_more_before: false, next_before: null })
    response.request = { ...response.request, series_kind: 'contract', contract: ' jm2609 ' }

    assert.deepEqual(mergeInitialPage(response).bars.map((bar) => bar.physicalContract), ['JM2609', 'JM2609'])
  })

  it('binds actual-dominant history to its one inclusive resolved segment', () => {
    const response = page([
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-08T09:15:00Z', close: 102 },
    ], { has_more_before: false, next_before: null })
    response.request = { ...response.request, series_kind: 'actual_dominant' }
    response.resolved_contract_segments = [
      { contract: ' jm2609 ', start_trading_day: '2026-08-07', end_trading_day: '2026-08-07' },
      { contract: 'JM2701', start_trading_day: '2026-08-08', end_trading_day: '2026-08-08' },
    ]

    assert.deepEqual(mergeInitialPage(response).bars.map((bar) => bar.physicalContract), ['JM2609', 'JM2701'])
  })

  it('leaves an actual-dominant bar without a resolved segment physically unbound', () => {
    const response = page([{ bar_end: '2026-08-07T09:15:00Z', close: 101 }], { has_more_before: false, next_before: null })
    response.request = { ...response.request, series_kind: 'actual_dominant' }

    assert.equal(resolveHistoricalPhysicalContract(response, response.bars[0]), undefined)
    assert.equal(mergeInitialPage(response).bars[0].physicalContract, undefined)
  })

  it('fails closed when an actual-dominant bar matches multiple resolved segments', () => {
    const response = page([{ bar_end: '2026-08-07T09:15:00Z', close: 101 }], { has_more_before: false, next_before: null })
    response.request = { ...response.request, series_kind: 'actual_dominant' }
    response.resolved_contract_segments = [
      { contract: 'JM2609', start_trading_day: '2026-08-01', end_trading_day: '2026-08-07' },
      { contract: 'JM2701', start_trading_day: '2026-08-07', end_trading_day: '2026-08-10' },
    ]

    assert.throws(
      () => mergeInitialPage(response),
      (error: unknown) => error instanceof MarketSeriesPhysicalIdentityError
        && error.code === 'MARKET_SERIES_SEGMENT_CONFLICT',
    )
  })

  it('leaves continuous history physically unbound', () => {
    const response = page([{ bar_end: '2026-08-07T09:15:00Z', close: 101 }], { has_more_before: false, next_before: null })

    assert.equal(mergeInitialPage(response).bars[0].physicalContract, undefined)
  })

  it('maps prepend bars from the prepend page identity rather than the current page', () => {
    const currentPage = page([{ bar_end: '2026-08-08T09:15:00Z', close: 102 }], { has_more_before: true, next_before: '2026-08-07T09:15:00Z' })
    currentPage.request = { ...currentPage.request, series_kind: 'actual_dominant' }
    currentPage.resolved_contract_segments = [
      { contract: 'JM2701', start_trading_day: '2026-08-08', end_trading_day: '2026-08-08' },
    ]
    const olderPage = page([{ bar_end: '2026-08-07T09:15:00Z', close: 101 }], { has_more_before: false, next_before: null })
    olderPage.request = { ...olderPage.request, series_kind: 'actual_dominant' }
    olderPage.resolved_contract_segments = [
      { contract: 'JM2609', start_trading_day: '2026-08-07', end_trading_day: '2026-08-07' },
    ]

    const result = prependHistoricalPage(mergeInitialPage(currentPage).bars, olderPage)

    assert.deepEqual(result.bars.map((bar) => bar.physicalContract), ['JM2609', 'JM2701'])
  })

  it('sorts and deduplicates an initial page by formal bar_end', () => {
    const result = mergeInitialPage(page([
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 103 },
    ], { has_more_before: true, next_before: '2026-08-07T09:15:00Z' }))

    assert.deepEqual(result.bars.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:15:00Z', 101],
      ['2026-08-07T09:30:00Z', 103],
    ])
  })

  it('prepends an older page without duplicating an overlapping bar_end', () => {
    const current = mergeInitialPage(page([
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
      { bar_end: '2026-08-07T09:45:00Z', close: 103 },
    ], { has_more_before: true, next_before: '2026-08-07T09:30:00Z' }))

    const result = prependHistoricalPage(current.bars, page([
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
    ], { has_more_before: false, next_before: null }))

    assert.deepEqual(result.bars.map((bar) => bar.time), [
      '2026-08-07T09:15:00Z',
      '2026-08-07T09:30:00Z',
      '2026-08-07T09:45:00Z',
    ])
  })

  it('rejects a page response from an older identity generation', () => {
    assert.equal(isCurrentGeneration(4, 5), false)
    assert.equal(isCurrentGeneration(5, 5), true)
  })

  it('clears the old public series before a replacement identity can fail', async () => {
    let rejectReplacement: ((reason: Error) => void) | undefined
    const series = useMarketSeries({
      fetchPage: (request) => request.symbol === 'ag'
        ? Promise.resolve(page(
            [{ bar_end: '2026-08-07T09:30:00Z', close: 100 }],
            { has_more_before: true, next_before: '2026-08-07T09:30:00Z' },
          ))
        : new Promise((_resolve, reject) => { rejectReplacement = reject }),
      fetchState: async () => state({ live_eligible: false, live_available: false }),
    })
    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '60m' })

    const replacement = series.replaceSeries({ seriesKind: 'contract', symbol: 'jm', contract: 'JM2609', frequency: '60m' })
    assert.deepEqual(series.bars.value, [])
    assert.equal(series.hasMoreBefore.value, false)
    assert.equal(series.canonicalCoverage.value, null)
    rejectReplacement?.(new Error('replacement unavailable'))
    await assert.rejects(replacement, /replacement unavailable/)
    assert.deepEqual(series.bars.value, [])
  })

  it('keeps the API next_before cursor for the earliest formal bar', () => {
    const result = mergeInitialPage(page([
      { bar_end: '2026-08-07T09:15:00Z', close: 101 },
      { bar_end: '2026-08-07T09:30:00Z', close: 102 },
    ], { has_more_before: true, next_before: '2026-08-07T09:15:00Z' }))

    assert.equal(result.nextBefore, '2026-08-07T09:15:00Z')
    assert.equal(result.hasMoreBefore, true)
  })

  it('exposes the queried series canonical coverage instead of a physical contract guess', async () => {
    const series = useMarketSeries({
      fetchPage: async () => page(
        [
          liveBar('2023-01-03T01:01:00Z', 90),
          liveBar('2026-08-10T07:00:00Z', 100),
        ],
        { has_more_before: true, next_before: '2026-08-10T07:00:00Z' },
        { start: '2023-01-03T01:01:00Z', end: '2026-08-10T07:00:00Z' },
      ),
      fetchState: async () => state({
        phase: 'CLOSED',
        live_eligible: false,
        live_available: false,
        after_market: { last_successful_trading_day: '2026-08-07' },
      }),
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })

    assert.deepEqual(series.canonicalCoverage.value, {
      start: '2023-01-03T01:01:00Z',
      end: '2026-08-10T07:00:00Z',
    })
  })

  it('merges an older page into the full loaded canonical coverage', async () => {
    let calls = 0
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? page(
            [
              liveBar('2026-06-24T18:30:00Z', 100),
              liveBar('2026-08-10T07:00:00Z', 101),
            ],
            { has_more_before: true, next_before: '2026-06-24T18:30:00Z' },
            { start: '2026-06-24T18:30:00Z', end: '2026-08-10T07:00:00Z' },
          )
          : page(
            [
              liveBar('2026-05-07T18:16:00Z', 98),
              liveBar('2026-06-24T18:30:00Z', 100),
            ],
            { has_more_before: true, next_before: '2026-05-07T18:16:00Z' },
            { start: '2026-05-07T18:16:00Z', end: '2026-06-24T18:30:00Z' },
          )
      },
      fetchState: async () => state({
        phase: 'CLOSED',
        live_eligible: false,
        live_available: false,
        after_market: { last_successful_trading_day: '2026-08-07' },
      }),
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    await series.loadMoreBefore()

    assert.deepEqual(series.canonicalCoverage.value, {
      start: '2026-05-07T18:16:00Z',
      end: '2026-08-10T07:00:00Z',
    })
  })
})

function state(overrides: Partial<MarketReadState> = {}): MarketReadState {
  return {
    symbol: 'ag',
    series_kind: 'actual_dominant',
    frequency: '15m',
    operational: true,
    phase: 'TRADING',
    trading_day: '2026-08-07',
    live_eligible: true,
    live_available: true,
    live_contract: 'AG2601',
    canonical_end: '2026-08-07T09:30:00Z',
    after_market: {},
    ...overrides,
  }
}

class FakeSocket {
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  readonly url: string

  constructor(url: string) {
    this.url = url
  }

  close() {
    this.closed = true
  }

  message(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  disconnect() {
    this.onclose?.()
  }
}

function liveBar(bar_end: string, close: number) {
  return {
    bar_end,
    trading_day: bar_end.slice(0, 10),
    open: close - 1,
    high: close + 1,
    low: close - 2,
    close,
    volume: 10,
    turnover: null,
    open_interest: null,
  }
}

describe('market Live overlay', () => {
  it('binds snapshot bars to the snapshot physical contract', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: ' ag2601 ', bars: [
      liveBar('2026-08-07T09:45:00Z', 101),
    ] })

    assert.equal(series.bars.value[series.bars.value.length - 1]?.physicalContract, 'AG2601')
  })

  it('fails closed when a contract snapshot identity differs from the requested contract', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state({ series_kind: 'contract' }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'contract', symbol: 'ag', contract: 'AG2601', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2605', bars: [
      liveBar('2026-08-07T09:45:00Z', 101),
    ] })

    assert.equal(series.liveUnavailable.value, true)
    assert.deepEqual(series.bars.value.map((bar) => bar.close), [100])
  })

  it('accepts the snapshot physical contract for actual-dominant overlays', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2605', bars: [
      liveBar('2026-08-07T09:45:00Z', 101),
    ] })

    assert.equal(series.bars.value[series.bars.value.length - 1]?.physicalContract, 'AG2605')
  })

  it('reuses the established snapshot identity for ordinary bars', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state({ live_contract: 'AG9999' }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2601', bars: [] })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })

    assert.equal(series.bars.value[series.bars.value.length - 1]?.physicalContract, 'AG2601')
  })

  it('does not guess a physical contract for an ordinary bar before any snapshot identity', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state({ live_contract: 'AG9999' }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })

    assert.equal(series.bars.value[series.bars.value.length - 1]?.physicalContract, undefined)
  })

  it('clears the overlay identity on reset before the next ordinary bar', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2601', bars: [] })
    sockets[0].message({ type: 'reset', trading_day: '2026-08-08', contract: 'AG2605' })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })

    assert.equal(series.bars.value[series.bars.value.length - 1]?.physicalContract, undefined)
  })

  it('replaces the overlay identity when a snapshot changes physical contract', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2601', bars: [
      liveBar('2026-08-07T09:45:00Z', 101),
    ] })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-08', contract: 'AG2605', bars: [
      liveBar('2026-08-08T09:45:00Z', 102),
    ] })

    assert.deepEqual(series.bars.value.map((bar) => [bar.close, bar.physicalContract]), [
      [100, undefined],
      [102, 'AG2605'],
    ])
  })

  it('merges only snapshot bars strictly after the canonical seam and replaces duplicate live ends', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2601', bars: [
      liveBar('2026-08-07T09:30:00Z', 999),
      liveBar('2026-08-07T09:45:00Z', 101),
    ] })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 102) })

    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:30:00Z', 100],
      ['2026-08-07T09:45:00Z', 102],
    ])
  })

  it('drops the transient overlay on a websocket reset while retaining canonical history', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })
    sockets[0].message({ type: 'reset', trading_day: '2026-08-10', contract: 'AG2610' })

    assert.deepEqual(series.bars.value.map((bar) => bar.close), [100])
  })

  it('ignores late REST and websocket messages from a replaced series generation', async () => {
    let resolveAgOlder: ((value: MarketBarsPageResponse) => void) | undefined
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: (request) => {
        if (request.symbol !== 'ag') {
          return Promise.resolve(page([liveBar('2026-08-07T09:30:00Z', 200)], { has_more_before: false, next_before: null }))
        }
        if (request.before) {
          return new Promise<MarketBarsPageResponse>((resolve) => { resolveAgOlder = resolve })
        }
        return Promise.resolve(page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: true, next_before: '2026-08-07T09:30:00Z' }))
      },
      fetchState: async (request) => state({ symbol: request.symbol, live_contract: `${request.symbol.toUpperCase()}2601` }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    const olderAg = series.loadMoreBefore()
    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' })
    resolveAgOlder?.(page([liveBar('2026-08-07T09:15:00Z', 99)], { has_more_before: false, next_before: null }))
    await olderAg
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })

    assert.deepEqual(series.bars.value.map((bar) => bar.close), [200])
  })

  it('retains history after a socket disconnect and reconnects with its newest live bar', async () => {
    const sockets: FakeSocket[] = []
    const scheduled: Array<() => void> = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
      scheduleReconnect: (callback) => {
        scheduled.push(callback)
        return scheduled.length
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })
    sockets[0].disconnect()
    assert.equal(series.liveUnavailable.value, true)
    assert.equal(series.bars.value.length, 2)
    scheduled[0]()

    assert.match(sockets[1].url, /after=2026-08-07T09%3A45%3A00Z/)
    sockets[1].message({ type: 'bar', bar: liveBar('2026-08-07T10:00:00Z', 102) })
    assert.equal(series.liveUnavailable.value, false)
  })

  it('keeps CLOSED and BREAK phases historical-safe without treating quiet bars as an error or reconnect', async () => {
    const sockets: FakeSocket[] = []
    const scheduled: Array<() => void> = []
    const make = async (phase: string, eligible: boolean) => {
      const series = useMarketSeries({
        fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
        fetchState: async () => state({
          phase,
          live_eligible: eligible,
          live_available: eligible,
          after_market: phase === 'CLOSED'
            ? { last_successful_trading_day: '2026-08-07' }
            : {},
        }),
        createWebSocket: (url: string) => {
          const socket = new FakeSocket(url)
          sockets.push(socket)
          return socket
        },
        scheduleReconnect: (callback) => {
          scheduled.push(callback)
          return scheduled.length
        },
      })
      await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
      return series
    }

    const closed = await make('CLOSED', false)
    const breaking = await make('BREAK', true)
    assert.equal(closed.liveUnavailable.value, false)
    assert.equal(breaking.liveUnavailable.value, false)
    assert.equal(sockets.length, 1)
    assert.equal(scheduled.length, 0)
  })

  it('waits for the after-market canonical seam when opened after close', async () => {
    let calls = 0
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? page([liveBar('2026-08-07T07:00:00Z', 100)], { has_more_before: false, next_before: null })
          : page([
            liveBar('2026-08-07T07:00:00Z', 100),
            liveBar('2026-08-10T07:00:00Z', 101),
          ], { has_more_before: false, next_before: null })
      },
      fetchState: async () => state({
        phase: 'CLOSED',
        trading_day: '2026-08-10',
        live_eligible: false,
        live_available: false,
        canonical_end: '2026-08-07T07:00:00Z',
        after_market: { last_successful_trading_day: null },
      }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })

    assert.equal(sockets.length, 1)
    sockets[0].message({ type: 'state', state: state({
      phase: 'CLOSED',
      trading_day: '2026-08-10',
      live_eligible: false,
      live_available: false,
      canonical_end: '2026-08-10T07:00:00Z',
      after_market: { last_successful_trading_day: null },
    }) })
    await new Promise<void>((resolve) => setImmediate(resolve))

    assert.equal(sockets[0].closed, true)
    assert.equal(calls, 2)
    assert.deepEqual(series.bars.value.map((bar) => bar.time), [
      '2026-08-07T07:00:00Z',
      '2026-08-10T07:00:00Z',
    ])
  })

  it('restores a post-close display snapshot without treating it as realtime Live', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([
        liveBar('2026-08-10T07:00:00Z', 100),
      ], { has_more_before: false, next_before: null }),
      fetchState: async () => state({
        phase: 'CLOSED',
        trading_day: '2026-08-10',
        live_eligible: false,
        live_available: false,
        canonical_end: '2026-08-10T07:00:00Z',
        after_market: { last_successful_trading_day: null },
      }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({
      type: 'snapshot',
      source: 'post_close',
      trading_day: '2026-08-10',
      contract: 'AG2601',
      bars: [liveBar('2026-08-10T07:15:00Z', 101)],
    })

    assert.equal(series.overlaySource.value, 'post_close')
    assert.deepEqual(series.bars.value.map((bar) => bar.time), [
      '2026-08-10T07:00:00Z',
      '2026-08-10T07:15:00Z',
    ])
    assert.equal(series.marketState.value?.live_eligible, false)
  })

  it('opens the post-close handoff for an explicitly requested real contract', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([
        liveBar('2026-08-10T07:00:00Z', 100),
      ], { has_more_before: false, next_before: null }),
      fetchState: async () => state({
        series_kind: 'contract',
        phase: 'CLOSED',
        trading_day: '2026-08-10',
        live_eligible: false,
        live_available: false,
        live_contract: null,
        canonical_end: '2026-08-10T07:00:00Z',
        after_market: { last_successful_trading_day: null },
      }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({
      seriesKind: 'contract',
      symbol: 'ag',
      contract: 'AG2601',
      frequency: '15m',
    })

    assert.equal(sockets.length, 1)
    assert.match(sockets[0].url, /series_kind=contract/)
    assert.match(sockets[0].url, /contract=AG2601/)
  })

  it('preserves an empty post-close reconnect but clears an explicit none source', async () => {
    const sockets: FakeSocket[] = []
    const scheduled: Array<() => void> = []
    const series = useMarketSeries({
      fetchPage: async () => page([
        liveBar('2026-08-10T07:00:00Z', 100),
      ], { has_more_before: false, next_before: null }),
      fetchState: async () => state({
        phase: 'CLOSED',
        trading_day: '2026-08-10',
        live_eligible: false,
        live_available: false,
        canonical_end: '2026-08-10T07:00:00Z',
        after_market: {
          last_successful_trading_day: null,
          last_failure: { trading_day: '2026-08-10', error_code: 'UPDATE_FAILED' },
        },
      }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
      scheduleReconnect: (callback) => {
        scheduled.push(callback)
        return scheduled.length
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({
      type: 'snapshot',
      source: 'post_close',
      trading_day: '2026-08-10',
      contract: 'AG2601',
      bars: [liveBar('2026-08-10T07:15:00Z', 101)],
    })
    sockets[0].disconnect()
    scheduled[0]()
    sockets[1].message({
      type: 'snapshot',
      source: 'post_close',
      trading_day: '2026-08-10',
      contract: 'AG2601',
      bars: [],
    })

    assert.equal(series.overlaySource.value, 'post_close')
    assert.deepEqual(series.bars.value.map((bar) => bar.time), [
      '2026-08-10T07:00:00Z',
      '2026-08-10T07:15:00Z',
    ])

    sockets[1].message({
      type: 'snapshot',
      source: 'none',
      trading_day: null,
      contract: null,
      bars: [],
    })
    assert.equal(series.overlaySource.value, 'none')
    assert.deepEqual(series.bars.value.map((bar) => bar.time), [
      '2026-08-10T07:00:00Z',
    ])
  })

  it('drops old post-close bars when a reconnect snapshot changes day or contract', async () => {
    for (const replacement of [
      { tradingDay: '2026-08-11', contract: 'AG2601' },
      { tradingDay: '2026-08-10', contract: 'AG2605' },
    ]) {
      const sockets: FakeSocket[] = []
      const scheduled: Array<() => void> = []
      const series = useMarketSeries({
        fetchPage: async () => page([
          liveBar('2026-08-10T07:00:00Z', 100),
        ], { has_more_before: false, next_before: null }),
        fetchState: async () => state({
          phase: 'CLOSED',
          trading_day: '2026-08-10',
          live_eligible: false,
          live_available: false,
          live_contract: null,
          canonical_end: '2026-08-10T07:00:00Z',
          after_market: { last_successful_trading_day: null },
        }),
        createWebSocket: (url: string) => {
          const socket = new FakeSocket(url)
          sockets.push(socket)
          return socket
        },
        scheduleReconnect: (callback) => {
          scheduled.push(callback)
          return scheduled.length
        },
      })

      await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
      sockets[0].message({
        type: 'snapshot',
        source: 'post_close',
        trading_day: '2026-08-10',
        contract: 'AG2601',
        bars: [liveBar('2026-08-10T07:15:00Z', 101)],
      })
      sockets[0].disconnect()
      scheduled[0]()
      sockets[1].message({
        type: 'snapshot',
        source: 'post_close',
        trading_day: replacement.tradingDay,
        contract: replacement.contract,
        bars: [],
      })

      assert.equal(series.overlaySource.value, 'none')
      assert.deepEqual(series.bars.value.map((bar) => bar.time), [
        '2026-08-10T07:00:00Z',
      ])
      series.dispose()
    }
  })

  it('tracks an empty realtime snapshot identity before the first bar arrives', async () => {
    const sockets: FakeSocket[] = []
    const scheduled: Array<() => void> = []
    const series = useMarketSeries({
      fetchPage: async () => page([
        liveBar('2026-08-07T09:30:00Z', 100),
      ], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
      scheduleReconnect: (callback) => {
        scheduled.push(callback)
        return scheduled.length
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({
      type: 'snapshot',
      source: 'realtime',
      trading_day: '2026-08-07',
      contract: 'AG2601',
      bars: [],
    })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 101) })
    sockets[0].disconnect()
    scheduled[0]()
    sockets[1].message({
      type: 'snapshot',
      source: 'realtime',
      trading_day: '2026-08-08',
      contract: 'AG2605',
      bars: [],
    })

    assert.equal(series.overlaySource.value, 'none')
    assert.deepEqual(series.bars.value.map((bar) => bar.time), [
      '2026-08-07T09:30:00Z',
    ])
  })

  it('keeps the canonical page visible when the optional state request is unavailable', async () => {
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => { throw new Error('state unavailable') },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })

    assert.equal(series.bars.value.length, 1)
    assert.equal(series.liveUnavailable.value, true)
  })

  it('does not open a Live socket for continuous, non-rank1 contract, daily, or weekly history', async () => {
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }),
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'continuous', symbol: 'ag', frequency: '15m' })
    await series.replaceSeries({ seriesKind: 'contract', symbol: 'ag', contract: 'AG2509', frequency: '15m' })
    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '1d' })
    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '1w' })

    assert.equal(sockets.length, 0)
  })

  it('replaces a canonical advance and drops now-formal live bars without losing later live bars', async () => {
    let calls = 0
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null })
          : page([
            liveBar('2026-08-07T09:30:00Z', 100),
            liveBar('2026-08-07T09:45:00Z', 101),
          ], { has_more_before: false, next_before: null })
      },
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2601', bars: [
      liveBar('2026-08-07T09:45:00Z', 150),
      liveBar('2026-08-07T10:00:00Z', 160),
    ] })
    sockets[0].message({ type: 'state', state: state({ canonical_end: '2026-08-07T09:45:00Z' }) })
    await Promise.resolve()

    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:30:00Z', 100],
      ['2026-08-07T09:45:00Z', 101],
      ['2026-08-07T10:00:00Z', 160],
    ])
  })

  it('refreshes the canonical edge before closing a socket on after-market CLOSED state', async () => {
    let calls = 0
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null })
          : page([
            liveBar('2026-08-07T09:30:00Z', 100),
            liveBar('2026-08-07T09:45:00Z', 101),
          ], { has_more_before: false, next_before: null })
      },
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'state', state: state({
      phase: 'CLOSED',
      live_available: false,
      canonical_end: '2026-08-07T09:45:00Z',
    }) })
    await new Promise<void>((resolve) => setImmediate(resolve))

    assert.equal(sockets[0].closed, true)
    assert.equal(calls, 2)
    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:30:00Z', 100],
      ['2026-08-07T09:45:00Z', 101],
    ])
  })

  it('keeps the socket open until a CLOSED canonical refresh resolves', async () => {
    let calls = 0
    let resolveRefresh: ((value: MarketBarsPageResponse) => void) | undefined
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        if (calls === 1) {
          return page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null })
        }
        return new Promise<MarketBarsPageResponse>((resolve) => { resolveRefresh = resolve })
      },
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'state', state: state({
      phase: 'CLOSED',
      live_available: false,
      canonical_end: '2026-08-07T09:45:00Z',
    }) })

    assert.equal(sockets[0].closed, false)
    resolveRefresh?.(page([
      liveBar('2026-08-07T09:30:00Z', 100),
      liveBar('2026-08-07T09:45:00Z', 101),
    ], { has_more_before: false, next_before: null }))
    await new Promise<void>((resolve) => setImmediate(resolve))

    assert.equal(sockets[0].closed, true)
  })

  it('drops stale Live bars and handles a failed CLOSED canonical refresh', async () => {
    let calls = 0
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        if (calls === 1) {
          return page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null })
        }
        throw new Error('canonical refresh unavailable')
      },
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 150) })
    sockets[0].message({ type: 'state', state: state({
      phase: 'CLOSED',
      live_available: false,
      canonical_end: '2026-08-07T09:45:00Z',
    }) })
    await Promise.resolve()
    await Promise.resolve()

    assert.equal(sockets[0].closed, true)
    assert.equal(series.liveUnavailable.value, true)
    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:30:00Z', 100],
    ])
  })

  it('retains a post-close snapshot when the announced canonical refresh fails', async () => {
    let calls = 0
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        if (calls === 1) {
          return page([liveBar('2026-08-10T07:00:00Z', 100)], { has_more_before: false, next_before: null })
        }
        throw new Error('canonical refresh unavailable')
      },
      fetchState: async () => state({
        phase: 'CLOSED',
        trading_day: '2026-08-10',
        live_eligible: false,
        live_available: false,
        live_contract: null,
        canonical_end: '2026-08-10T07:00:00Z',
        after_market: { last_successful_trading_day: null },
      }),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({
      type: 'snapshot',
      source: 'post_close',
      trading_day: '2026-08-10',
      contract: 'AG2601',
      bars: [liveBar('2026-08-10T07:15:00Z', 101)],
    })
    sockets[0].message({ type: 'state', state: state({
      phase: 'CLOSED',
      trading_day: '2026-08-10',
      live_eligible: false,
      live_available: false,
      live_contract: null,
      canonical_end: '2026-08-10T07:15:00Z',
      after_market: { last_successful_trading_day: null },
    }) })
    await new Promise<void>((resolve) => setImmediate(resolve))

    assert.equal(series.overlaySource.value, 'post_close')
    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-10T07:00:00Z', 100],
      ['2026-08-10T07:15:00Z', 101],
    ])
  })

  it('drops stale Live bars when an advanced canonical refresh returns an empty page', async () => {
    let calls = 0
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null })
          : page([], { has_more_before: false, next_before: null })
      },
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'bar', bar: liveBar('2026-08-07T09:45:00Z', 150) })
    sockets[0].message({ type: 'state', state: state({
      phase: 'CLOSED',
      live_available: false,
      canonical_end: '2026-08-07T09:45:00Z',
    }) })
    await Promise.resolve()
    await Promise.resolve()

    assert.equal(sockets[0].closed, true)
    assert.equal(series.liveUnavailable.value, true)
    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:30:00Z', 100],
    ])
  })

  it('keeps the newest canonical edge when same-series refresh responses resolve out of order', async () => {
    let pageCalls = 0
    let resolveOlderRefresh: ((value: MarketBarsPageResponse) => void) | undefined
    let resolveNewerRefresh: ((value: MarketBarsPageResponse) => void) | undefined
    const sockets: FakeSocket[] = []
    const series = useMarketSeries({
      fetchPage: () => {
        pageCalls += 1
        if (pageCalls === 1) {
          return Promise.resolve(page([liveBar('2026-08-07T09:30:00Z', 100)], { has_more_before: false, next_before: null }))
        }
        if (pageCalls === 2) {
          return new Promise<MarketBarsPageResponse>((resolve) => { resolveOlderRefresh = resolve })
        }
        return new Promise<MarketBarsPageResponse>((resolve) => { resolveNewerRefresh = resolve })
      },
      fetchState: async () => state(),
      createWebSocket: (url: string) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

    await series.replaceSeries({ seriesKind: 'actual_dominant', symbol: 'ag', frequency: '15m' })
    sockets[0].message({ type: 'snapshot', source: 'realtime', trading_day: '2026-08-07', contract: 'AG2601', bars: [
      liveBar('2026-08-07T09:45:00Z', 150),
      liveBar('2026-08-07T10:00:00Z', 160),
      liveBar('2026-08-07T10:15:00Z', 170),
    ] })
    sockets[0].message({ type: 'state', state: state({ canonical_end: '2026-08-07T09:45:00Z' }) })
    sockets[0].message({ type: 'state', state: state({ canonical_end: '2026-08-07T10:00:00Z' }) })

    resolveNewerRefresh?.(page([
      liveBar('2026-08-07T09:30:00Z', 100),
      liveBar('2026-08-07T09:45:00Z', 101),
      liveBar('2026-08-07T10:00:00Z', 102),
    ], { has_more_before: false, next_before: null }))
    await Promise.resolve()
    resolveOlderRefresh?.(page([
      liveBar('2026-08-07T09:30:00Z', 100),
      liveBar('2026-08-07T09:45:00Z', 101),
    ], { has_more_before: false, next_before: null }))
    await Promise.resolve()

    assert.deepEqual(series.bars.value.map((bar) => [bar.time, bar.close]), [
      ['2026-08-07T09:30:00Z', 100],
      ['2026-08-07T09:45:00Z', 101],
      ['2026-08-07T10:00:00Z', 102],
      ['2026-08-07T10:15:00Z', 170],
    ])
  })
})
