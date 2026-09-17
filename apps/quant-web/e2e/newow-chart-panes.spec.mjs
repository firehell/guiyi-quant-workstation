import { expect, test } from '@playwright/test'
import { NEWOW_STRATEGIES, installNewowProductFixtures, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

for (const strategy of NEWOW_STRATEGIES) for (const frequency of ['1d']) {
  test(`${strategy} ${frequency}: native panes, indicator replacement and exact Hint dialog`, async ({ page }) => {
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const fixture = await installNewowProductFixtures(page)
    await page.goto(newowRoute(strategy, frequency))
    const stage = page.getByTestId('newow-product-chart-stage')
    await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
    await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
    // Three native panes and one shared timeline have three cells; separator rows are excluded.
    await expect(stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })).toHaveCount(4)
    const nativeRows = stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })
    const paneHeights = await nativeRows.evaluateAll(rows => rows.slice(0, 3).map(row => row.getBoundingClientRect().height))
    expect(paneHeights[0]).toBeGreaterThanOrEqual(280)
    expect(paneHeights[1]).toBeGreaterThanOrEqual(64)
    expect(paneHeights[2]).toBeGreaterThanOrEqual(112)
    await expect(stage.locator('.newow-product-chart-stage__volume-label')).toBeVisible()
    await expect.poll(async () => {
      const native = await nativeRows.nth(2).boundingBox()
      const controls = await stage.locator('.newow-product-chart-stage__auxiliary-toolbar').boundingBox()
      return Math.abs(native.y - controls.y)
    }).toBeLessThanOrEqual(4)
    expect(productRequests(fixture, 'auxiliary').map(item => item.url.searchParams.get('component'))).toEqual(['macd'])
    for (const [label, component] of [['照妖镜', 'zhaoyao_mirror'], ['涨跌动能', 'up_down_energy'], ['主力控盘', 'main_force_control'], ['MACD', 'macd']]) {
      const button = page.getByRole('button', { name: label, exact: true })
      await button.click()
      await expect(stage).toHaveAttribute('data-auxiliary-component', component)
      await expect(button).toHaveAttribute('aria-pressed', 'true')
      const count = productRequests(fixture, 'auxiliary').length
      await button.click()
      expect(productRequests(fixture, 'auxiliary')).toHaveLength(count)
      await expect(stage.locator('tr').filter({ has: page.locator('td:nth-child(3)') })).toHaveCount(4)
    }
    expect(productRequests(fixture, 'chart')).toHaveLength(1)
    expect(productRequests(fixture, 'explanation')).toHaveLength(0)
    await stage.getByText('过程提示', { exact: true }).click()
    const hint = stage.locator('[data-hint-id]').first()
    const id = await hint.getAttribute('data-hint-id')
    await hint.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('历史过程提示')
    await dialog.getByText('来源与原始事实', { exact: true }).click()
    await expect(dialog).toContainText(id)
    await expect(dialog).toContainText('known_at')
    expect(productRequests(fixture, 'explanation')).toHaveLength(0)
    await page.keyboard.press('Escape')
    if (strategy === 'trend' && frequency === '1d') {
      await page.getByRole('button', { name: '图表全屏', exact: true }).click()
      await expect.poll(() => stage.evaluate(element => document.fullscreenElement === element)).toBe(true)
      await page.getByRole('button', { name: '退出图表全屏', exact: true }).click()
      await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true)
      await stage.getByText('过程提示', { exact: true }).click()
      await stage.screenshot({ path: '/private/tmp/newow-task3-chart.png' })
    }
    expect(errors).toEqual([])
    assertNoUnexpectedRequests(fixture)
  })
}

test('weekly deep link remains closed without requesting strategy data', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('trend', '1w'))
  await expect(page.getByText('当前牛哇周期未开放', { exact: true })).toBeVisible()
  await expect(page.getByText(/1w 尚未开放/)).toBeVisible()
  expect(productRequests(fixture, 'chart')).toHaveLength(0)
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(0)
  assertNoUnexpectedRequests(fixture)
})
