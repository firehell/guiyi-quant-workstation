import { expect, test } from '@playwright/test'
import { mockWorkspace, research } from './market-research.helpers.mjs'

const freeAg = '/market/chart?symbol=ag&view=free&series_kind=actual_dominant&frequency=15m'

test('unified Free keeps research in disclosures and chart usable at desktop and narrow widths', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.goto(freeAg)
  await expect(page.getByTestId('kline-shell')).toBeVisible()
  await expect(page.locator('.product-workspace__sidebar')).toHaveCount(0)
  for (const width of [1680, 1440, 1280, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  await page.getByText('市场背景', { exact: true }).click()
  await expect(page.getByText('日线趋势', { exact: true })).toBeVisible()
  await expect(page.getByText('20日位置', { exact: true })).toBeVisible()
  await page.getByText('市场背景', { exact: true }).click()
  await expect(page.getByText('20日位置', { exact: true })).not.toBeVisible()
})

test('missing OI does not fabricate research facts', async ({ page }) => {
  await mockWorkspace(page, { json: research(null) })
  await page.goto(freeAg)
  await expect(page.getByTestId('kline-shell')).toBeVisible()
  await page.getByText('市场背景', { exact: true }).click()
  await expect(page.getByText('OI 1D', { exact: true }).locator('..')).toContainText('—')
})

test('research endpoint failure leaves the unified Kline readable', async ({ page }) => {
  await mockWorkspace(page, { status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QUERY_WINDOW_EMPTY' } }) })
  await page.goto(freeAg)
  await expect(page.getByTestId('kline-shell')).toBeVisible()
  await page.getByText('市场背景', { exact: true }).click()
  await expect(page.locator('#detail-disclosure-market-background').getByText('市场背景暂不可用', { exact: true })).toBeVisible()
})

test('HTDY is an explicit view and its in-chart legend clears on Free switch', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.goto(freeAg)
  await expect(page.getByTestId('htdy-chart-legend')).toHaveCount(0)
  await page.getByRole('tab', { name: '火天大有', exact: true }).click()
  const legend = page.getByTestId('htdy-chart-legend')
  await expect(legend).toBeVisible()
  for (const text of ['ZK1 上轨', 'ZD1 下轨', 'ZD2 趋势']) await expect(legend.getByText(text, { exact: true })).toBeVisible()
  await page.getByTestId('kline-shell').scrollIntoViewIfNeeded()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
  const shellBox = await page.getByTestId('kline-shell').boundingBox()
  await page.mouse.move(shellBox.x + 240, shellBox.y + 220)
  const hoverLegend = page.locator('.kline-hover-legend')
  await expect(hoverLegend).toBeVisible()
  expect((await legend.boundingBox()).y).toBeGreaterThanOrEqual((await hoverLegend.boundingBox()).y + (await hoverLegend.boundingBox()).height + 4)
  await page.getByRole('tab', { name: '自由看盘', exact: true }).click()
  await expect(legend).toHaveCount(0)
})

test('after-market failure stays visible without hiding valid Canonical or claiming normal data', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, { afterMarket: { last_failure: { code: 'UPDATE_FAILED' } } })
  await page.goto(freeAg)
  await expect(page.getByTestId('kline-shell')).toBeVisible()
  await expect(page.locator('.quote-header__status')).toHaveText('最近盘后更新失败')
  await expect(page.locator('.quote-header__price strong')).not.toHaveText('—')
  await expect(page.getByText('数据正常', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /更多行情数据/ }).click()
  await expect(page.getByText('当前状态', { exact: true }).locator('..')).toContainText('最近盘后更新失败')
})
