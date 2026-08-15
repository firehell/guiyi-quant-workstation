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

function radarItem(overrides = {}) {
  return {
    symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: 0.012,
    price_change_5d: 0.032, volume_ratio20: 1.4, oi_change_1d: 0.021,
    atr14_percentile252: 0.72, position20: 0.84, turnover: 12_000,
    reason_codes: ['price_move_up', 'oi_increase'],
    ...overrides,
  }
}

function sectorSummary(sector, median) {
  return {
    sector, total_count: 1, participant_count: 1, up_count: median > 0 ? 1 : 0,
    down_count: median < 0 ? 1 : 0, median_price_change_1d: median, attention_count: 1,
  }
}

function radar(overrides = {}) {
  return {
    status: 'ready', expected_as_of: '2026-08-15', active_count: 60, participant_count: 60,
    stale: [], unavailable: [],
    summary: { up_count: 20, down_count: 18, volume_expansion_count: 12, oi_increase_count: 9, high_volatility_count: 7 },
    items: [], attention: [], sector_summary: [],
    ...overrides,
  }
}

function formalSignal() {
  return {
    id: 17, rule_code: 'subing_entry_signal_v1', display_name: '苏冰', symbol: 'jm', product_name: '焦煤',
    contract: 'JM2609', trading_day: '2026-08-15', frequency: '5m', bar_end: '2026-08-15T02:25:00Z',
    result_codes: ['buy'], lower_tf_confirmation: true, detected_at: '2026-08-15T02:26:00Z', notification_attempted_at: null,
  }
}

async function mockMarketHomepage(page, currentFormalResponse) {
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({ json: currentFormalResponse }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
}

test('Market homepage shows only current formal signals above Radar', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('苏冰')
  await expect(formal).toContainText('JM 焦煤 · 买入信号')
  await expect(formal).toContainText('JM2609')
  await expect(formal).toContainText('5m · 10:25 确认')
  await expect(formal).toContainText('5m 同向确认')
  await expect(formal).not.toContainText('火天大有')
  await expect(page.getByText('Market Radar', { exact: true })).toBeVisible()
  expect(await page.locator('[data-testid="market-formal-signals"], .radar-summary').evaluateAll((nodes) => (
    Boolean(nodes[0]?.compareDocumentPosition(nodes[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true)
})

test('Market homepage keeps formal decisions ahead of Radar at a 980-like viewport', async ({ page }) => {
  await page.setViewportSize({ width: 979, height: 900 })
  await mockMarketHomepage(page, {
    status: 'ready',
    trading_day: '2026-08-15',
    items: [formalSignal(), { ...formalSignal(), id: 18, symbol: 'ag', product_name: '白银', contract: 'AG2601' }],
  })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('只显示当前交易日的正式信号')
  await expect(page.getByText('值得关注，但尚未形成正式信号', { exact: true })).toBeVisible()
  await expect(formal.locator('.market-formal-signals__card')).toHaveCount(2)
  expect(await formal.locator('.market-formal-signals__card').evaluateAll((cards) => cards[1].getBoundingClientRect().top > cards[0].getBoundingClientRect().top)).toBe(true)
  expect(await page.locator('[data-testid="market-formal-signals"], .market-attention').evaluateAll((nodes) => (
    Boolean(nodes[0]?.compareDocumentPosition(nodes[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true)
})

test('Market homepage caps formal decisions at two columns on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockMarketHomepage(page, {
    status: 'ready',
    trading_day: '2026-08-15',
    items: [
      formalSignal(),
      { ...formalSignal(), id: 18, symbol: 'ag', product_name: '白银', contract: 'AG2601' },
      { ...formalSignal(), id: 19, symbol: 'au', product_name: '黄金', contract: 'AU2610' },
    ],
  })
  await page.goto('/market')

  const cards = page.getByTestId('market-formal-signals').locator('.market-formal-signals__card')
  await expect(cards).toHaveCount(3)
  const tops = await cards.evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().top))
  expect(Math.abs(tops[0] - tops[1])).toBeLessThan(1)
  expect(tops[2]).toBeGreaterThan(tops[1])
})

test('Market homepage keeps lower-timeframe confirmation fixed at 5m for a 15m signal', async ({ page }) => {
  await mockMarketHomepage(page, {
    status: 'ready', trading_day: '2026-08-15', items: [{ ...formalSignal(), frequency: '15m' }],
  })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('买入信号')
  await expect(formal).toContainText('15m')
  await expect(formal).toContainText('5m 同向确认')
  await expect(formal).not.toContainText('15m 同向确认')
})

test('Market homepage distinguishes ready empty formal signals', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [] })
  await page.goto('/market')

  await expect(page.getByTestId('market-formal-signals')).toContainText('当前交易日暂无正式信号')
})

test('Market homepage keeps Radar visible when formal signals are unavailable', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'unavailable', trading_day: null, items: [] })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal.getByText('暂不可用', { exact: true })).toBeVisible()
  await expect(formal).toContainText('正式信号暂不可用')
  await expect(page.getByText('Market Radar', { exact: true })).toBeVisible()
})

