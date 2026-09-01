import { expect, test } from '@playwright/test'
import { runtimeHealth } from './market-research.helpers.mjs'

test.describe('Market dashboard', () => {
  test('shows Runtime facts without implying provider delivery', async ({ page }) => {
    await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
    await page.goto('/market')

    await expect(page.getByRole('heading', { name: '行情看板' })).toBeVisible()
    const strip = page.getByTestId('market-runtime-status')
    await expect(strip).toContainText('整体正常')
    await expect(strip).toContainText('服务商已接受（不代表送达）')
  })

  test('contains no SuBing workbench and refreshes only Runtime', async ({ page }) => {
    const counts = { runtime: 0, daily: 0, strategy: 0 }
    await page.route('**/api/runtime/health', (route) => {
      counts.runtime += 1
      return route.fulfill({ json: runtimeHealth() })
    })
    await page.route('**/api/v1/market/research/subing-daily-watch/current', (route) => {
      counts.daily += 1
      return route.fulfill({ status: 500 })
    })
    await page.route('**/api/alerts/strategy-actions/current', (route) => {
      counts.strategy += 1
      return route.fulfill({ status: 500 })
    })

    await page.goto('/market')
    await expect(page.getByTestId('subing-workbench')).toHaveCount(0)
    await expect(page.getByText('研究观察工作台', { exact: true })).toHaveCount(0)
    await expect(page.getByText('苏冰策略事件', { exact: true })).toHaveCount(0)
    await expect(page.getByText('今日观察', { exact: true })).toHaveCount(0)
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 1, daily: 0, strategy: 0 })
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 2, daily: 0, strategy: 0 })
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect.poll(() => ({ ...counts })).toEqual({ runtime: 3, daily: 0, strategy: 0 })
  })

  test('retains a successful Runtime snapshot after a refresh failure', async ({ page }) => {
    let runtimeAttempt = 0
    await page.route('**/api/runtime/health', (route) => {
      runtimeAttempt += 1
      return runtimeAttempt === 2
        ? route.fulfill({ json: runtimeHealth() })
        : route.fulfill({ status: 503 })
    })
    await page.goto('/market')
    const strip = page.getByTestId('market-runtime-status')
    await expect(strip).toContainText('运行状态暂不可用')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(strip).toContainText('整体正常')
    await page.getByRole('button', { name: '全部刷新' }).click()
    await expect(strip).toContainText('状态已过期')
  })

  test('stays within desktop viewports', async ({ page }) => {
    await page.route('**/api/runtime/health', (route) => route.fulfill({ json: runtimeHealth() }))
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
