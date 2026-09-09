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
function events() { return { status: 'ready', trading_day: '2026-09-02', items: [{ id: 1, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2601', trading_day: '2026-09-02', frequency: '15m', bar_end: '2026-09-02T02:45:00Z', result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null }] } }
function mixedEvents() {
  const value = events()
  value.items.push({ id: 2, rule_code: 'subing_ths_alert_15m_v1', symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-02', frequency: '15m', bar_end: '2026-09-02T02:45:00Z', result_codes: ['sell'], detected_at: '2026-09-02T02:45:02Z', notification_attempted_at: null })
  return value
}

async function mockMarketHomeApi(page, requests, currentEvents = events(), currentOverview = overview(), currentRuntime = runtime()) {
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
    if (new URL(page.url()).pathname === '/market/chart') return route.fallback()
    const allowed = new Set(['/api/v1/market/research/home-overview', '/api/runtime/health', '/api/alerts/current-events'])
    if (route.request().method() !== 'GET' || !allowed.has(url.pathname)) {
      requests.unexpected.push(`${route.request().method()} ${url.pathname}`)
      return route.abort('blockedbyclient')
    }
    requests.push(url.pathname)
    if (url.pathname.endsWith('/market/research/home-overview')) { const value = typeof currentOverview === 'function' ? currentOverview() : currentOverview; return value === null ? route.abort() : route.fulfill({ json: value }) }
    if (url.pathname === '/api/runtime/health') return route.fulfill({ json: typeof currentRuntime === 'function' ? currentRuntime() : currentRuntime })
    return route.fulfill({ json: typeof currentEvents === 'function' ? currentEvents() : currentEvents })
  })
}

async function openObservations(page) {
  const button = page.getByRole('button', { name: /研究观察/ }).first()
  if (await button.getAttribute('aria-expanded') !== 'true') await button.click()
}

function expectHomeReads(requests, count = 1) {
  expect(requests.unexpected).toEqual([])
  expect(requests.pageErrors).toEqual([])
  expect(requests.filter(path => path.endsWith('/home-overview'))).toHaveLength(count)
  expect(requests.filter(path => path === '/api/runtime/health')).toHaveLength(count)
  expect(requests.filter(path => path === '/api/alerts/current-events')).toHaveLength(count)
}

for (const width of [1440, 390]) {
  test(`maintenance v3 and weekly history summary are visible at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const requests = []
    const health = runtime('ok')
    health.components = {
      after_market: { status: 'pending', run_state: 'running', expected_trading_day: '2026-09-02',
        current_run: { scheduled_date: '2026-09-02', started_at: '2026-09-02T10:05:00Z', products: ['jm'],
          attempt: 1, stage: 'reading', current_symbol: 'jm', updated_at: '2026-09-02T10:06:00Z',
          current_partition: { dataset: ['contract', 'jm', 'JM2609', '1m'], year: 2026, month: 9 },
          elapsed_seconds: 64.2, counters: { reading: { completed: 7 }, publishing: { completed: 2 } } } },
      weekly_audit: { status: width === 390 ? 'findings' : 'passed', readonly: true, scope: 'operational_full_history',
        through: '2026-08-28', finding_count: width === 390 ? 2 : 0, updated_at: '2026-08-29T01:02:00Z' },
    }
    await mockMarketHomeApi(page, requests, events(), overview(), health)
    await page.goto('/market')
    await expect(page.getByText(/盘后维护.*读取校验.*7 次操作/)).toBeVisible()
    await expect(page.getByText(/盘后维护.*contract\/JM2609.*1m.*2026-09.*累计 64.2 秒/)).toBeVisible()
    await expect(page.getByText(/盘后维护.*已提交发布 2 次操作/)).toBeVisible()
    await expect(page.getByText(width === 390 ? /每周历史审计.*发现历史问题.*2026-08-28/ : /每周历史审计.*审计通过.*2026-08-28/)).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expectHomeReads(requests)
    await page.screenshot({ path: testInfo.outputPath(`maintenance-${width}.png`), fullPage: true })
  })
}

test('white full-width home uses exactly three reads and keeps observations collapsed until opened', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview(), runtime('ready'))
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.locator('.market-dashboard-page')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(page.locator('.n-layout-sider, .n-layout-header, input, .toolbar')).toHaveCount(0)
  await expect(page.getByText(/非实时行情/).first()).toBeVisible()
  await expect(page.getByText('AG · 火天大有 · 买观察 · 15m')).not.toBeVisible()
  await openObservations(page)
  await expect(page.getByText('AG · 火天大有 · 买观察 · 15m')).toBeVisible()
  expectHomeReads(requests)
  await page.getByText('AG · 火天大有 · 买观察 · 15m').click()
  await expect(page).toHaveURL(/view=htdy.*symbol=ag.*series_kind=actual_dominant.*frequency=15m/)
})

test('mixed immutable Events preserve SuBing route and never request a second home source', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, mixedEvents(), overview(), runtime('ready'))
  await page.goto('/market')
  await openObservations(page)
  await expect(page.getByText('JM · 苏冰预警 · 空头预警 · 15m')).toBeVisible()
  expectHomeReads(requests)
  await page.getByText('JM · 苏冰预警 · 空头预警 · 15m').click()
  await expect(page).toHaveURL(/view=subing.*symbol=jm.*series_kind=actual_dominant.*frequency=15m.*focus_bar_end=2026-09-02T02:45:00Z/)
})

test('distinguishes empty and unavailable observations even when panel starts collapsed', async ({ page }) => {
  let current = { status: 'ready', trading_day: '2026-09-02', items: [] }
  const requests = []
  await mockMarketHomeApi(page, requests, () => current)
  await page.goto('/market')
  await openObservations(page)
  await expect(page.getByText('当前交易日暂无正式研究观察 Event')).toBeVisible()
  current = { status: 'unavailable', trading_day: null, items: [] }
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText(/当前 Alert Event 暂不可用/)).toBeVisible()
  await expect(page.getByText('当前交易日暂无正式研究观察 Event')).toHaveCount(0)
})

test('renders the five states and soft percentage badges without inventing targets', async ({ page }) => {
  const requests = []
  const value = allTableStatesOverview()
  value.items[0].oi_change_1d = '0.0218'
  await mockMarketHomeApi(page, requests, events(), value, runtime('ready'))
  await page.goto('/market')
  for (const state of ['up', 'down', 'neutral', 'aligned', 'unavailable']) {
    await expect(page.getByTestId(`market-state-icon-${state}-table`).first()).toHaveCSS('width', '28px')
    await expect(page.getByTestId(`market-state-icon-${state}-legend`).first()).toHaveCSS('width', '28px')
  }
  await expect(page.getByTestId('market-state-icon-neutral-table').first()).toHaveCSS('background-color', 'rgb(54, 90, 245)')
  await expect(page.getByTestId('market-state-icon-up-micro').first()).toHaveCSS('border-radius', '50%')
  await expect(page.getByRole('columnheader', { name: /目标参考价/ })).not.toContainText('↕')
  await expect(page.getByRole('columnheader', { name: /目标参考价/ }).getByRole('button')).toHaveCount(0)
  const targets = page.locator('td.target-unavailable')
  await expect(targets).toHaveCount(5)
  expect(await targets.allTextContents()).toEqual(Array(5).fill('—'))
  await expect(page.getByText('+2.18%', { exact: true })).toBeVisible()
  const badge = page.locator('tbody tr').first().locator('.change-badge')
  await expect(badge).toHaveCSS('border-radius', '7px')
  await expect(badge).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
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
  for (const [label, field] of [['最新收盘', 'close'], ['1d 涨跌幅', 'price_change_1d'], ['量比', 'volume_ratio20'], ['1d 增仓率', 'oi_change_1d']]) {
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
  await expect(page.getByText('涨跌不可用 1', { exact: true })).toBeVisible()
  await expect(page.locator('tbody tr[data-symbol="rs"] .change-badge')).toHaveText('—')
  for (const label of ['牛哇', '火天大有', '苏冰预警', '更多']) {
    const menu = page.locator('.market-home-header details').filter({ has: page.locator('summary', { hasText: label }) })
    await menu.locator('summary').click()
    await expect(menu.getByRole('button', { name: new RegExp(rs.product_name) })).toBeVisible()
  }
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
  await expect(page).toHaveURL(/view=newow.*symbol=ag.*strategy=trend.*series_kind=actual_dominant.*frequency=1d/)
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
  await page.locator('tbody tr[data-symbol="ag"]').click()
  await expect(page).toHaveURL(/view=newow.*symbol=ag/)
  await expect(page.locator('.market-dashboard-page')).toHaveCount(0)
  await detailDirectoryReady
  await expect(page.locator('[data-detail-workspace="newow"]')).toBeVisible()
  requests.length = 0
  await page.goBack()
  await expect(page.locator('tbody tr')).toHaveCount(4)
  await expect(page.getByRole('columnheader', { name: /最新收盘/ })).toHaveAttribute('aria-sort', 'descending')
  expectHomeReads(requests)
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

test('header view menus require an explicit available product and produce exact view routes', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests, events(), overview())
  for (const [label, view, frequency] of [['牛哇', 'newow', '1d'], ['火天大有', 'htdy', '1d'], ['苏冰预警', 'subing', '15m'], ['更多', 'free', '1d']]) {
    requests.length = 0
    await page.goto('/market')
    await expect(page.locator('tbody tr')).toHaveCount(2)
    const menu = page.locator('.market-home-header details').filter({ has: page.locator('summary', { hasText: label }) })
    await menu.locator('summary').click()
    const choice = menu.getByRole('button', { name: /白银/ })
    await expect(choice).toBeVisible()
    expectHomeReads(requests)
    await choice.click()
    await expect(page).toHaveURL(/\/market\/chart\?/)
    const url = new URL(page.url())
    expect(url.pathname).toBe('/market/chart')
    expect(url.searchParams.get('view')).toBe(view)
    expect(url.searchParams.get('symbol')).toBe('ag')
    expect(url.searchParams.get('frequency')).toBe(frequency)
    expect(url.searchParams.get('series_kind')).toBe('actual_dominant')
  }
  expect(requests.unexpected).toEqual([])
})

test('cached and server stale overview facts stay gray and expose their own failure', async ({ page }) => {
  let attempts = 0
  const requests = []
  await mockMarketHomeApi(page, requests, events(), () => ++attempts === 1 ? degradedStaleOverview() : null)
  await page.goto('/market')
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('tbody .market-state-icon--up')).toHaveCount(0)
  await expect(page.getByText(/过期|stale/).first()).toBeVisible()
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
  await expect(page.getByText(/可用\s*—\s*\/\s*—/)).toBeVisible()
  const menu = page.locator('.market-home-header details').filter({ has: page.locator('summary', { hasText: '牛哇' }) })
  await menu.locator('summary').click()
  await expect(menu.getByRole('button')).toHaveCount(0)
  expectHomeReads(requests)
})

test('an unavailable refreshed Event snapshot never leaves old observations clickable', async ({ page }) => {
  let attempt = 0
  const requests = []
  await mockMarketHomeApi(page, requests, () => ++attempt === 1 ? events() : { status: 'unavailable', trading_day: null, items: [] })
  await page.goto('/market')
  await openObservations(page)
  await expect(page.getByText('AG · 火天大有 · 买观察 · 15m')).toBeVisible()
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText(/当前 Alert Event 暂不可用/)).toBeVisible()
  await expect(page.getByText('AG · 火天大有 · 买观察 · 15m')).toHaveCount(0)
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

test('390px compatibility retains readable observations and product entry without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const requests = []
  await mockMarketHomeApi(page, requests, { status: 'unavailable', trading_day: null, items: [] })
  await page.goto('/market')
  const list = page.getByLabel('移动端品种列表')
  await expect(list).toContainText('Event 不可用')
  await openObservations(page)
  await expect(page.getByText(/当前 Alert Event 暂不可用/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(list).toHaveScreenshot('market-home-390-list.png', { animations: 'disabled', maxDiffPixels: 400 })
  await expect(page).toHaveScreenshot('market-home-390.png', { fullPage: true, animations: 'disabled', maxDiffPixels: 400 })
  await list.getByRole('button').first().click()
  await expect(page).toHaveURL(/view=newow.*symbol=ag/)
})
