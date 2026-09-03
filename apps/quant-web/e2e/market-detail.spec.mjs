import { expect, test } from '@playwright/test'

import { detailBar, htdyEvent, installDetailFakeWebSocket, mockMarketDetail, navigateClient } from './market-detail.helpers.mjs'

const freeJm = '/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m'

function freeHistory(total) {
  return Array.from({ length: total }, (_, index) => detailBar('jm', index, 100 + index))
}

async function mockPagedFreeHistory(page, total = 540) {
  const all = freeHistory(total)
  return mockMarketDetail(page, {
    barsPage({ url }) {
      const first = all.slice(-300)
      if (!url.searchParams.get('before')) {
        return {
          bars: first,
          page: { has_more_before: all.length > first.length, next_before: first[0].bar_end },
        }
      }
      const older = all.slice(0, -300)
      return { bars: older, page: { has_more_before: false, next_before: null } }
    },
  })
}

test('missing view keeps the complete legacy detail page', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  await expect(page.locator('[data-detail-ready]')).toHaveCount(0)
})

test('Free mounts its generic workspace without the legacy sidebar or strategy markers', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const shell = page.locator('[data-detail-ready="true"]')
  await expect(shell).toBeVisible()
  await expect(shell.getByText('焦煤', { exact: true }).first()).toBeVisible()
  await expect(page.getByTestId('product-check-sidebar')).toHaveCount(0)
  await expect(page.locator('.product-workspace__sidebar')).toHaveCount(0)
  await expect(shell.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-research-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.getByText('火天大有（原始观察）', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/SuBing|牛哇|Newow/, { exact: false })).toHaveCount(0)

  const order = await shell.locator('[data-detail-section]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-detail-section')))
  expect(order.slice(0, 4)).toEqual(['topbar', 'quote', 'view-nav', 'workspace-slot'])
})

test('Free Range warm-up has a 1280 by 800 baseline and does not create a strategy marker', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('箱体识别（Range）').check()
  await expect(page.getByText(/箱体历史预载不足|箱体历史预载失败/)).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveScreenshot('market-detail-free-range-1280x800.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 400,
  })
})

test('Free Range reaches its fixed ready boundary without strategy markers', async ({ page }) => {
  const requests = await mockPagedFreeHistory(page)
  await page.goto(freeJm)

  await page.getByLabel('箱体识别（Range）').check()
  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBeGreaterThanOrEqual(2)
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveAttribute('data-range-detector-warmup', 'ready')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.getByRole('status')).toContainText('Range Detector 只读回画展示；确认前不可用于策略判断。')
  await expect(page.getByText('箱体历史预载不足')).toHaveCount(0)
})

test('Free shows the fixed Range read-only warning while history is insufficient', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('箱体识别（Range）').check()
  await expect(page.getByRole('status')).toContainText('箱体历史预载不足；Range Detector 只读回画展示；确认前不可用于策略判断。')
})

test('Free pagination keeps an away-from-latest viewport while prepending history', async ({ page }) => {
  const requests = await mockPagedFreeHistory(page, 600)
  await page.goto(freeJm)

  const chart = page.locator('.chart')
  await chart.scrollIntoViewIfNeeded()
  const chartBox = await chart.boundingBox()
  await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5)
  await page.mouse.down()
  await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5, { steps: 12 })
  await page.mouse.up()
  for (let index = 0; index < 2; index += 1) {
    await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5)
    await page.mouse.down()
    await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5, { steps: 12 })
    await page.mouse.up()
  }

  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBeGreaterThanOrEqual(2)
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
})

test('Free exposes fullscreen enter, exit, and return-to-latest controls', async ({ page }) => {
  await mockPagedFreeHistory(page, 600)
  await page.goto(freeJm)

  const chart = page.locator('.chart')
  await chart.scrollIntoViewIfNeeded()
  const chartBox = await chart.boundingBox()
  for (let index = 0; index < 2; index += 1) {
    await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5)
    await page.mouse.down()
    await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5, { steps: 12 })
    await page.mouse.up()
  }
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '回到最新', exact: true }).click()
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: '全屏图表', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出全屏', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '退出全屏', exact: true }).click()
  await expect(page.getByRole('button', { name: '全屏图表', exact: true })).toBeVisible()
})

