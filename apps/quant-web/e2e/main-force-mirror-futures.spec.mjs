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

async function mockChartMarketApi(page, requests, items = bars()) {
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
        resolved_contract_segments: [],
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

  await page.goto('/market/chart?symbol=ag&series_kind=contract&contract=AG2601&frequency=60m')
  await expect(page.getByText('96 bars')).toBeVisible()
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toBeEnabled()
})

test('futures mirror renders only signed scores and dynamic bilateral caution markers', async ({ page }) => {
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
  await mockChartMarketApi(page, requests, fixtureBars)

  await page.goto('/market/chart?symbol=ag&series_kind=contract&contract=AG2601&frequency=60m')
  await expect(page.getByText('40 bars')).toBeVisible()
  const shell = page.getByTestId('kline-shell')
  const tabs = page.getByTestId('secondary-panel-tabs')
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()

  await expect(shell).toHaveAttribute('data-main-force-futures-marker-count', '2')
  await expect(page.getByText('70 = 风险证据评分阈值，不是资金流比例或概率')).toBeVisible()
  await expect(page.locator('[data-main-force-futures-marker-count]')).not.toHaveAttribute('data-main-force-futures-marker-count', '4')
})

test('three-tab pane remains within each required desktop viewport', async ({ page }) => {
  const requests = []
  await mockChartMarketApi(page, requests)
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=60m')
    await expect(page.getByText('96 bars')).toBeVisible()
    await page.getByTestId('secondary-panel-tabs').getByRole('tab', { name: '主力照妖镜' }).click()
    await expect(page.getByText('70 = 风险证据评分阈值，不是资金流比例或概率')).toBeVisible()
    expect(await page.locator('body').evaluate((body) => body.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
