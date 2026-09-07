import { expect, test } from '@playwright/test'
import { NEWOW_FREQUENCIES, NEWOW_STRATEGIES, installNewowProductFixtures, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

for (const strategy of NEWOW_STRATEGIES) for (const frequency of NEWOW_FREQUENCIES) {
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

test('cup failure retains the selected pane and its lifecycle, then restores through the single loader', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url }) => {
    if (url.searchParams.get('component') === 'cup_handle') {
      await route.fulfill({ status: 503, json: { detail: { code: 'NEWOW_API_UNAVAILABLE' } } })
      return 'handled'
    }
  } })
  await page.goto(newowRoute())
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
  await page.getByRole('button', { name: '杯柄说明', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('NEWOW_API_UNAVAILABLE')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
  await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
  await page.keyboard.press('Escape')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
  await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
  expect(productRequests(fixture, 'chart')).toHaveLength(1)
  expect(productRequests(fixture, 'auxiliary').map(item => item.url.searchParams.get('component'))).toEqual(['macd', 'cup_handle'])
  await page.getByRole('button', { name: '60m', exact: true }).click()
  await expect(stage).toHaveAttribute('data-frequency', '60m')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
  assertNoUnexpectedRequests(fixture)
})


test('late cup response cannot restore a pane from a previous strategy identity', async ({ page }) => {
  let releaseCup
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url }) => {
    if (url.searchParams.get('component') !== 'cup_handle') return
    await new Promise(resolve => { releaseCup = async () => {
      try { await route.fulfill({ status: 503, json: { detail: { code: 'NEWOW_API_UNAVAILABLE' } } }) } catch {}
      resolve()
    } })
    return 'handled'
  } })
  await page.goto(newowRoute())
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
  await page.getByRole('button', { name: '杯柄说明', exact: true }).click()
  await expect.poll(() => typeof releaseCup).toBe('function')
  await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
  await page.getByRole('button', { name: '震荡', exact: true }).evaluate(element => element.click())
  await expect(stage).toHaveAttribute('data-strategy', 'oscillation')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await expect(stage).toHaveAttribute('data-auxiliary-component', 'macd')
  await releaseCup()
  await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
  expect(productRequests(fixture, 'chart')).toHaveLength(2)
  expect(productRequests(fixture, 'auxiliary').filter(item => item.strategy === 'oscillation')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})
