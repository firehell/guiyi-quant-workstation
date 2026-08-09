import { expect, test } from '@playwright/test'

function bars(start, count, seed = 100) {
  return Array.from({ length: count }, (_, index) => {
    const barEnd = new Date(start + index * 15 * 60 * 1000).toISOString()
    const close = seed + index
    return {
      bar_end: barEnd,
      trading_day: barEnd.slice(0, 10),
      open: close - 1,
      high: close + 1,
      low: close - 2,
      close,
      volume: 100 + index,
      turnover: null,
      open_interest: null,
    }
  })
}

function state(symbol, overrides = {}) {
  return {
    symbol,
    series_kind: 'actual_dominant',
    frequency: '15m',
    operational: true,
    phase: 'TRADING',
    trading_day: '2026-08-07',
    live_eligible: true,
    live_available: true,
    live_contract: `${symbol.toUpperCase()}2601`,
    canonical_end: '2026-08-07T01:00:00.000Z',
    after_market: {},
    ...overrides,
  }
}

async function installFakeWebSocket(page) {
  await page.addInitScript(() => {
    class FakeWebSocket {
      static sockets = []

      constructor(url) {
        this.url = url
        this.onopen = null
        this.onmessage = null
        this.onclose = null
        this.closed = false
        FakeWebSocket.sockets.push(this)
      }

      close() {
        this.closed = true
      }

      serverSend(payload) {
        this.onmessage?.({ data: JSON.stringify(payload) })
      }
    }

    window.WebSocket = FakeWebSocket
    window.__marketSockets = FakeWebSocket.sockets
  })
}

async function mockMarketApi(page, requests) {
  const initialStart = Date.UTC(2026, 7, 7, 1)
  const initial = bars(initialStart, 1200)
  const older = [...bars(initialStart - 1200 * 15 * 60 * 1000, 1200, 0), initial[0]]
  const formalAdvance = [...initial, bars(initialStart + 1200 * 15 * 60 * 1000, 1, 1300)[0]]

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    if (url.pathname.endsWith('/dominants')) {
      await route.fulfill({ json: { items: [
        { product: 'ag', product_name: '白银', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-08-07' },
        { product: 'jm', product_name: '焦煤', exchange: 'DCE', actual_contract: 'JM2601', dominant_mapping_date: '2026-08-07' },
      ] } })
      return
    }
    if (url.pathname.endsWith('/coverage/canonical')) {
      await route.fulfill({ json: { items: [] } })
      return
    }
    if (url.pathname.endsWith('/state')) {
      const kind = url.searchParams.get('series_kind')
      const frequency = url.searchParams.get('frequency')
      const symbol = url.searchParams.get('symbol') || 'ag'
      const weekend = symbol === 'jm'
      const breaking = kind === 'continuous'
      await route.fulfill({ json: state(symbol, {
        series_kind: kind,
        frequency,
        phase: weekend ? 'CLOSED' : (breaking ? 'BREAK' : 'TRADING'),
        live_eligible: !weekend && !breaking,
        live_available: !weekend && !breaking,
      }) })
      return
    }
    if (url.pathname.endsWith('/bars/page')) {
      const before = url.searchParams.get('before')
      const symbol = url.searchParams.get('symbol') || 'ag'
      const pageBars = before
        ? older
        : (requests.filter((request) => request.pathname.endsWith('/bars/page') && request.searchParams.get('symbol') === symbol).length > 1
            ? formalAdvance
            : initial)
      await route.fulfill({ json: {
        request: {
          series_kind: url.searchParams.get('series_kind'), symbol, contract: null,
          frequency: url.searchParams.get('frequency'), before, limit: 1200,
        },
        bars: pageBars,
        canonical_coverage: null,
        page: before
          ? { has_more_before: false, next_before: null }
          : { has_more_before: true, next_before: initial[0].bar_end },
        resolved_contract_segments: [],
      } })
      return
    }
    await route.abort()
  })
}

