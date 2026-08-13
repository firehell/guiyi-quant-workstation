import { expect, test } from '@playwright/test'

function bar(index) {
  const barEnd = new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString()
  return {
    bar_end: barEnd, trading_day: barEnd.slice(0, 10), open: 99 + index, high: 102 + index,
    low: 98 + index, close: 100 + index, volume: 1_000 + index, turnover: 10_000 + index,
    open_interest: 2_000 + index,
  }
}

function research(oiChange = 0.06) {
  return {
    symbol: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE',
    series_kind: 'actual_dominant', contract: null, as_of: '2026-08-11', current_dominant: 'AG2601',
    dominant_mapping_date: '2026-08-11', daily_trend: 'up', weekly_trend: 'neutral', position20: 0.85,
    distance_to_20d_high: 0.03, distance_to_20d_low: 0.21, volume_ratio20: 1.42,
    oi_change_1d: oiChange, turnover_change_5d: 0.12, atr14_percentile252: 0.76,
    recent_daily: Array.from({ length: 40 }, (_, index) => ({
      ...bar(index), open_interest: oiChange === null ? null : 2_000 + index,
    })),
  }
}

function subing(overrides = {}) {
  const snapshot = (timeframe, barEnd, priceSide = 'above') => ({
    timeframe, bar_end: barEnd, trading_day: '2026-01-12', contract: 'AG2601',
    segment_start_trading_day: '2026-01-12', bar_source: 'live', close: '111.5',
    ema21: '109.5', price_side: priceSide, slope_5_raw: '0.12', slope_10_raw: '0.08',
    slope_5_bps_per_bar: '2.70', slope_10_bps_per_bar: '1.80', macd_dif: '0.7',
    macd_dea: '0.5', macd_histogram: '0.4', macd_cross: 'golden', macd_cross_level: '0.6',
    macd_zero_distance_abs: '0.6', macd_zero_distance_bps: '59.70', volume: '342',
    previous_volume: '100', volume_ratio_prev: '3.42',
  })
  return {
    symbol: 'ag', product_name: '白银', frequency: '5m', actual_contract: 'AG2601',
    dominant_mapping_date: '2026-08-11', segment_start_trading_day: '2026-01-12',
    source_mode: 'canonical_live', live_observation: 'available', live_reason: null,
    macd_policy_id: 'web_macd_legacy_v1', calibration_state: 'pending',
    primary: { status: 'ready', snapshot: snapshot('5m', '2026-01-12T02:25:00Z') },
    companion: { status: 'ready', snapshot: snapshot('15m', '2026-01-12T02:15:00Z') },
    ...overrides,
  }
}

async function mockWorkspace(page, researchResponse, options = {}) {
  const marketRequests = options.marketRequests || []
  const subingRequests = options.subingRequests || []
  const dominantRequests = options.dominantRequests || []
  let dominantResponseIndex = 0
  let subingResponseIndex = 0
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) {
      dominantRequests.push(Object.fromEntries(url.searchParams))
      if (dominantResponseIndex > 0 && options.dominantsRefreshDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.dominantsRefreshDelayMs))
      }
      const responses = options.dominantsResponses || []
      const response = responses[Math.min(dominantResponseIndex, responses.length - 1)]
        || { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-08-11' }] }
      dominantResponseIndex += 1
      return route.fulfill({ json: response })
    }
    if (url.pathname.endsWith('/research/product')) return route.fulfill(researchResponse)
    if (url.pathname.endsWith('/research/subing')) {
      subingRequests.push(Object.fromEntries(url.searchParams))
      if (options.subingDelayMs) await new Promise((resolve) => setTimeout(resolve, options.subingDelayMs))
      const responses = options.subingResponses || []
      const response = responses[Math.min(subingResponseIndex, responses.length - 1)]
        || options.subingResponse
        || subing()
      subingResponseIndex += 1
      return route.fulfill({ json: response })
    }
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: { symbol: 'ag', series_kind: url.searchParams.get('series_kind'), frequency: url.searchParams.get('frequency'), operational: true, phase: options.live ? 'TRADING' : 'CLOSED', trading_day: '2026-08-11', live_eligible: !!options.live, live_available: !!options.live, live_contract: options.live ? 'AG2601' : null, canonical_end: null, after_market: {} } })
    if (url.pathname.endsWith('/bars/page')) {
      const request = Object.fromEntries(url.searchParams)
      marketRequests.push(request)
      return route.fulfill({ json: { request: { series_kind: request.series_kind, symbol: 'ag', contract: request.contract || null, frequency: request.frequency, before: null, limit: 1200 }, bars: options.bars || Array.from({ length: 120 }, (_, index) => bar(index)), canonical_coverage: null, page: options.pageMeta || { has_more_before: false, next_before: null }, resolved_contract_segments: [] } })
    }
    return route.abort()
  })
}

test('SuBing owns the current dominant segment while preserving the user series identity', async ({ page }) => {
  const marketRequests = []
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, { marketRequests, subingRequests })
  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=5m')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  await expect(overlay.getByRole('button')).toHaveText(['无', '苏冰', '火天大有'])
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-12')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', 'ema_21')
  expect(marketRequests.some((request) => request.series_kind === 'contract' && request.contract === 'AG2601')).toBe(true)
  expect(subingRequests).toEqual([{ symbol: 'ag', frequency: '5m' }])
  await expect(page).toHaveURL(/series_kind=continuous/)

  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect.poll(() => marketRequests.at(-1)?.series_kind).toBe('continuous')
  await expect(page).toHaveURL(/series_kind=continuous/)
})

