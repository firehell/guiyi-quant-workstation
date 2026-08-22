import { expect, test } from '@playwright/test'
import {
  cloneSubingLifecycleCase,
  lifecycleChartBars,
  reidentifySubingResponse,
} from '../tests/fixtures/subingLifecycleCases.mjs'

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
    status: 'ready', expected_as_of: '2026-08-15', target_as_of: '2026-08-15', data_as_of: '2026-08-15',
    freshness_state: 'current', freshness_message: '当前完整', active_count: 60, participant_count: 60,
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
  await page.route('**/api/execution-review/event-states**', (route) => {
    const ids = new URL(route.request().url()).searchParams.getAll('event_ids').map(Number)
    return route.fulfill({ json: { items: ids.map((id) => ({
      event_id: id, state: 'pending_decision', decision_id: null, episode_id: null,
    })) } })
  })
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
}

test('Market homepage shows the current formal signals above Radar', async ({ page }) => {
  await mockMarketHomepage(page, {
    status: 'ready',
    trading_day: '2026-08-15',
    items: [
      formalSignal(),
      { ...formalSignal(), id: 18, rule_code: 'htdy_original_15m', display_name: '火天大有' },
    ],
  })
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('苏冰')
  await expect(formal).toContainText('JM 焦煤 · 买入信号')
  await expect(formal).toContainText('JM2609')
  await expect(formal).toContainText('5m · 10:25 确认')
  await expect(formal).toContainText('5m 同向确认')
  await expect(formal).toContainText('火天大有')
  await expect(page.getByText('Market Radar', { exact: true })).toBeVisible()
  expect(await page.locator('[data-testid="market-formal-signals"], .radar-summary').evaluateAll((nodes) => (
    Boolean(nodes[0]?.compareDocumentPosition(nodes[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true)
})

test('formal signal cards do not advertise a container-wide click target', async ({ page }) => {
  await mockMarketHomepage(page, { status: 'ready', trading_day: '2026-08-15', items: [formalSignal()] })
  await page.goto('/market')

  const card = page.getByTestId('market-formal-signals').locator('.market-formal-signals__card')
  await card.hover()
  await expect(card).toHaveCSS('transform', 'none')
  await expect(card.getByRole('button', { name: '记录执行' })).toBeVisible()
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
    const asOf = attempt === 1 ? '2026-08-14' : '2026-08-15'
    return route.fulfill({ json: radar({ expected_as_of: asOf, target_as_of: asOf, data_as_of: asOf }) })
  })
  await page.goto('/market')
  await expect(page.getByText('当前数据日期 2026-08-14', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '刷新 Radar' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Radar 刷新失败' })).toBeVisible()
  await expect(page.getByText('当前数据日期 2026-08-14', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('当前数据日期 2026-08-15', { exact: true })).toBeVisible()
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
  return { ...cloneSubingLifecycleCase('longSetup'), ...overrides }
}

async function mockWorkspace(page, researchResponse, options = {}) {
  const marketRequests = options.marketRequests || []
  const researchRequests = options.researchRequests || []
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
        || { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-01-12' }] }
      dominantResponseIndex += 1
      return route.fulfill({ json: response })
    }
    if (url.pathname.endsWith('/research/product')) {
      researchRequests.push(Object.fromEntries(url.searchParams))
      return route.fulfill(researchResponse)
    }
    if (url.pathname.endsWith('/research/subing')) {
      subingRequests.push(Object.fromEntries(url.searchParams))
      if (options.subingDelayMs) await new Promise((resolve) => setTimeout(resolve, options.subingDelayMs))
      const responses = options.subingResponses || []
      const response = responses[Math.min(subingResponseIndex, responses.length - 1)]
        || options.subingResponse
        || subing()
      subingResponseIndex += 1
      if (response?.__http_status) {
        return route.fulfill({ status: response.__http_status, json: response.json || { detail: 'unavailable' } })
      }
      return route.fulfill({ json: response })
    }
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: { symbol: 'ag', series_kind: url.searchParams.get('series_kind'), frequency: url.searchParams.get('frequency'), operational: true, phase: options.live ? 'TRADING' : 'CLOSED', trading_day: '2026-08-11', live_eligible: !!options.live, live_available: !!options.live, live_contract: options.live ? 'AG2601' : null, canonical_end: null, after_market: {} } })
    if (url.pathname.endsWith('/bars/page')) {
      const request = Object.fromEntries(url.searchParams)
      marketRequests.push(request)
      const bars = options.bars || Array.from({ length: 120 }, (_, index) => bar(index))
      const resolvedContractSegments = options.resolvedContractSegments || (
        request.series_kind === 'actual_dominant' && bars.length > 0
          ? [{
              contract: options.resolvedContract || 'AG2601',
              start_trading_day: bars[0].trading_day,
              end_trading_day: bars.at(-1).trading_day,
            }]
          : []
      )
      return route.fulfill({ json: {
        request: { series_kind: request.series_kind, symbol: 'ag', contract: request.contract || null, frequency: request.frequency, before: null, limit: 1200 },
        bars,
        canonical_coverage: null,
        page: options.pageMeta || { has_more_before: false, next_before: null },
        resolved_contract_segments: resolvedContractSegments,
      } })
    }
    return route.abort()
  })
}

async function mockAlertMarkerSurface(page) {
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/products/ag')) return route.fulfill({ json: { symbol: 'ag', rules: [] } })
    if (url.pathname.endsWith('/current-events')) return route.fulfill({ json: { status: 'ready', trading_day: '2026-01-12', items: [] } })
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [{
      id: 101, rule_code: 'subing_entry_signal_v1', symbol: 'ag', contract: 'AG2601',
      trading_day: '2026-01-12', frequency: '5m', bar_end: '2026-01-12T02:20:00Z',
      result_codes: ['buy'], lower_tf_confirmation: false, detected_at: '2026-01-12T02:20:01Z',
      notification_attempted_at: null,
    }] } })
    return route.abort()
  })
}

