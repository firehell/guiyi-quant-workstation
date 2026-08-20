import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const futuresFixture = JSON.parse(readFileSync(new URL('../../../tests/fixtures/main_force_mirror_futures_v1_golden.json', import.meta.url)))

async function recordCanvasText(page) {
  await page.addInitScript(() => {
    window.__GUIYI_E2E_CANVAS_TEXT__ = []
    const original = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (value, ...args) {
      window.__GUIYI_E2E_CANVAS_TEXT__.push(String(value))
      return original.call(this, value, ...args)
    }
  })
}

function bars(count = 96) {
  return Array.from({ length: count }, (_, index) => {
    const barEnd = new Date(Date.UTC(2026, 0, 1, 1 + index)).toISOString()
    const base = 100 + index * 0.35 + 3 * Math.sin(index / 3)
    const open = base + Math.sin(index)
    const close = base + Math.cos(index * 1.3)
    return {
      bar_end: barEnd,
      trading_day: barEnd.slice(0, 10),
      open,
      high: Math.max(open, close) + 1.5,
      low: Math.min(open, close) - 1.5,
      close,
      volume: 1_000 + index * 20,
      turnover: null,
      open_interest: 2_000 + index * 5,
    }
  })
}

function rolloverBars(contractBCount) {
  const contractA = futuresFixture.bars.slice(0, 40).map((bar, index) => ({
    bar_end: new Date(Date.UTC(2026, 0, 2, index)).toISOString(),
    trading_day: '2026-01-02',
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
    turnover: null,
    open_interest: bar.open_interest,
  }))
  const contractB = Array.from({ length: contractBCount }, (_, index) => {
    const base = 200 + index * 0.1
    const open = base + Math.sin(index / 3) * 0.05
    const close = base + Math.cos(index / 4) * 0.05
    return {
      bar_end: new Date(Date.UTC(2026, 0, 3, 16 + index)).toISOString(),
      trading_day: '2026-01-03',
      open,
      high: Math.max(open, close) + 1,
      low: Math.min(open, close) - 1,
      close,
      volume: 1_000 + index,
      turnover: null,
      open_interest: 5_000 + index * 2,
    }
  })
  return [...contractA, ...contractB]
}

const rolloverSegments = [
  { contract: 'AG2601', start_trading_day: '2026-01-02', end_trading_day: '2026-01-02' },
  { contract: 'AG2612', start_trading_day: '2026-01-03', end_trading_day: '2026-01-03' },
]

async function mockChartMarketApi(page, requests, items = bars(), resolvedContractSegments = null) {
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    if (url.pathname.endsWith('/dominants')) {
      await route.fulfill({ json: { items: [
        { product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-08-19' },
      ] } })
      return
    }
    if (url.pathname.endsWith('/bars/page')) {
      await route.fulfill({ json: {
        request: {
          series_kind: url.searchParams.get('series_kind'), symbol: 'ag', contract: url.searchParams.get('contract'),
          frequency: url.searchParams.get('frequency'), before: null, limit: 1200,
        },
        bars: items,
        canonical_coverage: null,
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: resolvedContractSegments ?? [{
          contract: 'AG2601',
          start_trading_day: items[0].trading_day,
          end_trading_day: items.at(-1).trading_day,
        }],
      } })
      return
    }
    if (url.pathname.endsWith('/state')) {
      await route.fulfill({ json: {
        symbol: 'ag', series_kind: url.searchParams.get('series_kind'), frequency: url.searchParams.get('frequency'), operational: false,
        phase: 'CLOSED', trading_day: '2026-08-19', live_eligible: false, live_available: false,
        live_contract: null, canonical_end: items.at(-1).bar_end, after_market: {},
      } })
      return
    }
    await route.fulfill({ status: 503, json: { detail: 'not required by futures secondary-panel test' } })
  })
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/current-events')) {
      await route.fulfill({ json: { status: 'ready', trading_day: items.at(-1)?.trading_day ?? null, items: [] } })
      return
    }
    if (url.pathname.endsWith('/products/ag')) {
      await route.fulfill({ json: { symbol: 'ag', rules: [] } })
      return
    }
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [] } })
    await route.fulfill({ status: 503, json: { detail: 'not required by futures secondary-panel test' } })
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: { status: 'ok', components: { alert: { status: 'disabled' } } } }))
}