test('SuBing clips old same-contract bars and renders Factor-only research wording', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('109 bars', { exact: true })).toBeVisible()
  await expect(page.getByText('研究参数待冻结', { exact: true })).toBeVisible()
  await expect(page.getByText('苏冰观察', { exact: true })).toBeVisible()
  await expect(page.getByText('当前合约', { exact: true })).toBeVisible()
  await expect(page.getByText('段起始', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('买入')
  await expect(page.locator('body')).not.toContainText('卖出')
  await expect(page.locator('body')).not.toContainText('formal signal')
})

test('SuBing keeps the visible chart empty until the segment snapshot resolves', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, { subingDelayMs: 700 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('0 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '')
  await expect(page.getByText('109 bars', { exact: true })).toBeVisible()
})

test('SuBing keeps unsupported 30m explicit and does not request a snapshot', async ({ page }) => {
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    pageMeta: { has_more_before: true, next_before: '2026-08-01T01:00:00Z' },
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=30m')

  await expect(page.getByText('苏冰 Factor V1 当前周期不可用，仅支持 5m / 15m / 1d', { exact: true })).toBeVisible()
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  await expect(page.getByText('可继续向前加载', { exact: true })).toBeVisible()
  expect(subingRequests).toEqual([])
})

test('SuBing refreshes dominant metadata once before accepting a rollover snapshot', async ({ page }) => {
  const marketRequests = []
  const subingRequests = []
  const dominantRequests = []
  const ag2602 = subing({
    actual_contract: 'AG2602',
    dominant_mapping_date: '2026-08-12',
  })
  await mockWorkspace(page, { json: research() }, {
    marketRequests,
    subingRequests,
    dominantRequests,
    dominantsRefreshDelayMs: 700,
    dominantsResponses: [
      { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-08-11' }] },
      { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2602', dominant_mapping_date: '2026-08-12' }] },
    ],
    subingResponses: [ag2602, ag2602],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(1)
  await expect(page.getByText('0 bars', { exact: true })).toBeVisible()
  await expect.poll(() => dominantRequests.length).toBe(2)
  await expect.poll(() => subingRequests.length).toBe(2)
  await expect.poll(() => marketRequests.at(-1)?.contract).toBe('AG2602')
  await expect(page.getByText('109 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__dominant')).toHaveText('当前主力 AG2602')
  expect(marketRequests[0]?.contract).toBe('AG2601')
  expect(dominantRequests).toHaveLength(2)
})

test('SuBing fails closed after one dominant refresh still mismatches the snapshot', async ({ page }) => {
  const subingRequests = []
  const dominantRequests = []
  const mismatched = subing({
    actual_contract: 'AG2602',
    dominant_mapping_date: '2026-08-12',
  })
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    dominantRequests,
    subingResponses: [mismatched, mismatched],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(2)
  await expect(page.getByText('苏冰 Factor 快照不可用', { exact: true })).toBeVisible()
  await expect(page.getByText('0 bars', { exact: true })).toBeVisible()
  await page.waitForTimeout(700)
  expect(subingRequests).toHaveLength(2)
  expect(dominantRequests).toHaveLength(2)
})

test('SuBing performs exactly one delayed refresh for an older companion at the 5m common boundary', async ({ page }) => {
  const subingRequests = []
  const boundarySnapshot = subing({
    primary: {
      status: 'ready',
      snapshot: {
        ...subing().primary.snapshot,
        bar_end: '2026-01-12T02:30:00Z',
      },
    },
  })
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    subingResponse: boundarySnapshot,
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(2)
  await page.waitForTimeout(900)
  expect(subingRequests).toHaveLength(2)
})

test('SuBing refreshes the snapshot after a completed primary Live bar without exposing old segment rows', async ({ page }) => {
  const subingRequests = []
  let marketSocket
  await page.routeWebSocket('**/api/v1/market/ws**', (socket) => {
    marketSocket = socket
  })
  await mockWorkspace(page, { json: research() }, { subingRequests, live: true })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(1)
  await expect.poll(() => !!marketSocket).toBe(true)
  marketSocket.send(JSON.stringify({
    type: 'bar',
    bar: {
      bar_end: '2026-05-01T07:00:00Z', trading_day: '2026-05-01', open: 219,
      high: 222, low: 218, close: 220, volume: 2_000, turnover: 20_000, open_interest: 3_000,
    },
  }))

  await expect.poll(() => subingRequests.length).toBe(2)
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-12')
})

test('shows one identity-matched research snapshot without crowding desktop Kline', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('趋势 / 位置')).toBeVisible()
  await expect(page.getByText('量与持仓')).toBeVisible()
  await expect(page.getByText('日线方向')).toBeVisible()
  await expect(page.getByText('上行')).toBeVisible()
  await expect(page.getByText('Price / Volume / OI')).toBeVisible()
  await expect(page.locator('.product-workspace__sidebar')).toBeVisible()
})

test('keeps Kline usable when research is unavailable and does not invent missing OI', async ({ page }) => {
  await mockWorkspace(page, { json: research(null) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('109 bars')).toBeVisible()
  await page.getByRole('button', { name: '研究', exact: true }).click()
  await expect(page.getByText('OI 暂无可用数据')).toBeVisible()
})

test('research endpoint failure leaves the Kline readable', async ({ page }) => {
  await mockWorkspace(page, { status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QUERY_WINDOW_EMPTY' } }) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('109 bars')).toBeVisible()
  await page.getByRole('button', { name: '研究', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('研究数据暂不可用', { exact: true })).toBeVisible()
})

test('HTDY stays opt-in and keeps its repainting-risk notice visible in the workspace', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toBeVisible()
})
