import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const futuresFixture = JSON.parse(readFileSync(new URL('../../../tests/fixtures/main_force_mirror_futures_v1_golden.json', import.meta.url)))

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

async function mockChartMarketApi(page, requests, items = bars(), withAlignedAlert = false) {
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
        resolved_contract_segments: [{
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
      const bar = items.at(-8)
      const event = bar ? [{
        id: 601, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2601',
        trading_day: bar.trading_day, frequency: '60m', bar_end: bar.bar_end,
        result_codes: ['buy'], lower_tf_confirmation: false,
        detected_at: bar.bar_end, notification_attempted_at: null,
      }] : []
      await route.fulfill({ json: { status: 'ready', trading_day: items.at(-1)?.trading_day ?? null, items: withAlignedAlert ? event : [] } })
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

test('futures mirror renders only signed scores and preserves rendered Alert markers across tabs', async ({ page }) => {
  const requests = []
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
  await mockChartMarketApi(page, requests, fixtureBars, true)

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
  await expect(page.getByText('40 bars')).toBeVisible()
  await expect(page.getByTestId('product-today-alert-events').getByText('买入观察')).toBeVisible()
  const shell = page.getByTestId('kline-shell')
  const tabs = page.getByTestId('secondary-panel-tabs')
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()

  await expect(shell).toHaveAttribute('data-main-force-futures-marker-count', '2')
  await expect(shell).toHaveAttribute('data-rendered-alert-marker-count', '1')
  const renderedAlertSignature = await shell.getAttribute('data-rendered-alert-marker-signature')
  expect(renderedAlertSignature).toContain('alert:htdy_original_15m:ag:')
  await expect(page.getByText('70 = 风险证据评分阈值，不是资金流比例或概率')).toBeVisible()
  await expect(page.locator('[data-main-force-futures-marker-count]')).not.toHaveAttribute('data-main-force-futures-marker-count', '4')
  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await expect(shell).toHaveAttribute('data-main-force-futures-marker-count', '0')
  await expect(shell).toHaveAttribute('data-rendered-alert-marker-count', '1')
  await expect(shell).toHaveAttribute('data-rendered-alert-marker-signature', renderedAlertSignature)
  await tabs.getByRole('tab', { name: '原型V0' }).click()
  await expect(shell).toHaveAttribute('data-rendered-alert-marker-signature', renderedAlertSignature)
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()
  await expect(shell).toHaveAttribute('data-rendered-alert-marker-signature', renderedAlertSignature)
})

test('three-tab pane keeps rendered V1 content and controls within each required desktop viewport', async ({ page }) => {
  const requests = []
  const fixtureBars = futuresFixture.bars.map((bar) => ({
    bar_end: bar.time, trading_day: bar.time.slice(0, 10), open: bar.open, high: bar.high, low: bar.low,
    close: bar.close, volume: bar.volume, turnover: null, open_interest: bar.open_interest,
  }))
  await mockChartMarketApi(page, requests, fixtureBars, true)
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
    await expect(shell).toHaveAttribute('data-main-force-futures-marker-count', '2')
    await expect(page.getByTestId('main-force-futures-pane-status')).not.toContainText('unsupported')
    const chart = page.locator('.chart')
    const chartBox = await chart.boundingBox()
    if (!chartBox) throw new Error('chart bounds unavailable')
    await page.mouse.move(chartBox.x + chartBox.width * 0.5, chartBox.y + chartBox.height * 0.2)
    await expect(page.getByTestId('mfm-hover-contract')).toHaveText('合约 AG2601')
    const shellBox = await shell.boundingBox()
    const tabsBox = await tabs.boundingBox()
    const legendBox = await page.getByLabel('期货主力照妖镜图例').boundingBox()
    const hoverBox = await page.locator('.kline-hover-legend').boundingBox()
    if (!shellBox || !tabsBox || !legendBox || !hoverBox) throw new Error('kline bounds unavailable')
    for (const box of [tabsBox, legendBox, hoverBox]) {
      expect(box.x).toBeGreaterThanOrEqual(shellBox.x)
      expect(box.y).toBeGreaterThanOrEqual(shellBox.y)
      expect(box.x + box.width).toBeLessThanOrEqual(shellBox.x + shellBox.width)
      expect(box.y + box.height).toBeLessThanOrEqual(shellBox.y + shellBox.height)
    }
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('visible V1 pane status follows a warm-up viewport instead of the loaded tail', async ({ page }) => {
  const requests = []
  const fixtureBars = futuresFixture.bars.map((bar) => ({
    bar_end: bar.time, trading_day: bar.time.slice(0, 10), open: bar.open, high: bar.high, low: bar.low,
    close: bar.close, volume: bar.volume, turnover: null, open_interest: bar.open_interest,
  }))
  await mockChartMarketApi(page, requests, fixtureBars)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
  await page.getByTestId('secondary-panel-tabs').getByRole('tab', { name: '主力照妖镜' }).click()
  const chart = page.locator('.chart')
  const box = await chart.boundingBox()
  if (!box) throw new Error('chart bounds unavailable')
  const shell = page.getByTestId('kline-shell')
  const initialRange = await shell.getAttribute('data-visible-logical-range')
  await page.mouse.move(box.x + 8, box.y + box.height * 0.3)
  for (let index = 0; index < 8; index += 1) await page.mouse.wheel(0, -300)
  await expect.poll(() => shell.getAttribute('data-visible-logical-range')).not.toBe(initialRange)
  await expect(page.getByTestId('main-force-futures-pane-status')).toHaveText('state_warmup · MFM_FUTURES_V1_WARMUP')
  await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.3)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.05, box.y + box.height * 0.3, { steps: 8 })
  await page.mouse.up()
  await expect(page.getByTestId('main-force-futures-pane-status')).toHaveText('ready · READY')
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
