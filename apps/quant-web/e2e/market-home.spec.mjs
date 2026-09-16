import { expect, test } from '@playwright/test'
import { mockMarketDetail, installDetailFakeWebSocket } from './market-detail.helpers.mjs'
import { lightHomeOverview, lightHomeOverviewWithUnavailablePrice } from './fixtures/market-home-light.mjs'

function overview() {
  return {
    status: 'ready', target_as_of: '2026-09-02', data_as_of: '2026-09-02', freshness: 'fresh',
    active_count: 2, participant_count: 2, stale_count: 0, unavailable_count: 0,
    summary: { price_up_count: 1, price_down_count: 1, price_flat_count: 0, price_unavailable_count: 0, daily_up_count: 1, daily_down_count: 1, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 1 },
    items: [item('ag', '白银', 'precious', 'up', 'up'), item('jm', '焦煤', 'black', 'down', 'down')],
    sectors: [{ sector: 'precious', active_count: 1, participant_count: 1, median_price_change_1d: '0.01' }, { sector: 'black', active_count: 1, participant_count: 1, median_price_change_1d: '-0.02' }],
  }
}
function item(symbol, product_name, sector, daily_trend, weekly_trend) {
  return { symbol, product_name, sector, exchange: 'DCE', actual_contract: `${symbol.toUpperCase()}2601`, dominant_mapping_date: '2026-09-02', data_as_of: '2026-09-02', close: '100', price_change_1d: daily_trend === 'up' ? '0.01' : '-0.01', price_change_5d: null, volume_ratio20: '1.2', oi_change_1d: null, atr14_percentile252: null, daily_trend, weekly_trend, reason_codes: [] }
}
function allTableStatesOverview() {
  const value = overview()
  value.items = [
    item('ag', '白银', 'black', 'up', 'up'),
    item('jm', '焦煤', 'black', 'down', 'down'),
    item('au', '黄金', 'black', 'neutral', 'neutral'),
    item('rb', '螺纹钢', 'black', 'unavailable', 'unavailable'),
    item('cu', '沪铜', 'black', 'up', 'down'),
  ]
  value.active_count = value.participant_count = 5
  value.summary = { price_up_count: 2, price_down_count: 3, price_flat_count: 0, price_unavailable_count: 0, daily_up_count: 2, daily_down_count: 1, daily_neutral_count: 1, daily_unavailable_count: 1, aligned_up_count: 1, aligned_down_count: 1 }
  value.sectors = [{ sector: 'black', active_count: 5, participant_count: 5, median_price_change_1d: '0.01' }]
  return value
}
function degradedStaleOverview() {
  const value = overview()
  value.status = 'degraded'
  value.freshness = 'stale'
  value.participant_count = 1
  value.stale_count = 1
  value.summary = { price_up_count: 1, price_down_count: 0, price_flat_count: 0, price_unavailable_count: 0, daily_up_count: 1, daily_down_count: 0, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 0 }
  value.items = [value.items[0]]
  value.sectors = [{ ...value.sectors[0] }, { ...value.sectors[1], participant_count: 0 }]
  return value
}
function runtime(status = 'degraded') { return { status, generated_at: '2026-09-02T01:00:00Z', readonly: true, would_start_services: false, would_enqueue_jobs: false, would_send_notifications: false, components: {} } }
function dailyCapabilities() {
  return {
    schema_version: 'newow_product_capabilities_v2', release_stage: 'daily', open_frequencies: ['1w', '1d'],
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
    open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
    deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
  }
}
function events() { return { status: 'ready', trading_day: '2026-09-02', items: [{ id: 1, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2601', trading_day: '2026-09-02', frequency: '15m', bar_end: '2026-09-02T02:45:00Z', result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null }] } }
function mixedEvents() {
  const value = events()
  value.items.push({ id: 2, rule_code: 'subing_ths_alert_15m_v1', symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-02', frequency: '15m', bar_end: '2026-09-02T02:45:00Z', result_codes: ['sell'], detected_at: '2026-09-02T02:45:02Z', notification_attempted_at: null })
  return value
}
function historyPage(items = mixedEvents().items, nextBefore = null) {
  return { status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items, next_before: nextBefore }
}
function historyEvents(start, count) {
  return Array.from({ length: count }, (_, offset) => {
    const id = start + offset
    const instant = new Date(Date.UTC(2026, 8, 2, 1, 0, id)).toISOString()
    return {
      id, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2601', trading_day: '2026-09-02', frequency: '15m',
      bar_end: instant, result_codes: ['buy'], detected_at: instant, notification_attempted_at: null,
    }
  })
}
function actualHomeScrollTop() {
  const content = document.querySelector('.content--market-home')
  const nested = content?.querySelector('.n-layout-scroll-container')
  const scrolling = [content, nested, document.scrollingElement]
    .find((element) => element && element.scrollHeight > element.clientHeight + 1)
  return scrolling?.scrollTop ?? 0
}
async function emitHomeLive(page, payload) {
  await page.evaluate((value) => {
    const socket = window.__marketDetailSockets.find((item) => new URL(item.url, location.href).pathname === '/api/v1/market/research/home-live/ws')
    if (!socket) throw new Error('home live socket missing')
    socket.onmessage?.({ data: JSON.stringify(value) })
  }, payload)
}
function liveItem(overrides = {}) {
  return { symbol: 'ag', physical_contract: 'AG2601', trading_day: '2026-09-02', bar_end: '2026-09-02T02:31:00Z', price: '112.5', previous_close: '100', price_change: '0.125', source: 'completed_1m', availability: 'live', phase: 'TRADING', reason: null, ...overrides }
}

async function mockMarketHomeApi(page, requests, currentEvents = events(), currentOverview = overview(), currentRuntime = runtime(), currentHistory = historyPage()) {
  requests.pageErrors = []
  page.on('pageerror', error => requests.pageErrors.push(error.message))
  await page.route(url => url.pathname.startsWith('/api/'), route => route.abort('blockedbyclient'))
  await mockMarketDetail(page)
  await installDetailFakeWebSocket(page)
  requests.all = []
  requests.unexpected = []
  page.on('request', (request) => requests.all.push({ method: request.method(), url: new URL(request.url()) }))
  await page.route(url => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    if (route.request().method() !== 'GET') { requests.unexpected.push(route.request().method()); return route.abort('blockedbyclient') }
    if (url.pathname === '/api/v1/market/newow/product-capabilities') {
      requests.push(url.pathname)
      return route.fulfill({ json: dailyCapabilities() })
    }
    if (new URL(page.url()).pathname === '/market/chart') return route.fallback()
    const allowed = new Set(['/api/v1/market/dominants', '/api/v1/market/research/home-overview', '/api/runtime/health', '/api/alerts/current-events', '/api/alerts/history'])
    if (route.request().method() !== 'GET' || !allowed.has(url.pathname)) {
      requests.unexpected.push(`${route.request().method()} ${url.pathname}`)
      return route.abort('blockedbyclient')
    }
    requests.push(url.pathname)
    if (url.pathname === '/api/v1/market/dominants') return route.fulfill({ json: { items: lightHomeOverview().items.map(({ symbol, product_name, actual_contract, dominant_mapping_date }) => ({ product: symbol, product_name, actual_contract, dominant_mapping_date })) } })
    if (url.pathname.endsWith('/market/research/home-overview')) { const value = typeof currentOverview === 'function' ? currentOverview() : currentOverview; return value === null ? route.abort() : route.fulfill({ json: value }) }
    if (url.pathname === '/api/runtime/health') return route.fulfill({ json: typeof currentRuntime === 'function' ? currentRuntime() : currentRuntime })
    if (url.pathname === '/api/alerts/history') {
      requests.push(`history:${url.searchParams.get('rule_code') ?? 'all'}:${url.searchParams.get('symbol') ?? 'all'}:${url.searchParams.get('before') ?? 'first'}`)
      return route.fulfill({ json: typeof currentHistory === 'function' ? currentHistory(url) : currentHistory })
    }
    return route.fulfill({ json: typeof currentEvents === 'function' ? currentEvents() : currentEvents })
  })
}

test('top navigation exposes market, messages, and one keyboard product search', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests)
  await page.goto('/market')
  await expect(page.getByRole('tab', { name: '市场' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: '消息' })).toHaveAttribute('aria-selected', 'false')
  await expect(page.locator('.market-home-header details')).toHaveCount(0)
  const search = page.getByRole('combobox', { name: '搜索60品种' })
  await search.fill('jm')
  await expect(page.getByRole('option', { name: /焦煤.*JM/ })).toBeVisible()
  await search.press('Enter')
  await expect(page).toHaveURL(/view=newow.*symbol=jm.*strategy=trend.*frequency=1w/)
  await expect(page.getByLabel('返回市场', { exact: true })).toBeVisible()
  await expect(page.getByRole('listbox', { name: '搜索60品种' })).toHaveCount(0)
  await search.click()
  await expect(page.getByRole('option', { name: /焦煤.*JM/ })).toBeVisible()
  await search.press('Escape')
  await expect(page.getByRole('listbox', { name: '搜索60品种' })).toHaveCount(0)
})

test('messages use bounded server history filters and immutable event navigation', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests)
  await page.goto('/market')
  await page.getByRole('tab', { name: '消息' }).click()
  await expect(page.getByText('火天大有', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('苏冰预警', { exact: true }).last()).toBeVisible()
  await page.getByRole('button', { name: '苏冰', exact: true }).click()
  await expect.poll(() => requests.filter((value) => String(value).startsWith('history:subing_ths_alert_15m_v1')).length).toBe(1)
  await page.locator('.market-message-filters select').selectOption('jm')
  await expect.poll(() => requests.filter((value) => String(value).startsWith('history:subing_ths_alert_15m_v1:jm')).length).toBe(1)
  await page.getByRole('button', { name: /焦煤.*空头预警/ }).click()
  await expect(page).toHaveURL(/view=subing.*symbol=jm.*focus_bar_end=2026-09-02T02:45:00Z/)
  await page.goBack()
  await expect(page.getByRole('tab', { name: '消息' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', { name: '苏冰', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.market-message-filters select')).toHaveValue('jm')
  await expect(page.getByLabel('开始交易日')).toHaveValue(/\d{4}-\d{2}-\d{2}/)
})

test('messages restore two loaded pages, the next cursor, and the real home scroll position after detail', async ({ page }) => {
  const requests = []
  const currentHistory = (url) => {
    const before = url.searchParams.get('before')
    if (before === 'page-2') return historyPage(historyEvents(25, 24), 'page-3')
    if (before === 'page-3') return historyPage(historyEvents(49, 1), null)
    return historyPage(historyEvents(1, 24), 'page-2')
  }
  await mockMarketHomeApi(page, requests, events(), overview(), runtime(), currentHistory)
  await page.goto('/market')
  await page.getByRole('tab', { name: '消息' }).click()
  const messageButtons = page.locator('.market-message-list > button')
  await expect(messageButtons).toHaveCount(24)
  await page.getByRole('button', { name: '加载更多' }).click()
  await expect(messageButtons).toHaveCount(48)
  const last = messageButtons.last()
  await last.scrollIntoViewIfNeeded()
  const before = await page.evaluate(actualHomeScrollTop)
  expect(before).toBeGreaterThan(500)
  const historyReads = requests.filter((value) => String(value).startsWith('history:')).length
  expect(historyReads).toBe(2)

  await last.click()
  await expect(page).toHaveURL(/\/market\/chart/)
  await page.goBack()
  await expect(messageButtons).toHaveCount(48)
  await expect.poll(() => page.evaluate(actualHomeScrollTop)).toBeGreaterThan(before - 10)
  expect(requests.filter((value) => String(value).startsWith('history:')).length).toBe(historyReads)
  const more = page.getByRole('button', { name: '加载更多' })
  await expect(more).toBeEnabled()
  await more.click()
  await expect(messageButtons).toHaveCount(49)
  expect(requests.filter((value) => String(value).endsWith(':page-3'))).toHaveLength(1)
})

test('one operational socket overlays same-contract 1m price and keeps stale value on disconnect', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests)
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  expect(await page.evaluate(() => window.__marketDetailSockets.filter((item) => new URL(item.url, location.href).pathname === '/api/v1/market/research/home-live/ws').length)).toBe(1)
  await emitHomeLive(page, { type: 'snapshot', schema_version: 1, observed_at: '2026-09-02T02:31:01Z', scope: 'operational', items: [liveItem()] })
  await expect(page.getByText(/分钟行情已连接 · 10:31/)).toBeVisible()
  const row = page.locator('tbody tr[data-symbol="ag"]')
  await expect(row.locator('.close-price')).toContainText('112.5')
  await expect(row.locator('.close-price')).toContainText('1m · 10:31')
  await expect(row.locator('.change-badge')).toHaveText('+12.50%')
  await emitHomeLive(page, { type: 'quote', schema_version: 1, observed_at: '2026-09-02T02:32:01Z', item: liveItem({ bar_end: '2026-09-02T02:30:00Z', price: '99' }) })
  await expect(row.locator('.close-price')).toContainText('112.5')
  await page.evaluate(() => window.__marketDetailSockets.find((item) => new URL(item.url, location.href).pathname === '/api/v1/market/research/home-live/ws').onclose?.())
  await expect(row.locator('.close-price')).toContainText('断线保留')
  await expect(page.getByText(/断线保留最新快照 · 10:31/)).toBeVisible()
})

test('authority reset invalidates the overview identity before applying a new contract price', async ({ page }) => {
  const currentOverview = () => {
    const value = overview()
    return value
  }
  const requests = []
  await mockMarketHomeApi(page, requests, events(), currentOverview)
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await emitHomeLive(page, { type: 'snapshot', schema_version: 1, observed_at: '2026-09-02T02:31:01Z', scope: 'operational', items: [liveItem()] })
  await emitHomeLive(page, { type: 'quote', schema_version: 1, observed_at: '2026-09-02T02:32:01Z', item: liveItem({ bar_end: '2026-09-02T02:32:00Z', price: '113' }) })
  await emitHomeLive(page, { type: 'quote', schema_version: 1, observed_at: '2026-09-02T02:33:01Z', item: liveItem({ bar_end: '2026-09-02T02:33:00Z', price: '114' }) })
  await expect(page.locator('tbody tr[data-symbol="ag"] .close-price')).toContainText('114')
  expect(requests.filter((value) => value.endsWith?.('/home-overview'))).toHaveLength(1)
  await emitHomeLive(page, { type: 'reset', schema_version: 1, observed_at: '2026-09-03T02:31:01Z', reason: 'AUTHORITY_CHANGED', items: [liveItem({ physical_contract: 'AG2701', trading_day: '2026-09-03', price: '120', previous_close: null, price_change: null })] })
  await expect.poll(() => requests.filter((value) => value.endsWith?.('/home-overview')).length).toBe(2)
  const row = page.locator('tbody tr[data-symbol="ag"]')
  await expect(row.locator('.close-price')).toContainText('120')
  await expect(row.locator('.close-price')).toContainText('AG2701')
  await expect(row.locator('.change-badge')).toHaveText('—')
})

function expectHomeReads(requests, overviewCount = 1, runtimeCount = overviewCount) {
  expect(requests.unexpected).toEqual([])
  expect(requests.pageErrors).toEqual([])
  expect(requests.filter(path => path.endsWith('/home-overview'))).toHaveLength(overviewCount)
  expect(requests.filter(path => path === '/api/runtime/health')).toHaveLength(runtimeCount)
  expect(requests.filter(path => path === '/api/alerts/current-events')).toHaveLength(0)
  expect(requests.filter(path => path === '/api/v1/market/newow/product-capabilities')).toHaveLength(Math.max(1, overviewCount))
}

for (const width of [1440, 390]) {
  test(`maintenance and weekly history summaries stay out of home at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const requests = []
    const health = runtime('degraded')
    health.components = {
      after_market: { status: 'degraded', run_state: 'running', expected_trading_day: '2026-09-02',
        current_run: { scheduled_date: '2026-09-02', started_at: '2026-09-02T10:05:00Z', products: ['jm'],
          attempt: 1, stage: 'reading', current_symbol: 'jm', updated_at: '2026-09-02T10:06:00Z',
          current_partition: { dataset: ['contract', 'jm', 'JM2609', '1m'], year: 2026, month: 9 },
          elapsed_seconds: 64.2, counters: { reading: { completed: 7 }, publishing: { completed: 2 } } } },
      weekly_audit: { status: width === 390 ? 'findings' : 'passed', readonly: true, scope: 'operational_full_history',
        through: '2026-08-28', finding_count: width === 390 ? 2 : 0, updated_at: '2026-08-29T01:02:00Z' },
    }
    await mockMarketHomeApi(page, requests, events(), overview(), health)
    await page.goto('/market')
    await expect(page.locator('tbody tr')).toHaveCount(2)
    await expect(page.getByText(/盘后维护.*读取校验.*7 次操作/)).toHaveCount(0)
    await expect(page.getByText(/盘后维护.*contract\/JM2609.*1m.*2026-09.*累计 64.2 秒/)).toHaveCount(0)
    await expect(page.getByText(/盘后维护.*已提交发布 2 次操作/)).toHaveCount(0)
    await expect(page.getByText(/盘后维护.*运行结果待确认/)).toHaveCount(0)
    await expect(page.getByText('Runtime 降级', { exact: true })).toHaveCount(0)
    await expect(page.getByText(width === 390 ? /每周历史审计.*发现历史问题.*2026-08-28/ : /每周历史审计.*审计通过.*2026-08-28/)).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expectHomeReads(requests)
    await page.screenshot({ path: testInfo.outputPath(`maintenance-${width}.png`), fullPage: true })
  })
}

test('white full-width market uses only overview and Runtime reads without a research observation panel', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview(), runtime('ready'))
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.locator('.market-dashboard-page')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(page.locator('.n-layout-sider, .n-layout-header, .toolbar')).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: '搜索60品种' })).toBeVisible()
  await expect(page.getByText(/非实时行情/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /研究观察/ })).toHaveCount(0)
  await expect(page.getByText('AG · 火天大有 · 买观察 · 15m')).toHaveCount(0)
  expectHomeReads(requests)
})

test('mixed immutable Events are isolated to the messages tab', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview(), runtime('ready'), historyPage(mixedEvents().items))
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.getByText(/空头预警/)).toHaveCount(0)
  expectHomeReads(requests)
  await page.getByRole('tab', { name: '消息' }).click()
  await page.getByRole('button', { name: /焦煤.*空头预警/ }).click()
  await expect(page).toHaveURL(/view=subing.*symbol=jm.*series_kind=actual_dominant.*frequency=15m.*focus_bar_end=2026-09-02T02:45:00Z/)
})

test('distinguishes empty message history from an unavailable request', async ({ page }) => {
  let current = historyPage([])
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview(), runtime(), () => current)
  await page.goto('/market')
  await page.getByRole('tab', { name: '消息' }).click()
  await expect(page.getByText('所选日期与筛选下暂无正式 Event。')).toBeVisible()
  current = null
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText(/消息暂不可用/)).toBeVisible()
  await expect(page.getByText('所选日期与筛选下暂无正式 Event。')).toHaveCount(0)
})

test('renders the five states and soft percentage badges without inventing targets', async ({ page }) => {
  const requests = []
  const value = allTableStatesOverview()
  value.items[0].oi_change_1d = '0.0218'
  await mockMarketHomeApi(page, requests, events(), value, runtime('ready'))
  await page.goto('/market')
  for (const state of ['up', 'down', 'neutral', 'mixed', 'aligned', 'unavailable']) {
    await expect(page.getByTestId(`market-state-icon-${state}-table`).first()).toHaveCSS('width', '28px')
    await expect(page.getByTestId(`market-state-icon-${state}-legend`).first()).toHaveCSS('width', '28px')
  }
  await expect(page.getByTestId('market-state-icon-neutral-table').first()).toHaveCSS('background-color', 'rgb(54, 90, 245)')
  await expect(page.getByTestId('market-state-icon-up-micro').first()).toHaveCSS('border-radius', '50%')
  await expect(page.getByRole('columnheader', { name: /目标参考价/ })).toHaveCount(0)
  await expect(page.locator('td.target-unavailable')).toHaveCount(0)
  await expect(page.getByText('+2.18%', { exact: true })).toBeVisible()
  const badge = page.locator('tbody tr').first().locator('.change-badge')
  await expect(badge).toHaveCSS('border-radius', '7px')
  await expect(badge).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
  const alignmentCell = page.locator('tbody tr').first().locator('td').nth(7)
  await expect(alignmentCell).toHaveCSS('text-align', 'center')
  await expect(alignmentCell).toHaveCSS('vertical-align', 'middle')
  const alignmentGroup = alignmentCell.locator('.alignment')
  await expect(alignmentGroup).toHaveCSS('position', 'relative')
  await expect(alignmentGroup).toHaveCSS('width', '40px')
  const alignmentBadge = alignmentGroup.getByTestId('market-state-icon-up-micro')
  await expect(alignmentBadge).toHaveCSS('position', 'absolute')
  await expect(alignmentBadge).toHaveCSS('width', '20px')
  expectHomeReads(requests)
  await expect(page.locator('.table-wrap')).toHaveScreenshot('market-home-five-table-states.png', { animations: 'disabled', maxDiffPixels: 400 })
})

test('column headers sort 60 products in both directions then restore stable source order without requests', async ({ page }) => {
  const requests = []
  const value = lightHomeOverview()
  await mockMarketHomeApi(page, requests, events(), value)
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(60)
  const symbols = () => page.locator('tbody tr').evaluateAll(rows => rows.map(row => row.dataset.symbol))
  for (const [label, field] of [['最新收盘', 'close'], ['涨跌幅', 'price_change_1d'], ['日量比', 'volume_ratio20'], ['日增仓率', 'oi_change_1d']]) {
    const header = page.getByRole('columnheader', { name: new RegExp(label) })
    const button = header.getByRole('button')
    await button.click()
    await expect(header).toHaveAttribute('aria-sort', 'descending')
    const sorted = direction => [...value.items].sort((a, b) => {
      if (a[field] === null || b[field] === null) return a[field] === b[field] ? a.symbol.localeCompare(b.symbol) : a[field] === null ? 1 : -1
      return (Number(a[field]) - Number(b[field])) * direction || a.symbol.localeCompare(b.symbol)
    }).map(row => row.symbol)
    expect(await symbols()).toEqual(sorted(-1))
    await button.press('Space')
    await expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(await symbols()).toEqual(sorted(1))
    await button.press('Enter')
    await expect(header).toHaveAttribute('aria-sort', 'none')
    expect(await symbols()).toEqual(value.items.map(row => row.symbol))
    await expect(page).toHaveURL(/\/market$/)
  }
  expectHomeReads(requests)
})

test('keeps 60 target-day D1 participants visible when RS2609 price change is unavailable', async ({ page }) => {
  const requests = []
  const value = lightHomeOverviewWithUnavailablePrice()
  const rs = value.items.find((item) => item.symbol === 'rs')
  await mockMarketHomeApi(page, requests, events(), value, runtime('ready'))
  await page.goto('/market')

  await expect(page.locator('tbody tr')).toHaveCount(60)
  await expect(page.locator('tbody tr[data-symbol="rs"] .change-badge')).toHaveText('—')
  const search = page.getByRole('combobox', { name: '搜索60品种' })
  await search.fill('rs')
  await expect(page.getByRole('option', { name: new RegExp(`${rs.product_name}.*RS`) })).toBeVisible()
  expectHomeReads(requests)
})

test('sector counts use authority and filtering toggles locally with keyboard row entry', async ({ page }) => {
  const requests = []
  const value = lightHomeOverview()
  await mockMarketHomeApi(page, requests, events(), value)
  await page.goto('/market')
  const precious = page.getByRole('button', { name: /贵金属\s*4/ })
  await precious.click()
  await expect(precious).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('tbody tr')).toHaveCount(4)
  await page.getByRole('columnheader', { name: /最新收盘/ }).getByRole('button').click()
  await precious.click()
  await expect(page.locator('tbody tr')).toHaveCount(60)
  expectHomeReads(requests)
  await page.locator('tbody tr[data-symbol="ag"]').press('Enter')
  await expect(page).toHaveURL(/view=newow.*symbol=ag.*strategy=trend.*series_kind=actual_dominant.*frequency=1w/)
})

test('sort and sector survive refresh and browser back while absent sector recovers to all', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), lightHomeOverview())
  await page.goto('/market')
  await page.getByRole('button', { name: /贵金属\s*4/ }).click()
  await page.getByRole('columnheader', { name: /最新收盘/ }).getByRole('button').click()
  await page.reload()
  await expect(page.locator('tbody tr')).toHaveCount(4)
  await expect(page.getByRole('columnheader', { name: /最新收盘/ })).toHaveAttribute('aria-sort', 'descending')
  expectHomeReads(requests, 2)
  const detailDirectoryReady = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/market/dominants' && response.ok())
  const detailStrategySettled = page.waitForEvent('requestfailed', request => new URL(request.url()).pathname === '/api/v1/market/newow/strategy-detail')
  await page.locator('tbody tr[data-symbol="ag"]').click()
  await expect(page).toHaveURL(/view=newow.*symbol=ag/)
  await expect(page.locator('.market-dashboard-page')).toHaveCount(0)
  await Promise.all([detailDirectoryReady, detailStrategySettled])
  await expect(page.locator('[data-detail-workspace="newow"]')).toBeVisible()
  requests.length = 0
  await page.goBack()
  await expect(page.locator('tbody tr')).toHaveCount(4)
  await expect(page.getByRole('columnheader', { name: /最新收盘/ })).toHaveAttribute('aria-sort', 'descending')
  expectHomeReads(requests, 0, 1)
  await page.evaluate(() => {
    const key = 'guiyi.market-home.preferences.v1'
    const value = JSON.parse(localStorage.getItem(key))
    localStorage.setItem(key, JSON.stringify({ ...value, sector: 'removed-sector' }))
  })
  await page.reload()
  await expect(page.locator('tbody tr')).toHaveCount(60)
  await expect(page.getByRole('button', { name: /全部\s*60/ }).first()).toHaveAttribute('aria-pressed', 'true')
  expect(requests.unexpected).toEqual([])
})

test('restores the actual 60-row layout scroll position immediately after browser back', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), lightHomeOverview())
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(60)
  const last = page.locator('tbody tr').last()
  await last.scrollIntoViewIfNeeded()
  const before = await page.evaluate(() => {
    const content = document.querySelector('.content--market-home')
    const nested = content?.querySelector('.n-layout-scroll-container')
    return Math.max(content?.scrollTop ?? 0, nested?.scrollTop ?? 0, document.scrollingElement?.scrollTop ?? 0)
  })
  expect(before).toBeGreaterThan(500)
  await last.click()
  await expect(page).toHaveURL(/\/market\/chart/)
  requests.length = 0
  await page.goBack()
  await expect(page.locator('tbody tr')).toHaveCount(60)
  await expect.poll(() => page.evaluate(() => {
    const content = document.querySelector('.content--market-home')
    const nested = content?.querySelector('.n-layout-scroll-container')
    return Math.max(content?.scrollTop ?? 0, nested?.scrollTop ?? 0, document.scrollingElement?.scrollTop ?? 0)
  })).toBeGreaterThan(before - 10)
  await expect.poll(() => requests.filter(path => path === '/api/runtime/health').length).toBe(1)
  expectHomeReads(requests, 0, 1)
})

test('invalid and blocked preferences fall back safely without hiding available rows', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview())
  await page.addInitScript(() => { try { localStorage.setItem('guiyi.market-home.preferences.v1', '{invalid') } catch {} })
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.getByRole('columnheader', { name: /最新收盘/ })).toHaveAttribute('aria-sort', 'none')
  await page.addInitScript(() => {
    const getItem = Storage.prototype.getItem
    const setItem = Storage.prototype.setItem
    Storage.prototype.getItem = function (key) {
      if (key === 'guiyi.market-home.preferences.v1') throw new DOMException('blocked', 'SecurityError')
      return getItem.call(this, key)
    }
    Storage.prototype.setItem = function (key, value) {
      if (key === 'guiyi.market-home.preferences.v1') throw new DOMException('blocked', 'SecurityError')
      return setItem.call(this, key, value)
    }
  })
  await page.reload()
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await page.getByRole('columnheader', { name: /最新收盘/ }).getByRole('button').click()
  await expect(page.getByRole('columnheader', { name: /最新收盘/ })).toHaveAttribute('aria-sort', 'descending')
  expectHomeReads(requests, 2)
})

test('header product search opens the safe default Newow route', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview())
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  const search = page.getByRole('combobox', { name: '搜索60品种' })
  await search.fill('白银')
  await page.getByRole('option', { name: /白银.*AG/ }).click()
  await expect(page).toHaveURL(/\/market\/chart\?/)
  const url = new URL(page.url())
  expect(url.pathname).toBe('/market/chart')
  expect(url.searchParams.get('view')).toBe('newow')
  expect(url.searchParams.get('symbol')).toBe('ag')
  expect(url.searchParams.get('frequency')).toBe('1w')
  expect(url.searchParams.get('series_kind')).toBe('actual_dominant')
  expect(requests.unexpected).toEqual([])
})

test('cached and server stale overview facts stay gray and expose their own failure', async ({ page }) => {
  let attempts = 0
  const requests = []
  await mockMarketHomeApi(page, requests, events(), () => ++attempts === 1 ? degradedStaleOverview() : null)
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('tbody .market-state-icon--up')).toHaveCount(0)
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText(/刷新失败.*上一份成功快照/)).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('tbody .market-state-icon--up')).toHaveCount(0)
})

test('initial unavailable snapshot invents no counts and no target or product rows', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), null)
  await page.goto('/market')
  await expect(page.getByText(/没有可展示的上一份成功快照/)).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(0)
  await expect(page.getByText(/可用\s*—\s*\/\s*—/)).toHaveCount(0)
  await page.getByRole('combobox', { name: '搜索60品种' }).focus()
  await expect(page.getByRole('option', { name: /黄金.*AU/ })).toBeVisible()
  await expect(page.getByText('目录加载失败，无法安全切换品种。', { exact: true })).toHaveCount(0)
  expectHomeReads(requests)
})

for (const [width, height] of [[1280, 800], [1440, 900], [1920, 1080], [2560, 1440]]) {
  test(`60-product white home fills ${width}px without overflow and keeps header visible while scrolling`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const requests = []
    await mockMarketHomeApi(page, requests, events(), lightHomeOverview())
    await page.goto('/market')
    await expect(page.locator('tbody tr')).toHaveCount(60)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const table = await page.locator('table').boundingBox()
    expect(table.width).toBeGreaterThan(width * .92)
    await expect(page).toHaveScreenshot(`market-home-${width}.png`, { animations: 'disabled', maxDiffPixels: 500 })
    await page.locator('tbody tr').last().scrollIntoViewIfNeeded()
    await expect(page.locator('tbody tr').last()).toBeInViewport()
    await expect(page.getByRole('columnheader', { name: /最新收盘/ })).toBeInViewport()
    await page.locator('tbody tr').last().focus()
    await expect(page.locator('tbody tr').last()).toHaveCSS('outline-style', 'solid')
    expectHomeReads(requests)
  })
}

test('390px compatibility retains readable market and messages without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const requests = []
  await mockMarketHomeApi(page, requests, { status: 'unavailable', trading_day: null, items: [] })
  await page.goto('/market')
  const list = page.getByLabel('移动端品种列表')
  await expect(list).toContainText('1d 涨跌幅')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(list).toHaveScreenshot('market-home-390-list.png', { animations: 'disabled', maxDiffPixels: 400 })
  await expect(page).toHaveScreenshot('market-home-390.png', { fullPage: true, animations: 'disabled', maxDiffPixels: 400 })
  await page.getByRole('tab', { name: '消息' }).click()
  await expect(page.getByLabel('历史消息')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('tab', { name: '市场' }).click()
  await list.getByRole('button').first().click()
  await expect(page).toHaveURL(/view=newow.*symbol=ag/)
})

for (const state of ['loading', 'failed', 'empty']) {
  test(`product directory remains usable when overview is ${state}`, async ({ page }) => {
    const requests = []
    await mockMarketHomeApi(page, requests)
    let release
    const pending = new Promise(resolve => { release = resolve })
    await page.route('**/market/research/home-overview', async route => {
      if (state === 'loading') await pending
      if (state !== 'empty') return route.abort()
      const value = overview()
      value.status = 'degraded'; value.freshness = 'unavailable'
      value.participant_count = 0; value.unavailable_count = 2; value.items = []
      value.summary = Object.fromEntries(Object.keys(value.summary).map(key => [key, 0]))
      value.sectors = value.sectors.map(item => ({ ...item, participant_count: 0, median_price_change_1d: null }))
      return route.fulfill({ json: value })
    })
    try {
      await page.goto('/market')
      if (state === 'empty') {
        await expect(page.locator('.market-home-empty')).toContainText('暂无可用品种')
        await expect(page.getByText('行情快照暂不可用；没有可展示的上一份成功快照。')).toHaveCount(0)
      }
      const search = page.getByRole('combobox', { name: '搜索60品种' })
      await search.fill('黄金')
      await expect(page.getByRole('option', { name: /黄金.*AU/ })).toBeVisible()
      await search.press('Escape')
      await page.getByRole('tab', { name: '消息' }).click()
      await page.locator('.market-message-filters select').selectOption('au')
      await expect.poll(() => requests.includes('history:all:au:first')).toBe(true)
      await page.locator('.market-message-filters select').selectOption('jm')
      await expect.poll(() => requests.includes('history:all:jm:first')).toBe(true)
      expect(requests.filter(path => path === '/api/v1/market/dominants')).toHaveLength(1)
      expect(requests.unexpected).toEqual([])
      expect(requests.pageErrors).toEqual([])
    } finally { release() }
  })
}


test('directory failure and recovery stay independent from quote rows and retain accepted options', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests)
  let fail = true
  await page.route('**/market/dominants', route => fail ? route.abort() : route.fallback())
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  const search = page.getByRole('combobox', { name: '搜索60品种' })
  await search.fill('黄金')
  await expect(page.getByText('目录加载失败，无法安全切换品种。', { exact: true })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await search.focus()
  await expect(page.getByRole('option', { name: /黄金.*AU/ })).toBeVisible()
  fail = true
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await search.focus()
  await expect(page.getByText('目录刷新失败，已保留上次选项。')).toBeVisible()
  await expect(page.getByRole('option', { name: /黄金.*AU/ })).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(2)
})
