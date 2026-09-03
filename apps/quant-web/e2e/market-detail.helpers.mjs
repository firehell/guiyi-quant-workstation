export function detailResearch(symbol) {
  const upper = symbol.toUpperCase()
  return {
    symbol,
    product_name: symbol === 'jm' ? '焦煤' : '螺纹钢',
    sector: '黑色',
    exchange: symbol === 'jm' ? 'DCE' : 'SHFE',
    series_kind: 'actual_dominant',
    contract: null,
    as_of: '2026-09-03T02:45:00Z',
    current_dominant: `${upper}2601`,
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

export function detailBar(symbol, index, close = 100 + index) {
  const time = new Date(Date.UTC(2026, 8, 3, 2, 30 + index * 15)).toISOString()
  return {
    bar_end: time,
    trading_day: '2026-09-03',
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 1_000 + index,
    turnover: 10_000 + index,
    open_interest: 2_000 + index,
    physical_contract: `${symbol.toUpperCase()}2601`,
  }
}

export async function mockMarketDetail(page, options = {}) {
  const requests = []
  const delays = options.researchDelayMs || {}
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    const symbol = url.searchParams.get('symbol') || options.defaultSymbol || 'jm'
    const upper = symbol.toUpperCase()

    if (url.pathname.endsWith('/dominants')) {
      return route.fulfill({ json: { items: [
        { product: 'jm', product_name: '焦煤', sector: '黑色', exchange: 'DCE', actual_contract: 'JM2601', dominant_mapping_date: '2026-09-03' },
        { product: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', actual_contract: 'RB2601', dominant_mapping_date: '2026-09-03' },
      ] } })
    }
    if (url.pathname.endsWith('/research/product')) {
      if (delays[symbol]) await new Promise((resolve) => setTimeout(resolve, delays[symbol]))
      return route.fulfill({ json: detailResearch(symbol) })
    }
    if (url.pathname.endsWith('/state')) {
      return route.fulfill({ json: {
        symbol,
        series_kind: url.searchParams.get('series_kind'),
        frequency: url.searchParams.get('frequency'),
        operational: true,
        phase: options.live ? 'TRADING' : 'CLOSED',
        trading_day: '2026-09-03',
        live_eligible: Boolean(options.live),
        live_available: Boolean(options.live),
        live_contract: options.live ? `${upper}2601` : null,
        canonical_end: '2026-09-03T02:45:00Z',
        after_market: { last_successful_trading_day: '2026-09-03' },
      } })
    }
    if (url.pathname.endsWith('/bars/page')) {
      const frequency = url.searchParams.get('frequency')
      const seed = symbol === 'jm' ? 100 : 200
      const bars = frequency === '1d' || frequency === '1w'
        ? [
            { ...detailBar(symbol, 0, seed), bar_end: '2026-09-02T07:00:00.000Z', trading_day: '2026-09-02' },
            { ...detailBar(symbol, 1, seed + 1), bar_end: '2026-09-03T07:00:00.000Z', trading_day: '2026-09-03' },
          ]
        : [detailBar(symbol, 0, seed), detailBar(symbol, 1, seed + 1)]
      return route.fulfill({ json: {
        request: {
          series_kind: url.searchParams.get('series_kind'),
          symbol,
          contract: url.searchParams.get('contract'),
          frequency,
          before: url.searchParams.get('before'),
          limit: Number(url.searchParams.get('limit')),
        },
        bars,
        canonical_coverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: url.searchParams.get('series_kind') === 'actual_dominant'
          ? [{ contract: `${upper}2601`, start_trading_day: bars[0].trading_day, end_trading_day: bars.at(-1).trading_day }]
          : [],
      } })
    }
    return route.abort()
  })
  return requests
}

export async function installDetailFakeWebSocket(page) {
  await page.addInitScript(() => {
    const sockets = []
    class DetailFakeWebSocket {
      static OPEN = 1
      static CLOSED = 3
      readyState = DetailFakeWebSocket.OPEN
      onopen = null
      onmessage = null
      onclose = null

      constructor(url) {
        this.url = url
        this.closed = false
        sockets.push(this)
        queueMicrotask(() => this.onopen?.())
      }

      close() {
        this.closed = true
        this.readyState = DetailFakeWebSocket.CLOSED
        this.onclose?.()
      }
    }
    window.WebSocket = DetailFakeWebSocket
    window.__marketDetailSockets = sockets
  })
}

export async function navigateClient(page, path) {
  await page.evaluate((nextPath) => {
    return import('/src/app/router.ts').then(({ router }) => router.push(nextPath))
  }, path)
}