function barRequestCount(requests) {
  return requests.filter((url) => url.pathname.endsWith('/bars/page')).length
}

async function secondaryPaneBounds(shell) {
  return shell.locator('.chart').evaluate((chart) => {
    const rows = Array.from(chart.querySelectorAll('tr')).filter((row) => row.querySelectorAll('canvas').length >= 4)
    const rect = rows[2]?.getBoundingClientRect()
    return rect ? { top: rect.top, bottom: rect.bottom } : null
  })
}

test('futures mirror tab is identity-gated, ordered, and local to the existing chart data', async ({ page }) => {
  const requests = []
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.chart.preferences.v3', JSON.stringify({
      version: 3,
      selectedOverlay: 'none',
      optionalEmaIndicators: [],
      period: null,
      realtimeFollow: false,
    }))
  })
  await mockChartMarketApi(page, requests)

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
  await expect(page.getByText('96 bars')).toBeVisible()

  const shell = page.getByTestId('kline-shell')
  const tabs = page.getByTestId('secondary-panel-tabs')
  await expect(tabs.getByRole('tab')).toHaveText(['MACD', '主力照妖镜', '原型V0'])
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toBeEnabled()
  await expect(tabs.getByRole('tab', { name: '原型V0' })).toBeEnabled()

  const initialBarRequests = barRequestCount(requests)
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror_futures')
  expect(barRequestCount(requests)).toBe(initialBarRequests)
  await expect(page.getByTestId('main-force-futures-pane-status')).toContainText(/ready|caution_warmup|conflict/)
  await page.getByLabel('周期').getByText('15m', { exact: true }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toBeDisabled()
  await expect(tabs.getByRole('tab', { name: '原型V0' })).toHaveAttribute('aria-selected', 'false')
  await page.getByLabel('周期').getByText('60m', { exact: true }).click()
  await expect.poll(() => barRequestCount(requests)).toBe(3)
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toBeEnabled()
  const barRequestsBeforeTabSwitch = barRequestCount(requests)
  await tabs.getByRole('tab', { name: '原型V0' }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror_v0')
  await tabs.getByRole('tab', { name: 'MACD' }).click()
  expect(barRequestCount(requests)).toBe(barRequestsBeforeTabSwitch)

  await page.goto('/market/chart?symbol=ag&series_kind=continuous&frequency=60m')
  await expect(page.getByText('96 bars')).toBeVisible()
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toBeDisabled()
  await expect(page.getByTestId('main-force-futures-pane-status')).toHaveText('unsupported · MFM_FUTURES_V1_SERIES_UNSUPPORTED')

  await page.goto('/market/chart?symbol=ag&series_kind=contract&contract=AG2601&frequency=60m')
  await expect(page.getByText('96 bars')).toBeVisible()
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toBeEnabled()
})

test('futures mirror renders signed scores and stays local across pane switches', async ({ page }) => {
  const requests = []
  await recordCanvasText(page)
  const fixtureBars = futuresFixture.bars.map((bar) => ({
    bar_end: bar.time,
    trading_day: bar.time.slice(0, 10),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
    turnover: null,
    open_interest: bar.open_interest,
  }))
  await mockChartMarketApi(page, requests, fixtureBars)

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
  await expect(page.getByText('40 bars')).toBeVisible()
  const shell = page.getByTestId('kline-shell')
  const tabs = page.getByTestId('secondary-panel-tabs')
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()

  await expect(page.getByText('70 = 风险证据评分阈值，不是资金流比例或概率')).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining(['追多小心 70', '追空小心 75']),
  )
  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  await tabs.getByRole('tab', { name: '原型V0' }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror_v0')
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror_futures')
})

