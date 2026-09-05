import { expect, test } from '@playwright/test'

import {
  assertNewowCupFixtureLifecycle,
  detailBar,
  htdyEvent,
  installDetailFakeWebSocket,
  mockMarketDetail,
  navigateClient,
  newowTrendDetailFixture,
  trendGenericBars,
  subingEvent,
  subingRule,
} from './market-detail.helpers.mjs'

const freeJm = '/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m'
const trendJm = '/market/chart?symbol=jm&view=trend'

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

async function mockReadyTrend(page, options = {}) {
  return mockMarketDetail(page, {
    barsPage({ url, symbol }) {
      if (url.searchParams.get('frequency') !== '1d') return undefined
      const bars = trendGenericBars(symbol)
      const upper = symbol.toUpperCase()
      return {
        bars,
        resolvedContractSegments: [
          { contract: `${upper}2601`, start_trading_day: bars[0].trading_day, end_trading_day: bars[3].trading_day },
          { contract: `${upper}2605`, start_trading_day: bars[4].trading_day, end_trading_day: bars.at(-1).trading_day },
        ],
      }
    },
    newowTrendDetail: ({ url, product }) => newowTrendDetailFixture({
      product,
      from: url.searchParams.get('from'),
      through: url.searchParams.get('through'),
    }),
    ...options,
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
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
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

test('Trend uses one fixed Newow authority and preserves same-Bar facts in history', async ({ page }) => {
  const fixture = newowTrendDetailFixture({ product: 'jm' })
  expect(() => assertNewowCupFixtureLifecycle(fixture)).not.toThrow()
  await installDetailFakeWebSocket(page)
  const requests = await mockReadyTrend(page)
  await page.goto(trendJm)

  const workspace = page.locator('[data-detail-workspace="trend"]')
  await expect(workspace).toHaveAttribute('data-newow-state', 'ready')
  await expect(page.getByText('固定日K', { exact: true })).toBeVisible()
  await expect(page.getByRole('group', { name: '序列' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: '周期' })).toHaveCount(0)
  await expect(page.getByLabel('指定合约')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '预警', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)

  const route = new URL(page.url())
  expect([...route.searchParams.keys()].sort()).toEqual(['symbol', 'view'])
  expect(route.searchParams.get('view')).toBe('trend')
  expect(route.searchParams.has('focus_bar_end')).toBe(false)

  const facts = await workspace.locator('[data-detail-section="facts"] > div').evaluateAll((nodes) => nodes.map((node) => ({
    label: node.querySelector('dt')?.textContent?.trim(),
    value: node.querySelector('dd')?.textContent?.trim(),
  })))
  expect(facts).toEqual([
    { label: '周线背景', value: '中性' },
    { label: '日线趋势', value: '持有' },
    { label: '当前风险', value: 'D1' },
  ])
  await expect(workspace.getByRole('status').first()).toContainText('趋势引擎状态，不代表实际账户持仓')
  await expect(workspace.getByText('仅展示已完成 D1；未完成 Bar 不进入 Newow 事实。')).toBeVisible()
  await expect(workspace.getByText('蓝色仅表示 Newow 的空仓或风险阶段，不表示建立期货空单。')).toBeVisible()
  await expect(workspace.getByText(/主力换月.*不表示交易机会/)).toBeVisible()

  const chart = page.getByTestId('newow-trend-chart-stage')
  await expect(chart).toHaveAttribute('data-chart-source', 'newow')
  await expect(chart).toHaveAttribute('data-pane-count', '2')
  await expect(chart).toHaveAttribute('data-newow-band-area-count', '8')
  await expect(chart).toHaveAttribute('data-newow-marker-count', '17')
  await expect(chart).toHaveAttribute('data-newow-rollover-count', '1')
  await expect(chart).toHaveAttribute('data-newow-marker-ids', /escape-latest-d1/)
  await expect(chart).not.toHaveAttribute('data-newow-marker-ids', /escape-latest-d2|escape-latest-d3/)
  await expect(page.getByTestId('kline-shell')).toHaveCount(0)
  await expect(page.getByLabel('箱体识别（Range）')).toHaveCount(0)
  await expect(page.getByText('火天大有（原始观察）', { exact: true })).toHaveCount(0)

  await expect(workspace.getByText('newow_trend_v1', { exact: true })).toBeVisible()
  await expect(workspace.getByText('newow_trend_d1_page_v2', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '风险与形态', exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: '主力与数据', exact: false })).toBeVisible()

  await page.getByRole('button', { name: '历史记录', exact: true }).first().click()
  const history = workspace.locator('.detail-section-tabs__history')
  await expect(history).toContainText('类型 NEWOW_ESCAPE_D1')
  await expect(history).toContainText('类型 NEWOW_ESCAPE_D2')
  await expect(history).toContainText('类型 NEWOW_ESCAPE_D3')
  await expect(history).toContainText('类型 CUP_HANDLE_READY')
  await expect(history).toContainText('类型 CUP_HANDLE_BREAKOUT')
  await expect(history).toContainText('类型 CUP_HANDLE_WEAKENED')
  await expect(history).toContainText('类型 CUP_HANDLE_INVALIDATED')
  await expect(history).toContainText('类型 CUP_HANDLE_EXPIRED')
  await expect(history).toContainText('合约 JM2601')
  await expect(history).toContainText('合约 JM2605')
  await expect(history).not.toContainText(/AlertEvent|已尝试通知|送达/)

  expect(requests.newowRequests).toHaveLength(1)
  const newowRequest = requests.newowRequests[0]
  expect(newowRequest.pathname).toBe('/api/v1/market/newow/trend-detail')
  expect(Object.fromEntries(newowRequest.searchParams)).toEqual({
    product: 'jm',
    from: '2026-08-21',
    through: '2026-09-03',
    frequency: '1d',
    series_kind: 'actual_dominant',
  })
  expect(requests.alertRequests).toEqual([])
  expect(requests.runtimeRequests).toEqual([])
  expect(await page.evaluate(() => (
    window.__marketDetailSockets?.filter((socket) => socket.url.includes('/api/v1/market/ws')).length ?? 0
  ))).toBe(0)
  expect(requests.every((url) => [
    '/api/v1/market/dominants',
    '/api/v1/market/research/product',
    '/api/v1/market/state',
    '/api/v1/market/bars/page',
    '/api/v1/market/newow/trend-detail',
  ].includes(url.pathname))).toBe(true)
})

test('Trend unavailable and contract-mismatched responses fall back to generic D1 without overlays', async ({ page }) => {
  let responseMode = 'unavailable'
  const requests = await mockReadyTrend(page, {
    newowTrendDetail({ url, product }) {
      if (responseMode === 'unavailable') return 'error'
      const payload = newowTrendDetailFixture({
        product,
        from: url.searchParams.get('from'),
        through: url.searchParams.get('through'),
      })
      payload.instrument.last_visible_physical_contract = `${product.toUpperCase()}9999`
      return payload
    },
  })
  await page.goto(trendJm)

  const workspace = page.locator('[data-detail-workspace="trend"]')
  const chart = page.getByTestId('newow-trend-chart-stage')
  await expect(workspace).toHaveAttribute('data-newow-state', 'unavailable')
  await expect(chart).toHaveAttribute('data-chart-source', 'generic-fallback')
  await expect(chart).toHaveAttribute('data-newow-band-area-count', '0')
  await expect(chart).toHaveAttribute('data-newow-marker-count', '0')
  await expect(chart).toHaveAttribute('data-newow-rollover-count', '0')
  await expect(page.getByTestId('newow-trend-chart-unavailable')).toContainText('仅显示 completed D1 K 线与成交量')
  await expect(workspace.getByText('趋势策略数据不可用；当前页面不会从基础 K 线推断 Newow 状态。')).toBeVisible()
  await expect(workspace.locator('[data-detail-section="facts"] dd')).toHaveText(['中性', '不可用', '不可用'])
  await expect(page.getByRole('button', { name: '历史记录', exact: true })).toHaveCount(0)

  responseMode = 'contract-mismatch'
  await page.reload()
  await expect(workspace).toHaveAttribute('data-newow-state', 'unavailable')
  await expect(chart).toHaveAttribute('data-chart-source', 'generic-fallback')
  await expect(chart).toHaveAttribute('data-newow-marker-count', '0')
  expect(requests.newowRequests).toHaveLength(2)
  expect(requests.alertRequests).toEqual([])
  expect(requests.runtimeRequests).toEqual([])
})

test('Trend controller paging expands the parity window and history focus restores latest and fullscreen', async ({ page }) => {
  const requests = await mockReadyTrend(page, {
    newowTrendDetail({ url, product }) {
      const payload = newowTrendDetailFixture({ product, from: url.searchParams.get('from'), through: url.searchParams.get('through') })
      payload.bars = payload.bars.filter((bar) => bar.trading_day >= url.searchParams.get('from'))
      const visible = new Set(payload.bars.map((bar) => bar.bar_end))
      for (const key of ['trend_band', 'trend_markers', 'escape_markers', 'cup_markers']) {
        payload[key] = payload[key].filter((item) => visible.has(item.bar_end))
      }
      payload.rollover_seams = payload.rollover_seams.filter((seam) => visible.has(seam.previous_bar_end) && visible.has(seam.next_bar_end))
      return payload
    },
    barsPage({ url, symbol }) {
      const all = trendGenericBars(symbol)
      const earlier = url.searchParams.has('before')
      const bars = earlier ? all.slice(0, 4) : all.slice(4)
      return { bars, page: { has_more_before: !earlier, next_before: earlier ? null : bars[0].bar_end },
        resolvedContractSegments: [{ contract: bars[0].physical_contract,
          start_trading_day: bars[0].trading_day, end_trading_day: bars.at(-1).trading_day }] }
    },
  })
  await page.goto(`${trendJm}&focus_bar_end=2026-09-03T07%3A00%3A00Z`)
  const workspace = page.locator('[data-detail-workspace="trend"]')
  const chart = page.getByTestId('newow-trend-chart-stage')
  await expect(workspace).toHaveAttribute('data-newow-state', 'ready')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  await page.getByRole('button', { name: '加载更早', exact: true }).click()
  await expect(chart).toHaveAttribute('data-newow-rollover-count', '1')
  expect(requests.newowRequests.at(-1).searchParams.get('from')).toBe('2026-08-21')
  await page.getByRole('button', { name: '历史记录', exact: true }).first().click()
  const historical = workspace.locator('.detail-section-tabs__history button').filter({ hasText: '合约 JM2601' }).first()
  await historical.click()
  await expect(page.getByTestId('newow-selected-marker')).toContainText('JM2601')
  await expect(chart.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await chart.getByRole('button', { name: '回到最新', exact: true }).click()
  await expect(chart.getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)
  await chart.getByRole('button', { name: '全屏图表', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true)
  await chart.getByRole('button', { name: '退出全屏', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(false)
  await navigateClient(page, '/market/chart?symbol=rb&view=trend')
  await expect(page.getByTestId('newow-selected-marker')).toHaveCount(0)
  expect(requests.alertRequests).toEqual([])
  expect(requests.runtimeRequests).toEqual([])
})

test('Trend OHLCV parity conflict clears every Newow layer and shows the stable identity code', async ({ page }) => {
  await mockReadyTrend(page, { barsPage({ symbol }) {
    const bars = trendGenericBars(symbol)
    bars.at(-1).volume += 1
    const upper = symbol.toUpperCase()
    return { bars, resolvedContractSegments: [
      { contract: `${upper}2601`, start_trading_day: bars[0].trading_day, end_trading_day: bars[3].trading_day },
      { contract: `${upper}2605`, start_trading_day: bars[4].trading_day, end_trading_day: bars.at(-1).trading_day },
    ] }
  } })
  await page.goto(trendJm)
  const chart = page.getByTestId('newow-trend-chart-stage')
  await expect(page.getByText(/NEWOW_DATA_IDENTITY_INVALID：/)).toBeVisible()
  await expect(chart).toHaveAttribute('data-chart-source', 'generic-fallback')
  for (const attr of ['data-newow-band-area-count', 'data-newow-marker-count', 'data-newow-rollover-count']) {
    await expect(chart).toHaveAttribute(attr, '0')
  }
  await expect(page.getByRole('button', { name: '历史记录', exact: true })).toHaveCount(0)
})

test('a stale Trend response cannot overwrite a newer product identity', async ({ page }) => {
  const requests = await mockReadyTrend(page, { newowDelayMs: { jm: 400 } })
  await page.goto(trendJm)
  await expect.poll(() => requests.newowRequests.length).toBe(1)
  await navigateClient(page, '/market/chart?symbol=rb&view=trend')

  const workspace = page.locator('[data-detail-workspace="trend"]')
  await expect(workspace).toHaveAttribute('data-newow-state', 'ready')
  await expect(page.locator('.detail-topbar__name')).toHaveText('螺纹钢')
  await expect(page.locator('.detail-topbar__contract')).toHaveText('RB')
  await expect(page.getByTestId('newow-trend-chart-stage')).toHaveAttribute('data-chart-source', 'newow')
  await expect(workspace.getByText('RB2605', { exact: true }).first()).toBeVisible()
  await expect.poll(() => requests.newowCompletedProducts.includes('jm')).toBe(true)
  await expect(page.locator('.detail-topbar__name')).toHaveText('螺纹钢')
  await expect(page.locator('.detail-topbar__contract')).toHaveText('RB')
  await expect(workspace.getByText('RB2605', { exact: true }).first()).toBeVisible()
})

test('Free, HTDY, and SuBing remain isolated workspaces with only SuBing Event facts', async ({ page }) => {
  const requests = await mockReadyTrend(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto(freeJm)
  await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-research-marker-count', '0')

  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
  await expect(page.getByText(/含未来函数的回画观察/)).toBeVisible()
  await expect(page.getByText('首次识别 Event', { exact: true }).first()).toBeVisible()

  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="subing"]')).toBeVisible()
  await expect(page.getByText(/正式 S↑ \/ S↓ 只来自 AlertEvent/)).toBeVisible()
  await expect(page.getByText(/S↑ 多头预警/).first()).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect(page.locator('[data-detail-section="facts"] > div').filter({ hasText: '预警状态' })).toContainText('尚无已评估 Bar')
  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="subing"] .detail-section-tabs__history')).toContainText('Bar 2026-09-03T02:45:00.000Z')
  expect(requests.alertRequests.every(({ method }) => method === 'GET')).toBe(true)
  expect(requests.newowRequests).toEqual([])
})

test('SuBing projects Rule-specific runtime warm-up and failure states', async ({ page }) => {
  let errorType = 'evaluation_warming_up'
  await mockReadyTrend(page, {
    alertRules: [subingRule()],
    subingRuntimeRuleStatus: () => ({ error_type: errorType }),
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  const statusFact = page.locator('[data-detail-section="facts"] > div').filter({ hasText: '预警状态' })
  await expect(statusFact).toContainText('正在 warm-up')

  errorType = 'evaluation_failed'
  await page.reload()
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(statusFact).toContainText('评估失败')
})

test('SuBing has stable desktop and narrow viewport visuals with selectable history', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockReadyTrend(page, {
    barsPage: ({ url, symbol }) => url.searchParams.get('frequency') === '15m'
      ? { bars: Array.from({ length: 40 }, (_, index) => detailBar(symbol, index, 100 + index)) }
      : undefined,
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  const workspace = page.locator('[data-detail-workspace="subing"]')
  await expect(workspace).toBeVisible()
  const chart = page.getByTestId('kline-shell')
  await chart.scrollIntoViewIfNeeded()
  await expect(page).toHaveScreenshot('market-detail-subing-1440x900.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 500,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '历史记录', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '历史记录' })).toContainText('Bar 2026-09-03T02:45:00.000Z')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page).toHaveScreenshot('market-detail-subing-390x844.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 500,
  })
})

test('SuBing marker click opens the matching immutable AlertEvent detail', async ({ page }) => {
  await mockReadyTrend(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  const chart = page.getByTestId('kline-shell')
  await chart.scrollIntoViewIfNeeded()
  const bounds = await chart.boundingBox()
  if (!bounds) throw new Error('SuBing chart is not visible')
  await page.mouse.click(bounds.x + bounds.width * 0.714, bounds.y + bounds.height * 0.4)
  await expect(page.getByRole('dialog', { name: '苏冰预警详情' })).toContainText('S↑ 多头预警 · 2026-09-03T02:45:00.000Z · JM2601')
})

test('SuBing consumes its exact AlertEvent focus once', async ({ page }) => {
  await mockReadyTrend(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  const focus = '2026-09-03T02:45:00.000Z'
  await page.goto(`/market/chart?symbol=jm&view=subing&focus_bar_end=${encodeURIComponent(focus)}`)
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
})

test('SuBing focus remains visible after viewport readiness settles', async ({ page }) => {
  await mockReadyTrend(page, {
    barsPage: ({ url, symbol }) => url.searchParams.get('frequency') === '15m'
      ? { bars: Array.from({ length: 600 }, (_, index) => detailBar(symbol, index, 100 + index)) }
      : undefined,
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  const focus = '2026-09-03T02:45:00.000Z'
  await page.goto(`/market/chart?symbol=jm&view=subing&focus_bar_end=${encodeURIComponent(focus)}`)
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  const range = await page.getByTestId('kline-shell').evaluate((element) => {
    const instance = element.__vueParentComponent
    return instance?.setupState?.chart?.timeScale().getVisibleLogicalRange() ?? null
  })
  expect(range).not.toBeNull()
  expect(range.from).toBeLessThanOrEqual(1)
  expect(range.to).toBeGreaterThanOrEqual(1)
  expect(range.to - range.from).toBeLessThan(100)
})

test('Trend has stable desktop and narrow viewport visuals', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await mockReadyTrend(page)
  await page.goto(trendJm)
  await expect(page.locator('[data-detail-workspace="trend"]')).toHaveAttribute('data-newow-state', 'ready')
  const chart = page.getByTestId('newow-trend-chart-stage')
  await chart.scrollIntoViewIfNeeded()
  await expect(page).toHaveScreenshot('market-detail-trend-1920x1080.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 500,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('[data-detail-workspace="trend"]')).toBeVisible()
  await chart.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page).toHaveScreenshot('market-detail-trend-390x844.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 500,
  })
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
    { path: '/market/chart?symbol=jm&view=trend', frequency: '1d', mounted: true },
    { path: '/market/chart?symbol=jm&view=subing', frequency: '15m', mounted: true },
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

    if (expected.mounted) {
      await page.getByRole('button', { name: '更多', exact: true }).click()
      await page.getByRole('menuitem', { name: '返回旧版详情' }).click()
    } else {
      await page.getByRole('button', { name: '返回旧版详情' }).click()
    }
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
  await expect(page.locator('[data-detail-workspace="trend"]')).toHaveAttribute('data-newow-state', 'unavailable')
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
