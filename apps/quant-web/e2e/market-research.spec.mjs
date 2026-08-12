import { expect, test } from '@playwright/test'

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

async function mockWorkspace(page, researchResponse) {
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) {
      return route.fulfill({ json: { items: [{ product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-08-11' }] } })
    }
    if (url.pathname.endsWith('/research/product')) return route.fulfill(researchResponse)
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: { symbol: 'ag', series_kind: 'actual_dominant', frequency: '15m', operational: true, phase: 'CLOSED', trading_day: '2026-08-11', live_eligible: false, live_available: false, live_contract: null, canonical_end: null, after_market: {} } })
    if (url.pathname.endsWith('/bars/page')) return route.fulfill({ json: { request: { series_kind: 'actual_dominant', symbol: 'ag', contract: null, frequency: '15m', before: null, limit: 1200 }, bars: Array.from({ length: 120 }, (_, index) => bar(index)), canonical_coverage: null, page: { has_more_before: false, next_before: null }, resolved_contract_segments: [] } })
    return route.abort()
  })
}

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
  await page.getByRole('button', { name: '研究', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('研究数据暂不可用', { exact: true })).toBeVisible()
})

test('HTDY stays opt-in and keeps its repainting-risk notice visible in the workspace', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '指标', exact: true }).click()
  await page.getByRole('checkbox', { name: /火天大有（原始观察）/ }).click()
  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toBeVisible()
})