test('SuBing keeps the Market display identity separate from current-dominant research', async ({ page }) => {
  const marketRequests = []
  const researchRequests = []
  const subingRequests = []
  await mockWorkspace(page, { json: research() }, { marketRequests, researchRequests, subingRequests })
  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=5m')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  await expect(overlay.getByRole('button')).toHaveText(['无', '苏冰', '火天大有'])
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', 'ema_21')
  await expect(page.getByRole('button', { name: '主连', exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toHaveText('苏冰计算 AG2601')
  expect(marketRequests.some((request) => request.series_kind === 'continuous' && !request.contract)).toBe(true)
  expect(subingRequests).toEqual([{ symbol: 'ag', frequency: '5m' }])
  await expect.poll(() => researchRequests.length).toBe(1)
  expect(researchRequests).toEqual([{ symbol: 'ag', series_kind: 'continuous' }])
  await expect(page).toHaveURL(/series_kind=continuous/)

  const marketRequestCount = marketRequests.length
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await page.waitForTimeout(100)
  expect(marketRequests).toHaveLength(marketRequestCount)
  expect(researchRequests).toHaveLength(1)
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/series_kind=continuous/)
})

test('shared EMA switches persist across SuBing and HTDY while none hides every overlay', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  const ema = page.getByRole('group', { name: 'EMA' })
  const ema10 = ema.getByRole('button', { name: 'EMA10', exact: true })
  const ema60 = ema.getByRole('button', { name: 'EMA60', exact: true })
  const kline = page.locator('.product-workspace__kline')
  const overlay = page.getByRole('group', { name: 'Overlay' })

  await expect(ema10).toHaveAttribute('aria-pressed', 'false')
  await expect(ema60).toHaveAttribute('aria-pressed', 'false')
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_21')
  await ema10.click()
  await ema60.click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
  await overlay.getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_60,htdy')
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', '')
  await expect(ema10).toHaveAttribute('aria-pressed', 'true')
  await expect(ema60).toHaveAttribute('aria-pressed', 'true')
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await page.reload()
  await expect(kline).toHaveAttribute('data-visible-main-indicators', 'ema_10,ema_21,ema_60')
})

test('SuBing keeps the full Market display history and renders the requested primary Signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.locator('.subing-strip')).toContainText('5m · 当前不匹配')
  await expect(page.getByText('苏冰研究明细', { exact: true })).toBeVisible()
  await expect(page.getByText('当前合约', { exact: true })).toBeVisible()
  await expect(page.getByText('段起始', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toHaveText('苏冰计算 AG2601')
  await expect(page.locator('body')).not.toContainText('买入')
  await expect(page.locator('body')).not.toContainText('卖出')
  await expect(page.locator('body')).not.toContainText('formal signal')
  await expect(page.locator('body')).not.toContainText('ZERO_BAND')
})

test('SuBing lifecycle remains an explicitly research-only funnel beside formal V1 wording', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('formalDirectLong'),
  })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.locator('.subing-strip')).toContainText('5m · 买入信号')
  const lifecycle = page.getByTestId('subing-lifecycle-panel')
  await expect(lifecycle).toContainText('Research only')
  await expect(lifecycle).toContainText('研究确认')
  await expect(lifecycle).toContainText('确认进度')
  await expect(lifecycle).toContainText('已研究确认')
  await expect(lifecycle).not.toContainText('3/3')
  await expect(lifecycle).toContainText('最近状态转换')
  await expect(lifecycle).not.toContainText('买入信号')
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('SuBing lifecycle shows a reducer-produced long momentum hold', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('longMomentumHold'),
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('1/3')
  await expect(page.locator('.subing-lifecycle-strip')).toContainText('确认 1/3')
  await expect(page.locator('.subing-research__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 2.0 bps/bar · MACD 金叉')
  await expect(page.locator('.subing-strip')).toContainText('当前不匹配')
})