test('shared K-line focus retries an unresolved target and clears it on identity replacement', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h, ref } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketKlineStage } = await import('/src/components/market/detail/MarketKlineStage.vue')
    const bars = [
      { time: '2026-09-03T02:30:00Z', open: 100, high: 102, low: 99, close: 101, volume: 1000, openInterest: 2000 },
      { time: '2026-09-03T02:45:00Z', open: 101, high: 103, low: 100, close: 102, volume: 1001, openInterest: 2001 },
    ]
    const focus = ref('2026-09-03T00:00:00Z')
    const identity = ref('focus-a')
    const resolved = []
    const app = createApp({
      setup() {
        return () => h(MarketKlineStage, {
          bars,
          mutation: { kind: 'replace', bars },
          loading: false,
          error: null,
          period: '15m',
          seriesKind: 'actual_dominant',
          visibleMainIndicators: [],
          rangeDetectorSourceIdentity: 'focus-test',
          rangeDetectorAnchorTime: null,
          identityKey: identity.value,
          focusBarEnd: focus.value,
          onFocusResolved: (value) => resolved.push(value),
        })
      },
    })
    const host = document.createElement('div')
    host.id = 'focus-stage-contract'
    document.body.append(host)
    app.mount(host)
    window.__marketKlineFocusContract = { focus, identity, resolved, app }
  })

  await expect(page.locator('#focus-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)
  await page.evaluate(() => { window.__marketKlineFocusContract.focus.value = '2026-09-03T02:45:00Z' })
  await expect(page.locator('#focus-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__marketKlineFocusContract.resolved)).toEqual(['2026-09-03T02:45:00Z'])
  await page.evaluate(() => {
    window.__marketKlineFocusContract.identity.value = 'focus-b'
    window.__marketKlineFocusContract.focus.value = null
  })
  await expect(page.locator('#focus-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)
})

test('shared K-line focus also resolves an existing daily trading day', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketKlineStage } = await import('/src/components/market/detail/MarketKlineStage.vue')
    const bars = [
      { time: '2026-09-01T07:00:00Z', trading_day: '2026-09-01', open: 100, high: 102, low: 99, close: 101, volume: 1000, openInterest: 2000 },
      { time: '2026-09-02T07:00:00Z', trading_day: '2026-09-02', open: 101, high: 103, low: 100, close: 102, volume: 1001, openInterest: 2001 },
    ]
    const resolved = []
    const app = createApp({
      setup() {
        return () => h(MarketKlineStage, {
          bars,
          mutation: { kind: 'replace', bars },
          loading: false,
          error: null,
          period: '1d',
          seriesKind: 'actual_dominant',
          visibleMainIndicators: [],
          rangeDetectorSourceIdentity: 'focus-daily-test',
          rangeDetectorAnchorTime: null,
          identityKey: 'focus-daily',
          focusBarEnd: '2026-09-02T07:00:00Z',
          onFocusResolved: (value) => resolved.push(value),
        })
      },
    })
    const host = document.createElement('div')
    host.id = 'focus-daily-stage-contract'
    document.body.append(host)
    app.mount(host)
    window.__marketKlineDailyFocusContract = { resolved, app }
  })

  await expect(page.locator('#focus-daily-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__marketKlineDailyFocusContract.resolved)).toEqual(['2026-09-02T07:00:00Z'])
})

test('Free identity controls keep the selected contract in the URL', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('指定合约').fill('JM2605')
  await page.getByRole('button', { name: '指定合约' }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('contract')
  expect(new URL(page.url()).searchParams.get('contract')).toBe('JM2605')
  await expect.poll(() => requests.some((url) => (
    url.pathname.endsWith('/bars/page')
    && url.searchParams.get('series_kind') === 'contract'
    && url.searchParams.get('contract') === 'JM2605'
  ))).toBe(true)
})

test('Free uses one shared series and frequency control surface while keeping a contract selector', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toHaveCount(1)
  await expect(page.getByRole('button', { name: '15m', exact: true })).toHaveCount(1)
  await expect(page.getByLabel('指定合约')).toHaveCount(1)
  await expect(page.getByRole('button', { name: /市场背景/ })).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('button', { name: /数据详情/ })).toHaveAttribute('aria-expanded', 'false')
})

