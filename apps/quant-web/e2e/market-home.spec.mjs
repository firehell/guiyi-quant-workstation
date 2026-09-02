import { expect, test } from '@playwright/test'

function overview() {
  return {
    status: 'ready', target_as_of: '2026-09-02', data_as_of: '2026-09-02', freshness: 'fresh',
    active_count: 2, participant_count: 2, stale_count: 0, unavailable_count: 0,
    summary: { price_up_count: 1, price_down_count: 1, price_flat_count: 0, daily_up_count: 1, daily_down_count: 1, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 1 },
    items: [item('ag', '白银', 'precious', 'up', 'up'), item('jm', '焦煤', 'black', 'down', 'down')],
    sectors: [{ sector: 'precious', active_count: 1, participant_count: 1, median_price_change_1d: '0.01' }, { sector: 'black', active_count: 1, participant_count: 1, median_price_change_1d: '-0.02' }],
  }
}
function item(symbol, product_name, sector, daily_trend, weekly_trend) {
  return { symbol, product_name, sector, exchange: 'DCE', actual_contract: `${symbol.toUpperCase()}2601`, dominant_mapping_date: '2026-09-02', data_as_of: '2026-09-02', close: '100', price_change_1d: daily_trend === 'up' ? '0.01' : '-0.01', price_change_5d: null, volume_ratio20: '1.2', oi_change_1d: null, atr14_percentile252: null, daily_trend, weekly_trend, reason_codes: [] }
}
function runtime() { return { status: 'degraded', generated_at: '2026-09-02T01:00:00Z', readonly: true, would_start_services: false, would_enqueue_jobs: false, would_send_notifications: false, components: {} } }
function events() { return { status: 'ready', trading_day: '2026-09-02', items: [{ id: 1, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2601', trading_day: '2026-09-02', frequency: '15m', bar_end: '2026-09-02T02:45:00Z', result_codes: ['buy'], detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null }] } }

async function mockMarketHomeApi(page, requests, currentEvents = events(), currentOverview = overview(), currentRuntime = runtime()) {
  await page.route(/\/api\/(?:v1\/market\/research\/home-overview|runtime\/health|alerts\/current-events)/, async (route) => {
    const url = new URL(route.request().url())
    requests.push(url.pathname)
    if (url.pathname.endsWith('/market/research/home-overview')) { const value = typeof currentOverview === 'function' ? currentOverview() : currentOverview; return value === null ? route.abort() : route.fulfill({ json: value }) }
    if (url.pathname === '/api/runtime/health') return route.fulfill({ json: typeof currentRuntime === 'function' ? currentRuntime() : currentRuntime })
    return route.fulfill({ json: currentEvents })
  })
}

async function expectFrozenIconContracts(page) {
  for (const [state, color] of [['up', 'rgb(230, 57, 53)'], ['aligned', 'rgb(255, 150, 1)'], ['down', 'rgb(53, 199, 89)'], ['neutral', 'rgb(1, 122, 255)'], ['unavailable', 'rgb(152, 162, 179)']]) {
    const icon = page.getByTestId(`market-state-icon-${state}-legend`).first()
    await expect(icon).toHaveCSS('background-color', color)
    await expect(icon).toHaveCSS('width', '40px')
  }
  await expect(page.getByTestId('market-state-icon-up-table').first()).toHaveCSS('width', '28px')
  await expect(page.getByTestId('market-state-icon-up-micro').first()).toHaveCSS('width', '24px')
}

test('uses exactly three top-level reads and opens immutable HTDY actual-dominant chart', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests)
  await page.goto('/market')

  await expect(page.getByText('非实时行情')).toBeVisible()
  await expect(page.getByText('HTDY Focus')).toBeVisible()
  await expect(page.getByText('AG · 买观察 · 15m')).toBeVisible()
  await expect(page.locator('.n-layout-sider__toggle')).toHaveCount(0)
  await expectFrozenIconContracts(page)
  await expect.poll(() => requests.filter((path) => path.endsWith('/home-overview')).length).toBe(1)
  expect(requests.filter((path) => path === '/api/runtime/health')).toHaveLength(1)
  expect(requests.filter((path) => path === '/api/alerts/current-events')).toHaveLength(1)

  await page.getByText('AG · 买观察 · 15m').click()
  await expect(page).toHaveURL(/symbol=ag.*series_kind=actual_dominant.*frequency=15m.*overlay=htdy/)
})

test('distinguishes an empty current Event projection from an unavailable projection', async ({ page }) => {
  const emptyRequests = []
  await mockMarketHomeApi(page, emptyRequests, { status: 'ready', trading_day: '2026-09-02', items: [] })
  await page.goto('/market')
  await expect(page.getByText('当前交易日暂无 HTDY 正式观察 Event')).toBeVisible()

  const unavailableRequests = []
  await mockMarketHomeApi(page, unavailableRequests, { status: 'unavailable', trading_day: null, items: [] })
  await page.reload()
  await expect(page.getByText('HTDY 当前 Event 暂不可用；不能据此判断本时段无观察。')).toBeVisible()
})

test('keeps each accepted viewport free of page-level horizontal overflow', async ({ page }) => {
  const requests = []
  await mockMarketHomeApi(page, requests)
  for (const [name, width, height] of [['1920', 1920, 1080], ['1440', 1440, 900], ['1280', 1280, 800], ['390', 390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.goto('/market')
    await expect(page.getByText('非实时行情')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/market-home-${name}.png`, fullPage: true })
  }
})

test('keeps 60-product filtering local and supports keyboard chart review', async ({ page }) => {
  const many = overview()
  many.items = Array.from({ length: 60 }, (_, index) => item(`x${index}`, `测试品种${index}`, 'black', 'up', 'up'))
  many.active_count = many.participant_count = 60
  many.summary.price_up_count = many.summary.daily_up_count = many.summary.aligned_up_count = 60
  many.summary.price_down_count = many.summary.price_flat_count = many.summary.daily_down_count = many.summary.daily_neutral_count = many.summary.daily_unavailable_count = many.summary.aligned_down_count = 0
  many.sectors = [{ sector: 'black', active_count: 60, participant_count: 60, median_price_change_1d: '0.01' }]
  const requests = []
  await mockMarketHomeApi(page, requests, events(), many)
  await page.goto('/market')
  await page.getByPlaceholder('搜索代码或中文名').fill('测试品种59')
  await expect(page.getByRole('rowheader', { name: 'X59 测试品种59' })).toBeVisible()
  await expect(page.getByText('X58 测试品种58')).toHaveCount(0)
  expect(requests.filter((path) => path.endsWith('/home-overview'))).toHaveLength(1)
  await page.locator('tbody tr').filter({ hasText: 'X59 测试品种59' }).press('Enter')
  await expect(page).toHaveURL(/symbol=x59.*series_kind=actual_dominant/)
})

test('retains a cached snapshot and surfaces overview and Runtime degradation', async ({ page }) => {
  let attempts = 0
  const requests = []
  await mockMarketHomeApi(page, requests, events(), () => { attempts += 1; if (attempts > 1) return null; return { ...overview(), status: 'degraded', freshness: 'stale' } }, { ...runtime(), status: 'degraded' })
  await page.goto('/market')
  await expect(page.getByText('overview degraded')).toBeVisible()
  await page.getByText('全部刷新').click()
  await expect(page.getByText('overview cached stale')).toBeVisible()
})