test('retest confirmation renders its own zero then one bar progress', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    bars: lifecycleChartBars,
    subingResponses: [cloneSubingLifecycleCase('pivotRetest0'), cloneSubingLifecycleCase('pivotRetest1')],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('0/3')
  await expect(page.locator('.subing-lifecycle-strip')).toContainText('确认 0/3')
  const overlay = page.getByRole('group', { name: 'Overlay' })
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('1/3')
  await expect(page.locator('.subing-lifecycle-strip')).toContainText('确认 1/3')
})

test('lifecycle markers keep Alert counts independent and clear stale research snapshots', async ({ page }) => {
  await mockAlertMarkerSurface(page)
  await mockWorkspace(page, { json: research() }, {
    subingDelayMs: 400,
    subingResponses: [cloneSubingLifecycleCase('longSetup'), cloneSubingLifecycleCase('pivotRetestConfirmed'), { __http_status: 503 }],
    bars: lifecycleChartBars,
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  const shell = page.getByTestId('kline-shell')
  const setupPanel = page.getByTestId('subing-lifecycle-panel')
  await expect(setupPanel).toBeVisible()
  await expect(setupPanel).toContainText('准备中')
  await expect(setupPanel).toContainText('—')
  await expect(shell).toHaveAttribute('data-alert-marker-count', '1')
  await expect(shell).toHaveAttribute('data-research-marker-count', '1')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '1')

  const overlay = page.getByRole('group', { name: 'Overlay' })
  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await expect(shell).toHaveAttribute('data-alert-marker-count', '1')
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect.poll(async () => shell.getAttribute('data-research-marker-count')).toBe('2')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '2')
  await expect(shell).toHaveAttribute('data-alert-marker-count', '1')

  await overlay.getByRole('button', { name: '无', exact: true }).click()
  await overlay.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect(shell).toHaveAttribute('data-research-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect(page.getByText('苏冰 Factor 快照不可用；K 线保留当前展示行情', { exact: true })).toBeVisible()
  await expect(shell).toHaveAttribute('data-rendered-research-marker-count', '0')
  await expect(page.getByTestId('subing-lifecycle-panel')).toHaveCount(0)
})

test('SuBing lifecycle renders risk and closed research stages without trade instructions', async ({ page }) => {
  for (const [caseName, expected] of [['shortExitRiskFirst', '退出风险'], ['oppositeContextClosed', '本轮结束']]) {
    const isRisk = caseName === 'shortExitRiskFirst'
    await mockWorkspace(page, { json: research() }, {
      subingResponse: cloneSubingLifecycleCase(caseName),
    })
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
    const lifecycle = page.getByTestId('subing-lifecycle-panel')
    await expect(lifecycle).toContainText(expected)
    await expect(page.locator('.subing-research__factor').filter({ hasText: 'Primary Factor' })).toContainText(isRisk ? 'S5 -2.0 bps/bar' : 'S5 2.0 bps/bar')
    await expect(lifecycle).not.toContainText(/下单|加仓|平仓指令/)
  }
})

test('SuBing daily lifecycle unavailability leaves the existing Factor view readable', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('dailyUnavailable'),
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=1d')

  await expect(page.locator('.subing-strip')).toContainText('苏冰 Factor')
  await expect(page.getByTestId('subing-lifecycle-panel')).toContainText('SUBING_LIFECYCLE_INTRADAY_ONLY')
  await expect(page.getByText('Primary Factor', { exact: true })).toBeVisible()
})

test('SuBing shows a same-boundary companion-only match without replacing the requested primary', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('companionFormalLong5m'),
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
    subingResponse: cloneSubingLifecycleCase('dualFormalLong5m'),
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
    subingResponse: cloneSubingLifecycleCase('dualFormalShort15m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.locator('.subing-strip')).toContainText('15m · 卖出信号 · 低周期确认')
  await expect(page.getByText('15m · 卖出信号', { exact: true })).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: '15m · 卖出信号 · 低周期确认' })).toBeVisible()
})

test('SuBing 15m non-match keeps the requested primary and creates no resolved signal', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    subingResponse: cloneSubingLifecycleCase('noFormalLong15m'),
  })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.locator('.subing-strip')).toContainText('15m · 当前不匹配')
  await expect(page.getByRole('definition').filter({ hasText: '15m · 当前不匹配' })).toBeVisible()
  await expect(page.getByText('Resolved Signal')).toHaveCount(0)
})

