import { test, expect } from '@playwright/test'
import { buildNewowSplitFixtureEnvelopeForTest, installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'

for (const width of [1440, 390]) {
  test(`selected split reference curve retains gap, owner and keyboard geometry at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
      if (section !== 'reference' || url.searchParams.get('reference_part') !== 'panel'
        || url.searchParams.get('reference_mode') !== 'holding') return
      const payload = buildNewowSplitFixtureEnvelopeForTest(url)
      payload.reference.value.curve.points = [
        { position: 0, bar_end: '2026-09-01T07:00:00Z', trading_day: '2026-09-01', segment_id: 'first', value: '0' },
        { position: 1, bar_end: '2026-09-01T08:00:00Z', trading_day: '2026-09-01', segment_id: 'first', value: '1' },
        { position: 2, bar_end: '2026-09-02T07:00:00Z', trading_day: '2026-09-02', segment_id: 'second', value: null },
        { position: 3, bar_end: '2026-09-03T07:00:00Z', trading_day: '2026-09-03', segment_id: 'second', value: '3' },
      ]
      payload.reference.value.curve.total_points = 4
      await route.fulfill({ json: payload })
      return 'handled'
    } })
    await page.goto(newowRoute())
    const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
    await region.scrollIntoViewIfNeeded()
    await region.getByRole('button', { name: '含浮动参考' }).click()
    const svg = region.locator('.newow-reference__curve .return-curve svg')
    await expect(svg).toBeVisible()
    await expect(svg.locator('polyline')).toHaveCount(2)
    const segments = await svg.locator('polyline').evaluateAll(nodes => nodes.map(node => node.getAttribute('points')))
    expect(segments.every(value => !value.includes('NaN'))).toBe(true)
    const box = await svg.boundingBox()
    expect(box.width).toBeGreaterThan(100)
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(width)
    await svg.focus()
    await svg.press('End')
    await expect(region.locator('.return-curve__readout')).toContainText('2026-09-03')
  })
}

for (const width of [1440, 390]) {
  test(`two single-point owners stay separate and visible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
      if (section !== 'reference' || url.searchParams.get('reference_part') !== 'panel'
        || url.searchParams.get('reference_mode') !== 'page_ordinary') return
      const payload = buildNewowSplitFixtureEnvelopeForTest(url)
      payload.reference.value.curve.points = [
        { position: 0, bar_end: '2026-06-01T07:00:00Z', trading_day: '2026-06-01', segment_id: 'first', value: '1' },
        { position: 100, bar_end: '2026-09-03T07:00:00Z', trading_day: '2026-09-03', segment_id: 'second', value: '3' },
      ]
      payload.reference.value.curve.total_points = 101
      payload.reference.value.curve.sampled = true
      await route.fulfill({ json: payload })
      return 'handled'
    } })
    await page.goto(newowRoute())
    const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
    await region.scrollIntoViewIfNeeded()
    const svg = region.locator('.page-performance .return-curve svg')
    await expect(svg).toBeVisible()
    const segments = await svg.locator('polyline.return-curve__line').evaluateAll(nodes => nodes.map(node => node.getAttribute('points')?.trim().split(/\s+/)))
    expect(segments).toHaveLength(2)
    expect(segments.every(part => part.length === 1)).toBe(true)
    const dots = svg.locator('circle.return-curve__isolated')
    await expect(dots).toHaveCount(2)
    expect(await dots.evaluateAll(nodes => nodes.every(node => {
      const box = node.getBoundingClientRect()
      return box.width > 0 && box.height > 0 && getComputedStyle(node).fill !== 'none'
    }))).toBe(true)
  })
}
