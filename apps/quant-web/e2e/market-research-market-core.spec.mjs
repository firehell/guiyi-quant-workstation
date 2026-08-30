import { expect, test } from '@playwright/test'
import {
  research,
  radarItem,
  sectorSummary,
  radar,
  dailyWatch,
  runtimeHealth,
  mockMarketHomepage,
  subing,
  mockWorkspace,
} from './market-research.helpers.mjs'

test.describe('Market core', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/alerts/strategy-actions/current', (route) => route.fulfill({
      json: { status: 'ready', trading_day: '2026-08-25', items: [] },
    }))
  })

test('Market homepage shows compact Runtime facts without implying provider delivery', async ({ page }) => {
  await mockMarketHomepage(page)
  await page.goto('/market')

  const strip = page.getByTestId('market-runtime-status')
  await expect(strip).toContainText('整体正常')
  await expect(strip).toContainText('实时正常')
  await expect(strip).toContainText('未获自然验证')
  await expect(strip).toContainText('服务商已接受（不代表送达）')
  await expect(strip).toContainText('已完成')
  await expect(strip).toContainText('2026-08-24 18:14')
  await expect(strip).not.toContainText('综合分')
  await expect(strip).not.toContainText('交易建议')
})

test('Market homepage accessibly distinguishes disabled Alert from missing natural observation', async ({ page }) => {
  const disabledRuntime = runtimeHealth()
  disabledRuntime.components.alert = {
    ...disabledRuntime.components.alert,
    status: 'disabled', configured_enabled: false,
    processing_state: 'unobserved', notification_state: 'unobserved',
    last_heartbeat_at: null, last_processed_bar_at: null,
  }
  await mockMarketHomepage(
    page,
    radar(),
    dailyWatch(),
    disabledRuntime,
  )
  await page.goto('/market')

  const strip = page.getByRole('region', { name: '运行状态' })
  await expect(strip).toContainText('提醒未启用')
  await expect(strip).not.toContainText('未获自然验证')
})

test('Market homepage refreshes Runtime, Strategy Actions and Daily with the bounded visibility policy', async ({ page }) => {
  const counts = { runtime: 0, radar: 0, daily: 0, strategy: 0 }
  await page.route('**/api/runtime/health', (route) => {
    counts.runtime += 1
    return route.fulfill({ json: runtimeHealth() })
  })
  await page.route('**/api/v1/market/research/radar', (route) => {
    counts.radar += 1
    return route.fulfill({ json: radar() })
  })
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => {
    counts.daily += 1
    return route.fulfill({ json: dailyWatch() })
  })
  await page.route('**/api/alerts/strategy-actions/current', (route) => {
    counts.strategy += 1
    return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-25', items: [] } })
  })

  await page.goto('/market')
  await expect.poll(() => ({ ...counts })).toEqual({ runtime: 1, radar: 1, daily: 1, strategy: 1 })

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect.poll(() => ({ ...counts })).toEqual({ runtime: 2, radar: 2, daily: 2, strategy: 2 })

  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await expect.poll(() => ({ ...counts })).toEqual({ runtime: 3, radar: 2, daily: 3, strategy: 3 })
})

test('Market homepage marks first Runtime failure unavailable and retains a stale successful snapshot', async ({ page }) => {
  let runtimeAttempt = 0
  await page.route('**/api/runtime/health', (route) => {
    runtimeAttempt += 1
    if (runtimeAttempt === 2) return route.fulfill({ json: runtimeHealth() })
    return route.fulfill({ status: 503 })
  })
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar() }))
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))

  await page.goto('/market')
  const strip = page.getByTestId('market-runtime-status')
  await expect(strip).toContainText('运行状态暂不可用')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(strip).toContainText('整体正常')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(strip).toContainText('状态已过期')
  await expect(strip).toContainText('整体正常')
})