test('SuBing keeps Market display bars visible while the segment snapshot resolves', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, { subingDelayMs: 700 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
  await expect(page.locator('.subing-strip')).toContainText('苏冰 Factor 快照加载中')
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
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

  const ema = page.getByRole('group', { name: 'EMA' })
  await ema.getByRole('button', { name: 'EMA10', exact: true }).click()
  await ema.getByRole('button', { name: 'EMA60', exact: true }).click()
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-main-indicators', '')
  expect(subingRequests).toEqual([])
})

test('SuBing refreshes dominant metadata without changing the Market display identity', async ({ page }) => {
  const marketRequests = []
  const subingRequests = []
  const dominantRequests = []
  const ag2602 = reidentifySubingResponse(cloneSubingLifecycleCase('longSetup'), 'AG2602')
  ag2602.dominant_mapping_date = '2026-08-12'
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
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect.poll(() => dominantRequests.length).toBe(2)
  await expect.poll(() => subingRequests.length).toBe(2)
  await expect.poll(() => marketRequests.length).toBeGreaterThanOrEqual(2)
  expect(marketRequests.every((request) => request.series_kind === 'continuous' && !request.contract)).toBe(true)
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.toolbar__subing-basis')).toHaveText('苏冰计算 AG2602')
  await expect(page).toHaveURL(/series_kind=continuous/)
  expect(dominantRequests).toHaveLength(2)
})

test('SuBing fails closed after one dominant refresh still mismatches the snapshot', async ({ page }) => {
  const subingRequests = []
  const dominantRequests = []
  const mismatched = reidentifySubingResponse(cloneSubingLifecycleCase('longSetup'), 'AG2602')
  mismatched.dominant_mapping_date = '2026-08-12'
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    dominantRequests,
    subingResponses: [mismatched, mismatched],
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(2)
  await expect(page.getByText('苏冰 Factor 快照不可用；K 线保留当前展示行情', { exact: true })).toBeVisible()
  await expect(page.getByText('120 bars', { exact: true })).toBeVisible()
  await page.waitForTimeout(700)
  expect(subingRequests).toHaveLength(2)
  expect(dominantRequests).toHaveLength(2)
})

test('SuBing performs exactly one delayed refresh for an older companion at the 5m common boundary', async ({ page }) => {
  const subingRequests = []
  const boundarySnapshot = cloneSubingLifecycleCase('olderCompanionAtBoundary')
  await mockWorkspace(page, { json: research() }, {
    subingRequests,
    subingResponse: boundarySnapshot,
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect.poll(() => subingRequests.length).toBe(2)
  await page.waitForTimeout(900)
  expect(subingRequests).toHaveLength(2)
})

test('SuBing refreshes the snapshot after a completed primary Live bar without clipping display history', async ({ page }) => {
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
  await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-visible-start-trading-day', '2026-01-01')
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
  await expect(page.getByText('120 bars')).toBeVisible()
  await page.getByRole('button', { name: '研究', exact: true }).click()
  await expect(page.getByText('OI 暂无可用数据')).toBeVisible()
})

test('research endpoint failure leaves the Kline readable', async ({ page }) => {
  await mockWorkspace(page, { status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QUERY_WINDOW_EMPTY' } }) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  await expect(page.locator('.product-workspace__sidebar').getByText('研究数据暂不可用', { exact: true })).toBeVisible()
})

test('HTDY stays opt-in and uses an in-chart legend without the redundant risk banner', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('htdy-chart-legend')).toHaveCount(0)
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  const legend = page.getByTestId('htdy-chart-legend')
  await expect(legend).toBeVisible()
  await expect(legend.getByText('ZK1 上轨', { exact: true })).toBeVisible()
  await expect(legend.getByText('ZD1 下轨', { exact: true })).toBeVisible()
  await expect(legend.getByText('ZD2 趋势', { exact: true })).toBeVisible()

  const shellBox = await page.getByTestId('kline-shell').boundingBox()
  expect(shellBox).not.toBeNull()
  await page.mouse.move(shellBox.x + 240, shellBox.y + 220)
  const hoverLegend = page.locator('.kline-hover-legend')
  await expect(hoverLegend).toBeVisible()
  const hoverBox = await hoverLegend.boundingBox()
  const legendBox = await legend.boundingBox()
  expect(hoverBox).not.toBeNull()
  expect(legendBox).not.toBeNull()
  expect(legendBox.y).toBeGreaterThanOrEqual(hoverBox.y + hoverBox.height + 4)
})