test('renders the latest canonical page first, paginates left, and overlays actual-dominant Live bars at the seam', async ({ page }) => {
  const requests = []
  await installFakeWebSocket(page)
  await mockMarketApi(page, requests)

  await page.goto('/market/chart?symbol=ag&contract=AG2601&series_kind=actual_dominant&frequency=15m')

  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(1)
  const first = requests.find((url) => url.pathname.endsWith('/bars/page'))
  expect(first.searchParams.has('before')).toBe(false)
  await expect(page.getByText('1200 bars')).toBeVisible()
  await expect(page.getByText('Live', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__marketSockets.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length)).toBe(1)

  await page.evaluate(() => {
    window.__marketSockets.find((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).serverSend({ type: 'snapshot', bars: [
      { bar_end: '2026-08-19T13:00:00.000Z', trading_day: '2026-08-19', open: 1299, high: 1301, low: 1298, close: 1300, volume: 1, turnover: null, open_interest: null },
      { bar_end: '2026-08-19T13:15:00.000Z', trading_day: '2026-08-19', open: 1300, high: 1302, low: 1299, close: 1301, volume: 1, turnover: null, open_interest: null },
    ] })
  })
  await expect(page.getByText('1202 bars')).toBeVisible()

  const canvas = page.locator('.chart canvas').first()
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + 20, box.y + box.height / 2, { steps: 12 })
  await page.mouse.up()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2, { steps: 12 })
  await page.mouse.up()
  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(2)
  expect(requests.filter((url) => url.pathname.endsWith('/bars/page'))[1].searchParams.get('before')).toBe('2026-08-07T01:00:00.000Z')

  await page.evaluate(() => {
    window.__marketSockets.find((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).serverSend({ type: 'state', state: {
      symbol: 'ag', series_kind: 'actual_dominant', frequency: '15m', operational: true, phase: 'TRADING',
      trading_day: '2026-08-07', live_eligible: true, live_available: true, live_contract: 'AG2601',
      canonical_end: '2026-08-19T13:00:00.000Z', after_market: {},
    } })
  })
  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(3)
  await expect(page.getByText('2402 bars')).toBeVisible()
  expect(requests.every((url) => !(url.searchParams.has('start') && url.searchParams.has('end')))).toBe(true)
})

test('keeps continuous, BREAK, and weekend-closed history readable without Live errors', async ({ page }) => {
  const requests = []
  await installFakeWebSocket(page)
  await mockMarketApi(page, requests)

  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=15m')
  await expect(page.getByText('Historical', { exact: true })).toBeVisible()
  await expect(page.getByText('盘中休市', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__marketSockets.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length)).toBe(0)

  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('Historical', { exact: true })).toBeVisible()
  await expect(page.getByText('已收盘', { exact: true })).toBeVisible()
  await expect(page.locator('.overlay.error')).toHaveCount(0)
})

test('does not leak a stale symbol websocket message after switching the displayed symbol', async ({ page }) => {
  const requests = []
  await installFakeWebSocket(page)
  await mockMarketApi(page, requests)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect.poll(() => page.evaluate(() => window.__marketSockets.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length)).toBe(1)

  await page.locator('.symbol-select').click()
  await page.getByText('JM 焦煤', { exact: true }).click()
  await expect(page.locator('.identity-row strong')).toHaveText('JM 焦煤')
  await expect.poll(() => page.evaluate(() => window.__marketSockets.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length)).toBe(0)
  await page.evaluate(() => {
    window.__marketSockets.find((socket) => socket.url.includes('/api/v1/market/ws')).serverSend({ type: 'bar', bar: {
      bar_end: '2026-08-07T06:00:00.000Z', trading_day: '2026-08-07', open: 1, high: 2, low: 0, close: 999, volume: 1, turnover: null, open_interest: null,
    } })
  })

  await expect(page.getByText('1200 bars')).toBeVisible()
  await expect(page.getByText('999 bars')).toHaveCount(0)
})
