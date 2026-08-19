import { expect, test } from '@playwright/test'

function bars(count = 80) {
  return Array.from({ length: count }, (_, index) => {
    const barEnd = new Date(Date.UTC(2026, 0, index + 1, 7)).toISOString()
    const base = 100 + index * 0.6 + 4 * Math.sin(index / 2.2)
    const open = base + 0.7 * Math.sin(index * 1.7)
    const close = base + 1.1 * Math.sin(index * 1.1)
    return {
      bar_end: barEnd,
      trading_day: barEnd.slice(0, 10),
      open,
      high: Math.max(open, close) + 1.5 + (index % 3) * 0.2,
      low: Math.min(open, close) - 1.2 - (index % 4) * 0.15,
      close,
      volume: 1_000 + (index % 5) * 250 + index * 15,
      turnover: null,
      open_interest: null,
    }
  })
}

async function mockChartMarketApi(page, requests) {
  const items = bars()
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
          series_kind: 'actual_dominant', symbol: 'ag', contract: null,
          frequency: '15m', before: null, limit: 1200,
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
        symbol: 'ag', series_kind: 'actual_dominant', frequency: '15m', operational: false,
        phase: 'CLOSED', trading_day: '2026-08-19', live_eligible: false, live_available: false,
        live_contract: null, canonical_end: items.at(-1).bar_end, after_market: {},
      } })
      return
    }
    await route.fulfill({ status: 503, json: { detail: 'not required by secondary-panel test' } })
  })
}

test('secondary pane defaults to MACD and switches to main-force mirror without refetching bars', async ({ page }) => {
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

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('80 bars')).toBeVisible()

  const shell = page.getByTestId('kline-shell')
  const tabs = page.getByTestId('secondary-panel-tabs')
  await expect(tabs.getByRole('tab')).toHaveText(['MACD', '主力照妖镜'])
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  await expect(tabs.getByRole('tab', { name: 'MACD' })).toHaveAttribute('aria-selected', 'true')

  const barRequestsBeforeSwitch = requests.filter((url) => url.pathname.endsWith('/bars/page')).length
  await tabs.getByRole('tab', { name: '主力照妖镜' }).click()

  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror')
  await expect(tabs.getByRole('tab', { name: '主力照妖镜' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('小心＝HHV5/BARSLAST10 结构警戒，非实测资金流')).toBeVisible()
  expect(requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(barRequestsBeforeSwitch)

  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  expect(requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(barRequestsBeforeSwitch)
})