test('three-tab pane keeps rendered V1 content and controls within each required desktop viewport', async ({ page }) => {
  const requests = []
  const fixtureBars = futuresFixture.bars.map((bar) => ({
    bar_end: bar.time, trading_day: bar.time.slice(0, 10), open: bar.open, high: bar.high, low: bar.low,
    close: bar.close, volume: bar.volume, turnover: null, open_interest: bar.open_interest,
  }))
  await mockChartMarketApi(page, requests, fixtureBars)
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
    await expect(page.getByText('40 bars')).toBeVisible()
    const shell = page.getByTestId('kline-shell')
    const tabs = page.getByTestId('secondary-panel-tabs')
    await tabs.getByRole('tab', { name: '主力照妖镜' }).click()
    await expect(page.getByTestId('main-force-futures-pane-status')).toContainText(/state_warmup|caution_warmup|ready|conflict/)
    const chart = page.locator('.chart')
    const chartBox = await chart.boundingBox()
    if (!chartBox) throw new Error('chart bounds unavailable')
    await page.mouse.move(chartBox.x + chartBox.width * 0.5, chartBox.y + chartBox.height * 0.2)
    await expect(page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2601')
    const shellBox = await shell.boundingBox()
    const tabsBox = await tabs.boundingBox()
    const legendBox = await page.getByLabel('期货主力照妖镜图例').boundingBox()
    const hoverBox = await page.locator('.kline-hover-legend').boundingBox()
    const pane = await secondaryPaneBounds(shell)
    if (!shellBox || !tabsBox || !legendBox || !hoverBox) throw new Error('kline bounds unavailable')
    if (!pane) throw new Error('secondary pane bounds unavailable')
    for (const box of [tabsBox, legendBox]) {
      expect(box.x).toBeGreaterThanOrEqual(shellBox.x)
      expect(box.y).toBeGreaterThanOrEqual(pane.top)
      expect(box.x + box.width).toBeLessThanOrEqual(shellBox.x + shellBox.width)
      expect(box.y + box.height).toBeLessThanOrEqual(pane.bottom)
    }
    expect(hoverBox.y).toBeGreaterThanOrEqual(shellBox.y)
    expect(hoverBox.y + hoverBox.height).toBeLessThanOrEqual(shellBox.y + shellBox.height)
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('actual-dominant rollover resets B readiness identity and caution markers', async ({ page, context }) => {
  async function openRolloverPage(target, contractBCount) {
    const requests = []
    await target.addInitScript(() => {
      window.localStorage.setItem('guiyi.market.chart.preferences.v3', JSON.stringify({
        version: 3,
        selectedOverlay: 'none',
        optionalEmaIndicators: [],
        period: null,
        realtimeFollow: false,
      }))
    })
    await mockChartMarketApi(target, requests, rolloverBars(contractBCount), rolloverSegments)
    await target.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
    await expect(target.getByText(`${40 + contractBCount} bars`)).toBeVisible()
    await target.getByTestId('secondary-panel-tabs').getByRole('tab', { name: '主力照妖镜' }).click()
    return target
  }

  const b10Page = await openRolloverPage(page, 10)
  await expect(b10Page.getByTestId('main-force-futures-pane-status')).toHaveText('state_warmup · MFM_FUTURES_V1_WARMUP')
  let chartBox = await b10Page.locator('.chart').boundingBox()
  if (!chartBox) throw new Error('B10 chart bounds unavailable')
  await b10Page.mouse.move(chartBox.x + chartBox.width * 0.92, chartBox.y + chartBox.height * 0.2)
  await expect(b10Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')
  await expect(b10Page.getByTestId('mfm-hover-state-ready')).toHaveText('state_ready false')
  await expect(b10Page.getByTestId('mfm-hover-caution-ready')).toHaveText('caution_ready false')

  const b21Page = await context.newPage()
  await openRolloverPage(b21Page, 21)
  await expect(b21Page.getByTestId('main-force-futures-pane-status')).toHaveText('caution_warmup · MFM_FUTURES_V1_CAUTION_WARMUP')
  chartBox = await b21Page.locator('.chart').boundingBox()
  if (!chartBox) throw new Error('B21 chart bounds unavailable')
  await b21Page.mouse.move(chartBox.x + chartBox.width * 0.92, chartBox.y + chartBox.height * 0.2)
  await expect(b21Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')
  await expect(b21Page.getByTestId('mfm-hover-state-ready')).toHaveText('state_ready true')
  await expect(b21Page.getByTestId('mfm-hover-caution-ready')).toHaveText('caution_ready false')

  const b31Page = await context.newPage()
  await recordCanvasText(b31Page)
  await openRolloverPage(b31Page, 31)
  await expect(b31Page.getByTestId('main-force-futures-pane-status')).toHaveText('ready · READY')
  chartBox = await b31Page.locator('.chart').boundingBox()
  if (!chartBox) throw new Error('B31 chart bounds unavailable')
  await b31Page.mouse.move(chartBox.x + chartBox.width * 0.92, chartBox.y + chartBox.height * 0.2)
  await expect(b31Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')
  await expect(b31Page.getByTestId('mfm-hover-state-ready')).toHaveText('state_ready true')
  await expect(b31Page.getByTestId('mfm-hover-caution-ready')).toHaveText('caution_ready true')
  await expect.poll(() => b31Page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining([expect.stringMatching(/^追[多空]小心/)]),
  )

  await b31Page.mouse.move(chartBox.x + chartBox.width * 0.9, chartBox.y + chartBox.height * 0.3)
  for (let index = 0; index < 10; index += 1) await b31Page.mouse.wheel(0, -300)
  await b31Page.mouse.move(chartBox.x + chartBox.width * 0.04, chartBox.y + chartBox.height * 0.2)
  await expect(b31Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')
  await b31Page.mouse.move(chartBox.x + chartBox.width * 0.92, chartBox.y + chartBox.height * 0.2)
  await expect(b31Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')

  await b31Page.evaluate(() => { window.__GUIYI_E2E_CANVAS_TEXT__ = [] })
  const tabs = b31Page.getByTestId('secondary-panel-tabs')
  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()
  await expect.poll(() => b31Page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__.length)).toBeGreaterThan(0)
  const contractBText = await b31Page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)
  expect(contractBText).not.toEqual(expect.arrayContaining([expect.stringMatching(/^追[多空]小心/)]))
  await b31Page.mouse.move(chartBox.x + chartBox.width * 0.04, chartBox.y + chartBox.height * 0.2)
  await expect(b31Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')
  await b31Page.mouse.move(chartBox.x + chartBox.width * 0.92, chartBox.y + chartBox.height * 0.2)
  await expect(b31Page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2612')
})

test('actual-dominant V1 hover follows the chart crosshair and exposes readiness without fabricated values', async ({ page }) => {
  const requests = []
  const fixtureBars = futuresFixture.bars.map((bar) => ({
    bar_end: bar.time, trading_day: bar.time.slice(0, 10), open: bar.open, high: bar.high, low: bar.low,
    close: bar.close, volume: bar.volume, turnover: null, open_interest: bar.open_interest,
  }))
  await mockChartMarketApi(page, requests, fixtureBars)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
  await expect(page.getByText('40 bars')).toBeVisible()
  await page.getByTestId('secondary-panel-tabs').getByRole('tab', { name: '主力照妖镜' }).click()
  const chart = page.locator('.chart')
  const box = await chart.boundingBox()
  if (!box) throw new Error('chart bounds unavailable')
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.2)

  await expect(page.getByTestId('mfm-hover-time')).toHaveText(futuresFixture.bars[21].time)
  await expect(page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2601')
  await expect(page.getByTestId('mfm-hover-state-ready')).toHaveText('state_ready true')
  await expect(page.getByTestId('mfm-hover-caution-ready')).toHaveText('caution_ready false')
  await expect(page.getByTestId('mfm-hover-availability')).toHaveText('可用性 小心预热')
  await expect(page.getByTestId('mfm-hover-availability-reason')).toHaveText('不可用原因 MFM_FUTURES_V1_CAUTION_WARMUP')
  await expect(page.getByTestId('mfm-hover-price-impulse')).not.toHaveText('价冲 —')
  await expect(page.getByTestId('mfm-hover-long-score')).toHaveText('多分 —')
})