test('Market homepage shows Radar skeletons while the initial snapshot is pending', async ({ page }) => {
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
  await page.route('**/api/v1/market/research/radar', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    await route.fulfill({ json: radar() })
  })
  await page.goto('/market')

  await expect(page.getByTestId('market-radar-skeleton')).toBeVisible()
  await expect(page.getByText('Market Radar', { exact: true })).toBeVisible()
  await expect(page.getByTestId('market-radar-skeleton')).toHaveCount(0)
})

test('manual Radar refresh keeps the last snapshot on failure and updates on retry', async ({ page }) => {
  let attempt = 0
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
  await page.route('**/api/v1/market/research/radar', async (route) => {
    attempt += 1
    if (attempt === 2) return route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
    return route.fulfill({ json: radar({ expected_as_of: attempt === 1 ? '2026-08-14' : '2026-08-15' }) })
  })
  await page.goto('/market')
  await expect(page.getByText('2026-08-14 · 60/60', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '刷新 Radar' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Radar 刷新失败' })).toBeVisible()
  await expect(page.getByText('2026-08-14 · 60/60', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('2026-08-15 · 60/60', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'Radar 刷新失败' })).toHaveCount(0)
})

test('sector tabs preserve backend order and combine sector with watchlist filtering', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.workspace.preferences.v1', JSON.stringify({
      version: 1, symbol: null, seriesKind: 'actual_dominant', frequency: '15m',
      researchSidebarOpen: true, watchlist: ['a'],
    }))
  })
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({
    json: { status: 'ready', trading_day: '2026-08-15', items: [] },
  }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar({
    items: [radarItem(), radarItem({ symbol: 'a', product_name: '豆一', sector: 'agriculture', price_change_1d: -0.004 })],
    sector_summary: [sectorSummary('black', 0.008), sectorSummary('agriculture', -0.004)],
  }) }))
  await page.goto('/market')

  const tabs = page.getByRole('tablist', { name: '按板块筛选' }).getByRole('tab')
  await expect(tabs).toHaveText(['黑色系 0.8%', '农产品 -0.4%'])
  await expect(tabs.first()).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.market-detail tbody tr')).toContainText('JM 焦煤')
  await expect(page.locator('.market-detail tbody tr')).not.toContainText('A 豆一')

  await page.getByRole('button', { name: '自选', exact: true }).click()
  await expect(page.locator('.market-detail tbody tr')).toHaveCount(0)
  await tabs.nth(1).click()
  await expect(page.locator('.market-detail tbody tr')).toHaveCount(1)
  await expect(page.locator('.market-detail tbody tr')).toContainText('A 豆一')
  await expect(tabs.nth(1).locator('.market-detail__tab-median')).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
})

test('Market homepage stays inside the three desktop acceptance viewports', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] })
  await page.goto('/market')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const box = await page.getByTestId('market-formal-signals').boundingBox()
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  }
})

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
    macd_policy_id: 'web_macd_legacy_v1', signal_macd_policy_id: 'subing_macd_sma_window_scale2_v1',
    calibration_state: 'accepted', calibration_id: 'subing_intraday_v1',
    primary: { status: 'ready', snapshot: snapshot('5m', '2026-01-12T02:25:00Z') },
    companion: { status: 'ready', snapshot: snapshot('15m', '2026-01-12T02:15:00Z') },
    primary_signal: {
      status: 'not_matched', direction: 'none', trigger_timeframe: '5m',
      lower_tf_confirmation: false, resolution: null,
      conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'fail' }], error_code: null,
    },
    resolved_signal: null,
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

test('SuBing clips old same-contract bars and renders the requested primary Signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('109 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.subing-strip')).toContainText('5m · 当前不匹配')
  await expect(page.getByText('苏冰研究明细', { exact: true })).toBeVisible()
  await expect(page.getByText('当前合约', { exact: true })).toBeVisible()
  await expect(page.getByText('段起始', { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('买入')
  await expect(page.locator('body')).not.toContainText('卖出')
  await expect(page.locator('body')).not.toContainText('formal signal')
  await expect(page.locator('body')).not.toContainText('ZERO_BAND')
})

test('SuBing shows a same-boundary companion-only match without replacing the requested primary', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: subing({
      primary: {
        status: 'ready',
        snapshot: { ...subing().primary.snapshot, bar_end: '2026-01-12T02:30:00Z' },
      },
      companion: {
        status: 'ready',
        snapshot: { ...subing().companion.snapshot, bar_end: '2026-01-12T02:30:00Z' },
      },
      primary_signal: {
        status: 'not_matched', direction: 'none', trigger_timeframe: '5m',
        lower_tf_confirmation: false, resolution: null,
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'fail' }], error_code: null,
      },
      resolved_signal: {
        status: 'matched', direction: 'long', trigger_timeframe: '15m',
        lower_tf_confirmation: false, resolution: null,
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'pass' }], error_code: null,
      },
    }),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.locator('.subing-strip')).toContainText('15m · 买入信号')
  await expect(page.getByRole('definition').filter({ hasText: '5m · 当前不匹配' })).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 买入信号' })).toBeVisible()
})

