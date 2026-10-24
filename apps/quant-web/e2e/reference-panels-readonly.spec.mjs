import { test, expect } from '@playwright/test'
test.skip(process.env.REAL_BACKEND !== '1', 'requires explicit local read-only market backend')
test.use({ launchOptions: { args: ['--js-flags=--max-old-space-size=384'] } })

test('SuBing reference failure and actual mode retain chart MACD', async ({ page }) => {
  await page.route('**/market/jm/subing/reference?*', route => route.fulfill({ status: 503, json: { detail: { code: 'SUBING_REFERENCE_BUDGET_EXCEEDED' } } }))
  await page.goto('/market/chart?view=subing&symbol=jm&series_kind=actual_dominant&frequency=15m')
  const chart = page.getByTestId('kline-shell')
  await expect.poll(async () => Number(await chart.getAttribute('data-macd-point-count'))).toBeGreaterThan(30)
  await expect(page.getByRole('alert').filter({ hasText: '历史参考' })).toBeVisible()
  await page.getByRole('button', { name: '实际记录', exact: true }).click()
  await expect.poll(async () => Number(await chart.getAttribute('data-macd-point-count'))).toBeGreaterThan(30)
})

test('HTDY uses shared reference panel, formatted returns and detail actions', async ({ page }) => {
  await page.goto('/market/chart?view=htdy&symbol=jm&series_kind=actual_dominant&frequency=15m')
  const panel = page.locator('.htdy-history')
  await expect(panel.getByRole('heading', { name: '策略收益与参考记录' })).toBeVisible()
  await expect(panel.locator('tbody tr').first()).toBeVisible({ timeout: 40000 })
  await expect(panel.getByText('胜率', { exact: false }).first()).toBeVisible()
  const returnText = await panel.locator('tbody tr').nth(1).locator('td').nth(5).innerText()
  expect(returnText).toMatch(/^[+−-]?\d+\.\d{2}%$/)
  await panel.getByRole('button', { name: '查看详情', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: '火天大有历史参考详情' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true)
})
