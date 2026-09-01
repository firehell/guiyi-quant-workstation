import { expect, test } from '@playwright/test'
import { dailyWatch, runtimeHealth, mockMarketHomepage } from './market-research.helpers.mjs'

test.describe('Market dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/alerts/strategy-actions/current', (route) => route.fulfill({
      json: { status: 'ready', trading_day: '2026-08-25', items: [] },
    }))
  })

  test('shows Runtime facts without implying provider delivery', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.goto('/market')

    await expect(page.getByRole('heading', { name: '行情看板' })).toBeVisible()
    const strip = page.getByTestId('market-runtime-status')
    await expect(strip).toContainText('整体正常')
    await expect(strip).toContainText('服务商已接受（不代表送达）')
  })

  test('refreshes only Runtime, Strategy Actions and Daily Watch', async ({ page }) => {
    const counts = { runtime: 0, daily: 0, strategy: 0, radar: 0 }
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/market/research/radar')) counts.radar += 1
    })
    await page.route('**/api/runtime/health', (route) => {
      counts.runtime += 1
      return route.fulfill({ json: runtimeHealth() })
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
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 1, daily: 1, strategy: 1, radar: 0 })
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 2, daily: 2, strategy: 2, radar: 0 })
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 3, daily: 3, strategy: 3, radar: 0 })
  })

  test('retains a successful Runtime snapshot after a refresh failure', async ({ page }) => {
    let runtimeAttempt = 0
    await page.route('**/api/runtime/health', (route) => {
      runtimeAttempt += 1
      return runtimeAttempt === 2
        ? route.fulfill({ json: runtimeHealth() })
        : route.fulfill({ status: 503 })
    })
    await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => route.fulfill({ json: dailyWatch() }))

    await page.goto('/market')
    const strip = page.getByTestId('market-runtime-status')
    await expect(strip).toContainText('运行状态暂不可用')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(strip).toContainText('整体正常')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(strip).toContainText('状态已过期')
  })

  test('stays within desktop viewports', async ({ page }) => {
    await mockMarketHomepage(page)
    await page.goto('/market')

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
      { width: 1024, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    }
  })
})