test('SuBing same-boundary dual match keeps 5m primary and resolves one 15m buy signal', async ({ page }) => {
  const alertRequests = []
  await page.route('**/api/v1/alerts/**', async (route) => {
    alertRequests.push(route.request().url())
    return route.abort()
  })
  await mockWorkspace(page, { json: research() }, {
    subingResponse: subing({
      primary: {
        status: 'ready',
        snapshot: { ...subing().primary.snapshot, bar_end: '2026-01-12T02:30:00Z' },
      },
      companion: {
        status: 'ready',
        snapshot: { ...subing().companion.snapshot, bar_end: '2026-01-12T02:30:00Z' },
      },
      primary_signal: {
        status: 'matched', direction: 'long', trigger_timeframe: '5m',
        lower_tf_confirmation: false, resolution: null,
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'pass' }], error_code: null,
      },
      resolved_signal: {
        status: 'matched', direction: 'long', trigger_timeframe: '15m',
        lower_tf_confirmation: true, resolution: 'higher_timeframe_wins',
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'pass' }], error_code: null,
      },
    }),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.locator('.subing-strip')).toContainText('15m · 买入信号 · 低周期确认')
  await expect(page.getByText('Primary Signal')).toBeVisible()
  await expect(page.getByText('5m · 买入信号', { exact: true })).toBeVisible()
  await expect(page.getByText('Resolved Signal')).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 买入信号 · 低周期确认' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('ZERO_BAND')
  await expect(page.locator('body')).not.toContainText('零轴条件')
  expect(alertRequests).toEqual([])
})

test('SuBing same-boundary 15m request keeps 15m as both primary and resolved signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: subing({
      frequency: '15m',
      primary: {
        status: 'ready',
        snapshot: { ...subing().companion.snapshot, bar_end: '2026-01-12T02:30:00Z' },
      },
      companion: {
        status: 'ready',
        snapshot: { ...subing().primary.snapshot, bar_end: '2026-01-12T02:30:00Z' },
      },
      primary_signal: {
        status: 'matched', direction: 'short', trigger_timeframe: '15m',
        lower_tf_confirmation: false, resolution: null,
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'pass' }], error_code: null,
      },
      resolved_signal: {
        status: 'matched', direction: 'short', trigger_timeframe: '15m',
        lower_tf_confirmation: true, resolution: 'higher_timeframe_wins',
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'pass' }], error_code: null,
      },
    }),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.locator('.subing-strip')).toContainText('15m · 卖出信号 · 低周期确认')
  await expect(page.getByText('15m · 卖出信号', { exact: true })).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 卖出信号 · 低周期确认' })).toBeVisible()
})

test('SuBing 15m non-match keeps the requested primary and creates no resolved signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: subing({
      frequency: '15m',
      primary: {
        status: 'ready',
        snapshot: { ...subing().companion.snapshot, bar_end: '2026-01-12T02:15:00Z' },
      },
      companion: {
        status: 'ready',
        snapshot: { ...subing().primary.snapshot, bar_end: '2026-01-12T02:15:00Z' },
      },
      primary_signal: {
        status: 'not_matched', direction: 'none', trigger_timeframe: '15m',
        lower_tf_confirmation: false, resolution: null,
        conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'fail' }], error_code: null,
      },
      resolved_signal: null,
    }),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.locator('.subing-strip')).toContainText('15m · 当前不匹配')
  await expect(page.getByRole('definition').filter({ hasText: '15m · 当前不匹配' })).toBeVisible()
  await expect(page.getByText('Resolved Signal')).toHaveCount(0)
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

test('research control toggles the inline sidebar instead of opening a duplicate drawer at 1280px', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const sidebar = page.locator('.product-workspace__sidebar')
  const researchControl = page.getByRole('button', { name: '研究', exact: true })
  await expect(sidebar).toBeVisible()
  await researchControl.click()
  await expect(sidebar).toBeHidden()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await researchControl.click()
  await expect(sidebar).toBeVisible()
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
  await expect(page.locator('.product-workspace__sidebar').getByText('研究数据暂不可用', { exact: true })).toBeVisible()
})

test('HTDY stays opt-in and keeps its repainting-risk notice visible in the workspace', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toBeVisible()
})
