import { expect, test } from '@playwright/test'
import { buildNewowSplitFixtureEnvelopeForTest, installNewowProductFixtures, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

for (const width of [1440, 390]) {
  test(`closed split curve locates an older trade while history pages at ${width}`, async ({ page }) => {
    const fixture = await installNewowProductFixtures(page, { recordsHistory: true, onProductRequest: async ({ route, url, section }) => {
      if (section !== 'reference' || url.searchParams.get('reference_mode') !== 'closed') return
      const payload = buildNewowSplitFixtureEnvelopeForTest(url, { recordsHistory: true })
      const value = payload.reference.value
      if (value.reference_part === 'history') {
        value.next_before = url.searchParams.has('history_before') ? null : 'reference-page-2'
      }
      if (value.reference_part === 'curve') {
        const closed = value.curve.points.toSorted((a, b) => a.bar_end.localeCompare(b.bar_end))
        value.curve.points = closed.map((point, position) => ({ ...point, position, value: position ? '10.2040' : '5.1020' }))
      }
      await route.fulfill({ json: payload })
      return 'handled'
    } })
    await page.setViewportSize({ width, height: 900 })
    await page.goto(newowRoute())
    const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
    await region.scrollIntoViewIfNeeded()
    await region.getByRole('button', { name: '已完成参考交易' }).click()
    const curve = region.getByLabel('参考收益曲线，点击查看读数或定位交易记录', { exact: true })
    await expect(curve).toBeVisible()
    await expect(region.getByTestId('newow-reference-summary')).toContainText('+10.2%')
    const points = await curve.locator('polyline').evaluateAll(nodes => nodes.map(node => node.getAttribute('points')))
    await expect(region.locator('article[data-reference-category]')).toHaveCount(3)
    expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(0)
    await region.getByRole('button', { name: '查看完整历史记录' }).click()
    await expect(region.locator('article[data-reference-category]')).toHaveCount(2)
    await region.getByRole('button', { name: '加载更多历史参考记录' }).click()
    await expect(region.locator('article[data-reference-category]')).toHaveCount(4)
    expect(await curve.locator('polyline').evaluateAll(nodes => nodes.map(node => node.getAttribute('points')))).toEqual(points)
    await curve.focus()
    await curve.press('Home')
    await curve.press('Enter')
    await expect(region.locator('#reference-trade-trend-1d-initial')).toBeVisible()
    await expect(region.locator('#reference-trade-trend-1d-initial')).toContainText('RB2601')
    await expect(region.locator('article[data-reference-category="interrupted"]')).toContainText('物理合约区段结束')
    await expect(region.locator('article[data-reference-category="open"] .newow-reference__record-return')).toHaveAttribute('data-direction', 'down')
    await expect(region.locator('article[data-reference-category="closed"] .newow-reference__record-return').first()).toHaveAttribute('data-direction', 'up')
    expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    assertNoUnexpectedRequests(fixture)
  })
}