test('Free reloads continuous, 60m, and daily identities without inventing a physical contract', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  await page.goto(freeJm)
  const seriesControls = page.getByRole('group', { name: '序列' })
  const frequencyControls = page.getByRole('group', { name: '周期' })

  await seriesControls.getByRole('button', { name: '主连', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('continuous')
  await expect(page.locator('.detail-topbar__contract')).toHaveText('JM')
  await expect.poll(() => requests.some((url) => (
    url.pathname.endsWith('/bars/page') && url.searchParams.get('series_kind') === 'continuous'
  ))).toBe(true)

  await frequencyControls.getByRole('button', { name: '60m', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('60m')
  await frequencyControls.getByRole('button', { name: '日K', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('1d')
  await expect.poll(() => requests.some((url) => (
    url.pathname.endsWith('/bars/page') && url.searchParams.get('frequency') === '1d'
  ))).toBe(true)
})

test('Free restores enabled EMA preferences after reload', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('EMA10').check()
  await page.reload()
  await expect(page.getByLabel('EMA10')).toBeChecked()
})

test('Free clears a contract when the product changes and keeps HTDY preferences untouched', async ({ page }) => {
  const recursiveUpdates = []
  page.on('console', (message) => {
    if (message.text().includes('Maximum recursive updates exceeded')) recursiveUpdates.push(message.text())
  })
  await page.addInitScript(() => {
    localStorage.setItem('guiyi.market.detail.preferences.v1', JSON.stringify({
      version: 1, lastView: 'htdy',
      htdy: { seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true },
      free: { seriesKind: 'actual_dominant', frequency: '15m', optionalEmaIndicators: [], showRangeDetector: false },
    }))
  })
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=contract&contract=JM2605&frequency=15m')

  await page.getByLabel('品种代码').fill('rb')
  await page.getByLabel('品种代码').press('Enter')
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
  expect(new URL(page.url()).searchParams.has('contract')).toBe(false)
  await expect(page.getByText('已切换品种，指定合约已清除并回到真实主力。')).toBeVisible()
  await page.getByLabel('箱体识别（Range）').check()
  const preferences = await page.evaluate(() => JSON.parse(localStorage.getItem('guiyi.market.detail.preferences.v1')))
  expect(recursiveUpdates).toEqual([])
  expect(preferences.lastView).toBe('htdy')
  expect(preferences.htdy).toEqual({ seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true })
})

test('shared quote header exposes the market phase and display source', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const quote = page.locator('[data-detail-section="quote"]')
  await expect(quote.getByText('已收盘', { exact: true })).toBeVisible()
  await expect(quote.getByText('Historical', { exact: true })).toBeVisible()
})

test('invalid identity fails closed and only recovers after an explicit click', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=2m')

  await expect(page.getByRole('heading', { name: '详情页地址无效' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('2m')
  await page.getByRole('button', { name: '恢复安全设置' }).click()
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('15m')
})

test('Trend and SuBing stay unavailable while HTDY mounts its observation-only workspace', async ({ page }, testInfo) => {
  await mockMarketDetail(page)
  for (const path of [
    '/market/chart?symbol=jm&view=trend',
    '/market/chart?symbol=jm&view=subing',
  ]) {
    await page.goto(path)
    await expect(page.getByText('当前视角尚未接入统一详情页', { exact: true })).toBeVisible()
    await expect(page.locator('[data-detail-ready="true"]')).toHaveCount(0)
  }

  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
  await expect(page.getByText(/含未来函数的回画观察/)).toBeVisible()
  await expect(page.getByText('首次识别 Event', { exact: true }).first()).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('market-detail-htdy-1440x900.png'), fullPage: false })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('market-detail-htdy-history-390.png'), fullPage: false })

  await page.getByRole('button', { name: '更多', exact: true }).click()
  await page.getByRole('menuitem', { name: '返回旧版详情' }).click()
  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  await expect(page.locator('.route-error-fallback')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.has('view')).toBe(false)
})

test('HTDY resolves immutable Event focus across every official frequency', async ({ page }) => {
  const cases = [
    ['1m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['5m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['15m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['30m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['60m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['1d', '2026-07-02T02:45:00.000Z', '2026-07-02', '2026-07-02T02:46:00.000Z'],
    ['1w', '2026-07-08T02:45:00.000Z', '2026-07-08', '2026-07-08T02:46:00.000Z'],
  ]
  let currentCase = null
  const requests = await mockMarketDetail(page, {
    barsPage: ({ url, symbol }) => {
      const frequency = url.searchParams.get('frequency')
      if (frequency === '1d' || frequency === '1w') {
        const total = frequency === '1w' ? 10 : 60
        return { bars: Array.from({ length: total }, (_, index) => {
          const day = new Date(Date.UTC(2026, 6, 1 + index * (frequency === '1w' ? 7 : 1))).toISOString().slice(0, 10)
          return { ...detailBar(symbol, index, 100 + index), bar_end: `${day}T07:00:00.000Z`, trading_day: day }
        }) }
      }
      return { bars: Array.from({ length: 60 }, (_, index) => detailBar(symbol, index, 100 + index)) }
    },
    alertEvents: () => currentCase ? [htdyEvent('jm', currentCase[0], currentCase[1], currentCase[2], currentCase[3])] : [],
  })
  for (const [frequency, focus, tradingDay, detectedAt] of cases) {
    currentCase = [frequency, focus, tradingDay, detectedAt]
    await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=${frequency}&focus_bar_end=${encodeURIComponent(focus)}`)
    await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
    const eventFact = page.locator('[data-detail-section="facts"] > div').filter({ hasText: '首次识别 Event' })
    await expect(eventFact).toContainText('买入观察')
    await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
    await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  }
  const eventRequests = requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))
  expect(eventRequests.length).toBeGreaterThanOrEqual(7)
  expect(requests.alertRequests.every(({ method }) => method !== 'PUT')).toBe(true)

  const before = eventRequests.length
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=continuous&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=contract&contract=JM2601&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))).toHaveLength(before)
})

test('HTDY keeps last successful immutable Event evidence when a later Event refresh fails', async ({ page }) => {
  let eventCalls = 0
  await mockMarketDetail(page, {
    alertEvents: () => (++eventCalls === 1 ? [htdyEvent('jm', '15m')] : 'error'),
  })
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m')
  const facts = page.locator('[data-detail-section="facts"]')
  const rawFact = facts.locator('div').filter({ has: page.getByText('当前重绘观察', { exact: true }) })
  const eventFact = facts.locator('div').filter({ has: page.getByText('首次识别 Event', { exact: true }) })
  await expect(rawFact).toContainText('暂无')
  await expect(eventFact).toContainText('买入观察')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect(page.getByRole('button', { name: '历史记录' })).toBeVisible()
  await expect(page.getByText(/最后成功快照（已旧）/)).toBeVisible({ timeout: 35_000 })
  await page.getByRole('button', { name: '历史记录' }).click()
  await expect(page.getByText(/Bar 2026-09-03T02:45:00.000Z/)).toBeVisible()
})

test('HTDY consumes a resolved 30m focus once before returning to legacy', async ({ page }) => {
  await mockMarketDetail(page)
  const focus = '2026-09-03T02:30:00Z'
  await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=30m&focus_bar_end=${encodeURIComponent(focus)}`)
  await page.evaluate(async () => {
    const { router } = await import('/src/app/router.ts')
    window.__legacyNavigationQuery = null
    router.beforeEach((to) => {
      if (to.path === '/market/chart' && to.query.view === undefined) {
        window.__legacyNavigationQuery = { ...to.query }
      }
    })
  })

  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  await page.getByRole('button', { name: '更多', exact: true }).click()
  await page.getByRole('menuitem', { name: '返回旧版详情' }).click()
  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  const legacyUrl = new URL(page.url())
  expect(legacyUrl.searchParams.has('view')).toBe(false)
  expect(legacyUrl.searchParams.get('overlay')).toBe('htdy')
  expect(await page.evaluate(() => window.__legacyNavigationQuery.focus_bar_end)).toBeUndefined()
})

test('returning a daily HTDY event only consumes focus after locating its trading day', async ({ page }) => {
  await mockMarketDetail(page)
  const focus = '2026-09-03T02:45:00Z'
  await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=1d&focus_bar_end=${encodeURIComponent(focus)}`)

  await page.getByRole('button', { name: '更多', exact: true }).click()
  await page.getByRole('menuitem', { name: '返回旧版详情' }).click()
  await expect(page.getByTestId('product-status-strip')).toBeVisible()
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
})

test('returning a fixed view to legacy makes its parsed identity explicit', async ({ page }) => {
  await mockMarketDetail(page)
  for (const expected of [
    { path: '/market/chart?symbol=jm&view=trend', frequency: '1d' },
    { path: '/market/chart?symbol=jm&view=subing', frequency: '15m' },
  ]) {
    await page.goto(expected.path)
    await page.evaluate(async () => {
      const { router } = await import('/src/app/router.ts')
      window.__legacyNavigationQuery = null
      router.beforeEach((to) => {
        if (to.path === '/market/chart' && to.query.view === undefined) {
          window.__legacyNavigationQuery = { ...to.query }
        }
      })
    })

    await page.getByRole('button', { name: '返回旧版详情' }).click()
    await expect(page.getByTestId('product-status-strip')).toBeVisible()
    const transferred = await page.evaluate(() => window.__legacyNavigationQuery)
    expect(transferred.series_kind).toBe('actual_dominant')
    expect(transferred.frequency).toBe(expected.frequency)
  }
})

test('a late JM response cannot overwrite a newer RB identity', async ({ page }) => {
  await mockMarketDetail(page, { researchDelayMs: { jm: 400 } })
  await page.goto(freeJm)
  await navigateClient(page, '/market/chart?symbol=rb&view=free&series_kind=actual_dominant&frequency=15m')

  const shell = page.locator('[data-detail-ready="true"]')
  await expect(shell.getByText('螺纹钢', { exact: true }).first()).toBeVisible()
  await expect(shell.getByText('201.00', { exact: true })).toBeVisible()
  await page.waitForTimeout(500)
  await expect(shell.getByText('螺纹钢', { exact: true }).first()).toBeVisible()
  await expect(shell.getByText('201.00', { exact: true })).toBeVisible()
})

test('leaving the Free shell closes its live series resource', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  await mockMarketDetail(page, { live: true })
  await page.goto(freeJm)

  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window.__marketDetailSockets?.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length ?? 0
  ))).toBeGreaterThan(0)

  await navigateClient(page, '/market/chart?symbol=jm&view=trend')
  await expect(page.getByText('当前视角尚未接入统一详情页', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window.__marketDetailSockets
      ?.filter((socket) => socket.url.includes('/api/v1/market/ws'))
      .every((socket) => socket.closed) ?? false
  ))).toBe(true)
})

test('390px shell keeps keyboard disclosure and does not invent history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const disclosure = page.getByRole('button', { name: /更多行情数据/ })
  await disclosure.focus()
  await page.keyboard.press('Enter')
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Space')
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('button', { name: '历史记录' })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveScreenshot('market-detail-free-390.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 400,
  })
})

test('mobile history drawer traps focus, closes with Escape, and restores its trigger', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h, ref } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketDetailDrawer } = await import('/src/components/market/detail/MarketDetailDrawer.vue')
    const host = document.createElement('div')
    host.id = 'drawer-browser-contract'
    document.body.append(host)
    const open = ref(false)
    const app = createApp({
      setup() {
        return () => h('div', [
          h('button', { id: 'drawer-trigger', onClick: () => { open.value = true } }, '打开历史'),
          h(MarketDetailDrawer, {
            open: open.value,
            title: '历史记录',
            onClose: () => { open.value = false },
          }, { default: () => h('button', { id: 'drawer-action' }, '历史项') }),
        ])
      },
    })
    app.mount(host)
    window.__marketDetailDrawerContractApp = app
  })

  const trigger = page.locator('#drawer-trigger')
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '历史记录' })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.locator('#drawer-action').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})
