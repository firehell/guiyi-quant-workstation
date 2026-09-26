import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'
for (const width of [1440, 390]) {
  test(`closed curve waits for pages and links records without changing totals at ${width}`, async ({ page }) => {
    await installNewowProductFixtures(page)
    await page.setViewportSize({ width, height: 900 })
    await page.goto(newowRoute())
    const curve = page.getByLabel('已完成参考交易累计收益曲线', { exact: true })
    await expect(curve).toContainText('尚未完整加载')
    await expect(curve.locator('circle')).toHaveCount(0)
    await page.getByRole('button', { name: '加载更多参考历史', exact: true }).click()
    await expect(curve.locator('circle')).toHaveCount(1)
    const points = await curve.locator('polyline').getAttribute('points')
    await curve.locator('circle').press('Enter')
    const selected = page.locator('.newow-reference__card[data-curve-selected="true"]')
    await expect(selected).toContainText('已清仓收益')
    await selected.getByRole('button', { name: '查看曲线', exact: true }).click()
    await expect(curve).toContainText('5.102')
    await page.getByLabel('筛选参考历史').selectOption('open')
    await expect(curve.locator('polyline')).toHaveAttribute('points', points)
    await expect(page.locator('.newow-reference__cards [data-reference-category="closed"]')).toHaveCount(0)
    await curve.locator('circle').press('Enter')
    await expect(selected).toBeVisible()
    await expect(curve).toContainText('未清仓浮动')
    await expect(curve).toContainText('中断结果')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `/private/tmp/newow-reference-curve-${width}.png`, fullPage: false })
  })
}