test('Market homepage lists every price and open-interest structure without overlapping points', async ({ page }) => {
  const items = [
    radarItem({ symbol: 'rb', product_name: '螺纹钢', price_change_1d: -0.012, oi_change_1d: 0.034 }),
    radarItem({ symbol: 'jm', product_name: '焦煤', price_change_1d: 0.012, oi_change_1d: 0.021 }),
    radarItem({ symbol: 'sf', product_name: '硅铁', price_change_1d: -0.02, oi_change_1d: -0.015 }),
    radarItem({ symbol: 'au', product_name: '黄金', price_change_1d: 0.03, oi_change_1d: -0.01 }),
    radarItem({ symbol: 'a', product_name: '豆一', price_change_1d: 0, oi_change_1d: 0.01 }),
  ]
  await mockWorkspace(page, { json: research() })
  await mockMarketHomepage(page, radar({
    items,
    sector_summary: [sectorSummary('black', 0.01)],
  }))
  await page.goto('/market')
  await page.getByText('展开全市场研究', { exact: true }).click()

  const quadrants = page.getByTestId('market-quadrant-list')
  await expect(quadrants).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-down-increase').getByRole('button', { name: '打开 RB 螺纹钢' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-up-increase').getByRole('button', { name: '打开 JM 焦煤' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-down-decrease').getByRole('button', { name: '打开 SF 硅铁' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-up-decrease').getByRole('button', { name: '打开 AU 黄金' })).toBeVisible()
  await expect(quadrants.getByTestId('market-quadrant-neutral').getByRole('button', { name: '打开 A 豆一' })).toBeVisible()
  await expect(quadrants.getByRole('button')).toHaveCount(5)
  await expect(quadrants.locator('.market-scatter__point')).toHaveCount(0)

  await quadrants.getByRole('button', { name: '打开 JM 焦煤' }).click()
  await expect(page).toHaveURL(/\/market\/chart\?symbol=jm/)
})

test('Market homepage shows Radar skeletons while the initial snapshot is pending', async ({ page }) => {
  await page.route('**/api/v1/market/research/radar', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    await route.fulfill({ json: radar() })
  })
  await page.goto('/market')

  await expect(page.getByTestId('market-radar-skeleton')).toBeVisible()
  await expect(page.getByTestId('subing-daily-watch')).toBeVisible()
  await expect(page.getByTestId('market-radar-skeleton')).toHaveCount(0)
})

test('manual Radar refresh keeps the last snapshot on failure and updates on retry', async ({ page }) => {
  let attempt = 0
  await page.route('**/api/v1/market/research/radar', async (route) => {
    attempt += 1
    if (attempt === 2) return route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } })
    const asOf = attempt === 1 ? '2026-08-14' : '2026-08-15'
    return route.fulfill({ json: radar({ expected_as_of: asOf, target_as_of: asOf, data_as_of: asOf }) })
  })
  await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))
  await page.goto('/market')
  await page.getByText('展开全市场研究', { exact: true }).click()
  const summary = page.locator('.radar-summary')
  await expect(summary).toContainText('当前数据日期 2026-08-14')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '市场雷达刷新失败' })).toBeVisible()
  await expect(summary).toContainText('当前数据日期 2026-08-14')

  await page.getByRole('button', { name: '全部刷新' }).click()
  await expect(summary).toContainText('当前数据日期 2026-08-15')
  await expect(page.getByRole('alert').filter({ hasText: '市场雷达刷新失败' })).toHaveCount(0)
})

test('sector tabs always show the selected market sector without self-select controls', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('guiyi.market.workspace.preferences.v1', JSON.stringify({
      version: 1, symbol: null, seriesKind: 'actual_dominant', frequency: '15m',
      researchSidebarOpen: true, watchlist: ['a'],
    }))
  })
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: radar({
    items: [radarItem(), radarItem({ symbol: 'a', product_name: '豆一', sector: 'agriculture', price_change_1d: -0.004 })],
    sector_summary: [sectorSummary('black', 0.008), sectorSummary('agriculture', -0.004)],
  }) }))
  await page.goto('/market')

  await page.getByText('展开全市场研究', { exact: true }).click()

  const tabs = page.getByRole('tablist', { name: '按板块筛选' }).getByRole('tab')
  await expect(tabs).toHaveText(['黑色系 0.8%', '农产品 -0.4%'])
  await expect(tabs.first()).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.market-detail tbody tr')).toContainText('JM 焦煤')
  await expect(page.locator('.market-detail thead')).not.toContainText('状态')
  await expect(page.locator('.market-detail thead')).not.toContainText('自选')
  await expect(page.getByRole('button', { name: '自选', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '加入', exact: true })).toHaveCount(0)
  await tabs.nth(1).click()
  await expect(page.locator('.market-detail tbody tr')).toHaveCount(1)
  await expect(page.locator('.market-detail tbody tr')).toContainText('A 豆一')
  await expect(tabs.nth(1).locator('.market-detail__tab-median')).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
})

test('Market homepage stays inside the three desktop acceptance viewports', async ({ page }) => {
  await mockMarketHomepage(page)
  await page.goto('/market')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const box = await page.getByTestId('subing-daily-watch').boundingBox()
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  }
})
})
