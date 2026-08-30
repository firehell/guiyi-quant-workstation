import { expect, test } from '@playwright/test'
import {
  research,
  mockWorkspace,
  mockAlertMarkerSurface,
  openDataDetails,
} from './market-research.helpers.mjs'

test.describe('Chart interaction', () => {
test('shows one identity-matched research snapshot without crowding desktop Kline', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByTestId('product-status-strip')).toContainText('Historical')
  await expect(page.getByTestId('product-status-strip')).toContainText('已收盘')
  await expect(page.getByTestId('product-status-strip')).toContainText('数据正常')
  await expect(page.getByText('Price / Volume / OI', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('product-check-background')).toContainText('日线')
  await expect(page.getByTestId('product-check-background')).toContainText('上行')
  await expect(page.getByTestId('product-check-background')).toContainText('20日位置')
  const details = await openDataDetails(page)
  await expect(details.getByText('Price / Volume / OI')).toBeVisible()
  await expect(page.locator('.product-workspace__sidebar')).toBeVisible()
})

test('status strip surfaces after-market failure instead of a normal-data claim', async ({ page }) => {
  await mockWorkspace(page, { json: research() }, {
    afterMarket: { last_failure: { code: 'UPDATE_FAILED' } },
  })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const status = page.getByTestId('product-status-strip')
  await expect(status).toContainText('最近盘后更新失败')
  await expect(status).not.toContainText('数据正常')
})

test('research control toggles the inline sidebar instead of opening a duplicate drawer at 1280px', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  const sidebar = page.locator('.product-workspace__sidebar')
  const researchControl = page.getByRole('button', { name: '检查', exact: true })
  await expect(sidebar).toBeVisible()
  await researchControl.click()
  await expect(sidebar).toBeHidden()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await researchControl.click()
  await expect(sidebar).toBeVisible()
})

test('Product Workspace stays inside desktop widths and exposes the Check drawer at 1024', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await mockAlertMarkerSurface(page)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }

  await page.getByRole('button', { name: '检查', exact: true }).click()
  const drawer = page.getByRole('dialog')
  await expect(drawer).toContainText('检查')
  await expect(drawer.getByTestId('product-check-observation')).toBeVisible()
  await expect(drawer.getByTestId('product-check-data-details')).not.toHaveAttribute('open')
})

test('keeps Kline usable when research is unavailable and does not invent missing OI', async ({ page }) => {
  await mockWorkspace(page, { json: research(null) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  const details = await openDataDetails(page)
  await expect(details.getByText('OI 暂无可用数据')).toBeVisible()
})

test('research endpoint failure leaves the Kline readable', async ({ page }) => {
  await mockWorkspace(page, { status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QUERY_WINDOW_EMPTY' } }) })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('120 bars')).toBeVisible()
  await expect(page.getByTestId('product-check-background')).toContainText('市场背景数据不可用')
})

test('HTDY stays opt-in and uses an in-chart legend without the redundant risk banner', async ({ page }) => {
  await mockWorkspace(page, { json: research() })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('htdy-chart-legend')).toHaveCount(0)
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(page.getByText('火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察', { exact: true })).toHaveCount(0)
  const legend = page.getByTestId('htdy-chart-legend')
  await expect(legend).toBeVisible()
  await expect(legend.getByText('ZK1 上轨', { exact: true })).toBeVisible()
  await expect(legend.getByText('ZD1 下轨', { exact: true })).toBeVisible()
  await expect(legend.getByText('ZD2 趋势', { exact: true })).toBeVisible()

  const shellBox = await page.getByTestId('kline-shell').boundingBox()
  expect(shellBox).not.toBeNull()
  await page.mouse.move(shellBox.x + 240, shellBox.y + 220)
  const hoverLegend = page.locator('.kline-hover-legend')
  await expect(hoverLegend).toBeVisible()
  const hoverBox = await hoverLegend.boundingBox()
  const legendBox = await legend.boundingBox()
  expect(hoverBox).not.toBeNull()
  expect(legendBox).not.toBeNull()
  expect(legendBox.y).toBeGreaterThanOrEqual(hoverBox.y + hoverBox.height + 4)
})
})
